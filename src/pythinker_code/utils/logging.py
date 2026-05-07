from __future__ import annotations

import codecs
import contextlib
import locale
import os
import sys
import threading
from collections.abc import Iterator
from typing import IO, Any, cast


class _LazyLogger:
    """Import loguru only when logging is actually used."""

    def __init__(self) -> None:
        self._logger: Any | None = None

    def _get(self) -> Any:
        if self._logger is None:
            from loguru import logger as real_logger

            # Disable logging by default for library usage.
            # Application entry points should call logger.enable("pythinker_code")
            # to enable logging.
            real_logger.disable("pythinker_code")
            self._logger = real_logger
        return self._logger

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


logger = cast(Any, _LazyLogger())


class StderrRedirector:
    def __init__(self, level: str = "ERROR") -> None:
        self._level = level
        self._encoding: str | None = None
        self._installed = False
        self._lock = threading.Lock()
        self._original_fd: int | None = None
        self._read_fd: int | None = None
        self._thread: threading.Thread | None = None

    def install(self) -> None:
        with self._lock:
            if self._installed:
                return
            with contextlib.suppress(Exception):
                sys.stderr.flush()
            if self._original_fd is None:
                with contextlib.suppress(OSError):
                    self._original_fd = os.dup(2)
            if self._encoding is None:
                self._encoding = (
                    sys.stderr.encoding or locale.getpreferredencoding(False) or "utf-8"
                )
            read_fd, write_fd = os.pipe()
            os.dup2(write_fd, 2)
            os.close(write_fd)
            self._read_fd = read_fd
            self._thread = threading.Thread(
                target=self._drain, name="pythinker-stderr-redirect", daemon=True
            )
            self._thread.start()
            self._installed = True

    def uninstall(self) -> None:
        with self._lock:
            if not self._installed:
                return
            if self._original_fd is not None:
                os.dup2(self._original_fd, 2)
            self._installed = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _drain(self) -> None:
        buffer = ""
        read_fd = self._read_fd
        if read_fd is None:
            return
        encoding = self._encoding or "utf-8"
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        try:
            while True:
                chunk = os.read(read_fd, 4096)
                if not chunk:
                    break
                buffer += decoder.decode(chunk)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._log_line(line)
        except Exception:
            logger.exception("Failed to read redirected stderr")
        finally:
            buffer += decoder.decode(b"", final=True)
            if buffer:
                self._log_line(buffer)
            with contextlib.suppress(OSError):
                os.close(read_fd)

    def _log_line(self, line: str) -> None:
        text = line.rstrip("\r")
        if not text:
            return
        logger.opt(depth=2).log(self._level, text)

    def open_original_stderr_handle(self) -> IO[bytes] | None:
        if self._original_fd is None:
            return None
        dup_fd = os.dup(self._original_fd)
        os.set_inheritable(dup_fd, True)
        return os.fdopen(dup_fd, "wb", closefd=True)


_stderr_redirector: StderrRedirector | None = None


def redirect_stderr_to_logger(level: str = "ERROR") -> None:
    global _stderr_redirector
    if _stderr_redirector is None:
        _stderr_redirector = StderrRedirector(level=level)
    _stderr_redirector.install()


def restore_stderr() -> None:
    if _stderr_redirector is not None:
        _stderr_redirector.uninstall()


@contextlib.contextmanager
def open_original_stderr() -> Iterator[IO[bytes] | None]:
    redirector = _stderr_redirector
    if redirector is None:
        yield None
        return
    stream = redirector.open_original_stderr_handle()
    try:
        yield stream
    finally:
        if stream is not None:
            stream.close()
