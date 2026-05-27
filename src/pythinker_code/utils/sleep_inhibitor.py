"""Prevent idle system sleep while an agent turn is running.

This mirrors the PythinkerX design: a small cross-platform wrapper owns an
OS-specific sleep assertion and the caller only toggles "turn running" state.
The helper is best-effort; unsupported platforms or missing desktop helpers log
and continue without affecting the agent turn.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol, cast

from pythinker_code.utils.logging import logger

ASSERTION_REASON = "Pythinker is running an active turn"
APP_ID = "pythinker"
# Keep Linux blocker helpers alive long enough without periodic restarts.
# This is i32::MAX seconds, accepted by common sleep implementations.
BLOCKER_SLEEP_SECONDS = str(2**31 - 1)


class _PlatformSleepInhibitor(Protocol):
    def acquire(self) -> None: ...

    def release(self) -> None: ...


class SleepInhibitor:
    """Keep the machine awake while an agent turn is in progress when enabled."""

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self._turn_running = False
        self._platform = _make_platform_inhibitor()

    def set_turn_running(self, turn_running: bool) -> None:
        """Update active-turn state and acquire/release the OS assertion as needed."""
        self._turn_running = turn_running
        if not self._enabled:
            self.release()
            return

        if turn_running:
            self.acquire()
        else:
            self.release()

    def acquire(self) -> None:
        self._platform.acquire()

    def release(self) -> None:
        self._platform.release()

    def is_turn_running(self) -> bool:
        """Return the latest turn-running state requested by the caller."""
        return self._turn_running

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()


class _NoopSleepInhibitor:
    def acquire(self) -> None:
        return

    def release(self) -> None:
        return


class _LinuxBackend(Enum):
    SYSTEMD_INHIBIT = "systemd-inhibit"
    GNOME_SESSION_INHIBIT = "gnome-session-inhibit"


class _LinuxSleepInhibitor:
    def __init__(self) -> None:
        self._child: subprocess.Popen[bytes] | None = None
        self._backend: _LinuxBackend | None = None
        self._preferred_backend: _LinuxBackend | None = None
        self._missing_backend_logged = False

    def acquire(self) -> None:
        if self._child is not None:
            status = self._child.poll()
            if status is None:
                return
            logger.warning(
                "Linux sleep inhibitor backend exited unexpectedly; attempting fallback "
                "(backend={backend}, status={status})",
                backend=self._backend.value if self._backend is not None else "unknown",
                status=status,
            )
            self._child = None
            self._backend = None

        should_log_backend_failures = not self._missing_backend_logged
        for backend in self._backend_order():
            try:
                child = _spawn_linux_backend(backend)
            except OSError as exc:
                if should_log_backend_failures and exc.errno != getattr(os, "ENOENT", 2):
                    logger.warning(
                        "Failed to start Linux sleep inhibitor backend "
                        "(backend={backend}, reason={reason})",
                        backend=backend.value,
                        reason=exc,
                    )
                continue
            except Exception as exc:
                if should_log_backend_failures:
                    logger.warning(
                        "Failed to start Linux sleep inhibitor backend "
                        "(backend={backend}, reason={reason})",
                        backend=backend.value,
                        reason=exc,
                    )
                continue

            status = child.poll()
            if status is None:
                self._child = child
                self._backend = backend
                self._preferred_backend = backend
                self._missing_backend_logged = False
                return

            if should_log_backend_failures:
                logger.warning(
                    "Linux sleep inhibitor backend exited immediately "
                    "(backend={backend}, status={status})",
                    backend=backend.value,
                    status=status,
                )
            _kill_and_reap_linux_child(child, backend)

        if should_log_backend_failures:
            logger.warning("No Linux sleep inhibitor backend is available")
            self._missing_backend_logged = True

    def release(self) -> None:
        child = self._child
        backend = self._backend
        self._child = None
        self._backend = None
        if child is not None:
            _kill_and_reap_linux_child(child, backend)

    def _backend_order(self) -> tuple[_LinuxBackend, _LinuxBackend]:
        if self._preferred_backend == _LinuxBackend.GNOME_SESSION_INHIBIT:
            return (_LinuxBackend.GNOME_SESSION_INHIBIT, _LinuxBackend.SYSTEMD_INHIBIT)
        return (_LinuxBackend.SYSTEMD_INHIBIT, _LinuxBackend.GNOME_SESSION_INHIBIT)

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()


_PR_SET_PDEATHSIG = 1
_LINUX_LIBC = ctypes.CDLL(None, use_errno=True) if sys.platform.startswith("linux") else None
_LINUX_PRCTL = getattr(_LINUX_LIBC, "prctl", None) if _LINUX_LIBC is not None else None
if _LINUX_PRCTL is not None:
    _LINUX_PRCTL.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    _LINUX_PRCTL.restype = ctypes.c_int


def _linux_parent_death_preexec(parent_pid: int) -> Callable[[], None]:
    def _preexec() -> None:
        if _LINUX_PRCTL is None:
            return
        if _LINUX_PRCTL(_PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0) == -1:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))
        if os.getppid() != parent_pid:
            os.kill(os.getpid(), signal.SIGTERM)

    return _preexec


def _spawn_linux_backend(backend: _LinuxBackend) -> subprocess.Popen[bytes]:
    if backend == _LinuxBackend.SYSTEMD_INHIBIT:
        args = [
            "systemd-inhibit",
            "--what=idle",
            "--mode=block",
            "--who",
            APP_ID,
            "--why",
            ASSERTION_REASON,
            "--",
            "sleep",
            BLOCKER_SLEEP_SECONDS,
        ]
    else:
        args = [
            "gnome-session-inhibit",
            "--inhibit",
            "idle",
            "--reason",
            ASSERTION_REASON,
            "sleep",
            BLOCKER_SLEEP_SECONDS,
        ]

    return subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=_linux_parent_death_preexec(os.getpid()),
    )


def _kill_and_reap_linux_child(
    child: subprocess.Popen[bytes], backend: _LinuxBackend | None
) -> None:
    backend_name = backend.value if backend is not None else "unknown"
    if child.poll() is None:
        try:
            child.kill()
        except OSError as exc:
            if child.poll() is None:
                logger.warning(
                    "Failed to stop Linux sleep inhibitor backend "
                    "(backend={backend}, reason={reason})",
                    backend=backend_name,
                    reason=exc,
                )
    try:
        child.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        logger.warning(
            "Timed out reaping Linux sleep inhibitor backend (backend={backend})",
            backend=backend_name,
        )
    except OSError as exc:
        logger.warning(
            "Failed to reap Linux sleep inhibitor backend (backend={backend}, reason={reason})",
            backend=backend_name,
            reason=exc,
        )


_K_CFSTRING_ENCODING_UTF8 = 0x08000100
_K_IOPM_ASSERTION_LEVEL_ON = 255
_K_IO_RETURN_SUCCESS = 0
_ASSERTION_TYPE_PREVENT_USER_IDLE_SYSTEM_SLEEP = "PreventUserIdleSystemSleep"


class _MacSleepInhibitor:
    def __init__(self) -> None:
        self._assertion_id: int | None = None
        self._core_foundation: ctypes.CDLL | None = None
        self._iokit: ctypes.CDLL | None = None

    def acquire(self) -> None:
        if self._assertion_id is not None:
            return
        try:
            assertion_id = self._create_assertion(ASSERTION_REASON)
        except Exception as exc:
            logger.warning(
                "Failed to create macOS sleep-prevention assertion (reason={reason})",
                reason=exc,
            )
            return
        self._assertion_id = assertion_id

    def release(self) -> None:
        assertion_id = self._assertion_id
        self._assertion_id = None
        if assertion_id is None:
            return
        try:
            iokit = self._load_iokit()
            result = iokit.IOPMAssertionRelease(ctypes.c_uint32(assertion_id))
        except Exception as exc:
            logger.warning(
                "Failed to release macOS sleep-prevention assertion (reason={reason})",
                reason=exc,
            )
            return
        if result != _K_IO_RETURN_SUCCESS:
            logger.warning(
                "Failed to release macOS sleep-prevention assertion (iokit_error={error})",
                error=result,
            )

    def _load_core_foundation(self) -> ctypes.CDLL:
        if self._core_foundation is None:
            core_foundation = ctypes.CDLL(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            core_foundation.CFStringCreateWithCString.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_uint32,
            ]
            core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
            core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
            core_foundation.CFRelease.restype = None
            self._core_foundation = core_foundation
        return self._core_foundation

    def _load_iokit(self) -> ctypes.CDLL:
        if self._iokit is None:
            iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
            iokit.IOPMAssertionCreateWithName.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            iokit.IOPMAssertionCreateWithName.restype = ctypes.c_int
            iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
            iokit.IOPMAssertionRelease.restype = ctypes.c_int
            self._iokit = iokit
        return self._iokit

    def _create_cf_string(self, text: str) -> ctypes.c_void_p:
        core_foundation = self._load_core_foundation()
        value = core_foundation.CFStringCreateWithCString(
            None,
            text.encode("utf-8"),
            _K_CFSTRING_ENCODING_UTF8,
        )
        if not value:
            raise RuntimeError("CFStringCreateWithCString returned null")
        return ctypes.c_void_p(value)

    def _create_assertion(self, reason: str) -> int:
        core_foundation = self._load_core_foundation()
        iokit = self._load_iokit()
        assertion_type = self._create_cf_string(_ASSERTION_TYPE_PREVENT_USER_IDLE_SYSTEM_SLEEP)
        assertion_name = self._create_cf_string(reason)
        assertion_id = ctypes.c_uint32(0)
        try:
            result = iokit.IOPMAssertionCreateWithName(
                assertion_type,
                _K_IOPM_ASSERTION_LEVEL_ON,
                assertion_name,
                ctypes.byref(assertion_id),
            )
        finally:
            core_foundation.CFRelease(assertion_type)
            core_foundation.CFRelease(assertion_name)
        if result != _K_IO_RETURN_SUCCESS:
            raise RuntimeError(f"IOPMAssertionCreateWithName returned {result}")
        return int(assertion_id.value)

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()


_POWER_REQUEST_CONTEXT_VERSION = 0
_POWER_REQUEST_CONTEXT_SIMPLE_STRING = 1
_POWER_REQUEST_SYSTEM_REQUIRED = 0
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _WindowsReasonContextReason(ctypes.Union):
    _fields_ = [("SimpleReasonString", ctypes.c_wchar_p)]


class _WindowsReasonContext(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_ulong),
        ("Flags", ctypes.c_ulong),
        ("Reason", _WindowsReasonContextReason),
    ]


class _WindowsSleepInhibitor:
    def __init__(self) -> None:
        self._handle: int | None = None
        self._request_type = _POWER_REQUEST_SYSTEM_REQUIRED
        self._kernel32: Any | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        try:
            self._handle = self._create_power_request(ASSERTION_REASON)
        except Exception as exc:
            logger.warning(
                "Failed to acquire Windows sleep-prevention request (reason={reason})",
                reason=exc,
            )

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        kernel32: Any = self._load_kernel32()
        if not kernel32.PowerClearRequest(handle, self._request_type):
            logger.warning(
                "Failed to clear Windows sleep-prevention request (reason={reason})",
                reason=_last_windows_error(),
            )
        if not kernel32.CloseHandle(handle):
            logger.warning(
                "Failed to close Windows sleep-prevention request handle (reason={reason})",
                reason=_last_windows_error(),
            )

    def _load_kernel32(self) -> Any:
        if self._kernel32 is None:
            ctypes_any = cast(Any, ctypes)
            kernel32: Any = ctypes_any.WinDLL("kernel32", use_last_error=True)
            kernel32.PowerCreateRequest.argtypes = [ctypes.POINTER(_WindowsReasonContext)]
            kernel32.PowerCreateRequest.restype = ctypes.c_void_p
            kernel32.PowerSetRequest.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel32.PowerSetRequest.restype = ctypes.c_int
            kernel32.PowerClearRequest.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel32.PowerClearRequest.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            self._kernel32 = kernel32
        return self._kernel32

    def _create_power_request(self, reason: str) -> int:
        kernel32: Any = self._load_kernel32()
        context = _WindowsReasonContext()
        context.Version = _POWER_REQUEST_CONTEXT_VERSION
        context.Flags = _POWER_REQUEST_CONTEXT_SIMPLE_STRING
        context.Reason.SimpleReasonString = reason

        handle = kernel32.PowerCreateRequest(ctypes.byref(context))
        if not handle or handle == _INVALID_HANDLE_VALUE:
            raise OSError(_last_windows_error())
        if not kernel32.PowerSetRequest(handle, self._request_type):
            error = _last_windows_error()
            kernel32.CloseHandle(handle)
            raise OSError(error)
        return int(handle)

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()


def _last_windows_error() -> str:
    ctypes_any = cast(Any, ctypes)
    error_code = int(ctypes_any.get_last_error())
    if error_code == 0:
        return "unknown Windows error"
    return str(ctypes_any.FormatError(error_code))


def _make_platform_inhibitor() -> _PlatformSleepInhibitor:
    if sys.platform.startswith("linux"):
        return _LinuxSleepInhibitor()
    if sys.platform == "darwin":
        return _MacSleepInhibitor()
    if sys.platform == "win32":
        return _WindowsSleepInhibitor()
    return _NoopSleepInhibitor()
