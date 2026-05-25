from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from enum import Enum, auto
from pathlib import Path
from shutil import which

import aiohttp
import typer
from rich.text import Text

from pythinker_code.native import (
    is_native_build as _is_native_build,
)
from pythinker_code.native import (
    native_archive_asset_name,
    native_installer_asset_name,
    native_installer_release_url,
)
from pythinker_code.share import get_share_dir
from pythinker_code.ui.shell.console import console
from pythinker_code.ui.theme import get_tui_tokens as _get_tui_tokens
from pythinker_code.utils.aiohttp import new_client_session
from pythinker_code.utils.logging import logger

PYPI_JSON_URL = "https://pypi.org/pypi/pythinker-code/json"
CHANGELOG_URL_EN = "https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/CHANGELOG.md"

# Default upgrade command. `_detect_upgrade_command()` overrides this when the
# install method is recognizable from `sys.executable`.
UPGRADE_COMMAND = ["uv", "tool", "upgrade", "pythinker-code"]

LATEST_VERSION_FILE = get_share_dir() / "latest_version.txt"
LAST_UPDATE_CHECK_FILE = get_share_dir() / "last_update_check.txt"
AUTO_UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60

_UPDATE_LOCK = asyncio.Lock()

NATIVE_INSTALLER_MARKER = "__pythinker_native_installer__"


class UpdateResult(Enum):
    UPDATE_AVAILABLE = auto()
    UPDATED = auto()
    UP_TO_DATE = auto()
    FAILED = auto()
    UNSUPPORTED = auto()


def semver_tuple(version: str) -> tuple[int, int, int]:
    v = version.strip()
    if v.startswith("v"):
        v = v[1:]
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", v)
    if not match:
        return (0, 0, 0)
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def _detect_upgrade_command() -> list[str]:
    """Pick the right upgrade argv based on how this interpreter was installed."""
    if _is_native_build():
        return [NATIVE_INSTALLER_MARKER]
    exe = sys.executable.replace("\\", "/").lower()
    if "/uv/tools/" in exe:
        return ["uv", "tool", "upgrade", "pythinker-code"]
    if "/pipx/venvs/" in exe:
        return ["pipx", "upgrade", "pythinker-code"]
    return [sys.executable, "-m", "pip", "install", "--upgrade", "pythinker-code"]


def _format_upgrade_command(command: list[str]) -> str:
    if _is_windows():
        return subprocess.list2cmdline(command)
    return " ".join(shlex_quote(part) for part in command)


def shlex_quote(value: str) -> str:
    if not value:
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _spawn_detached_windows_upgrade(upgrade_command: list[str]) -> bool:
    """Launch the upgrade in a new console window that survives this process exit.

    Returns True if the helper was spawned. The new console sleeps a few seconds
    before invoking ``upgrade_command`` so the currently running ``pythinker.exe``
    has time to exit and release the executable lock that ``uv``/``pip`` would
    otherwise trip over with ``os error 32``.
    """
    if not _is_windows():
        return False
    if which("cmd") is None:
        return False
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    # `start "" cmd /k <inner>` opens a new console; `timeout` gives the parent
    # time to exit so the exe lock releases before the upgrade runs.
    formatted_command = _format_upgrade_command(upgrade_command)
    inner = (
        "echo Waiting for Pythinker to exit... "
        "& timeout /t 3 /nobreak >nul "
        f"& {formatted_command} "
        "& echo. "
        "& echo Upgrade finished. Press any key to close this window. "
        "& pause >nul"
    )
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", "cmd", "/k", inner],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError:
        logger.exception("Failed to spawn detached Windows upgrade:")
        return False
    return True


async def _get_latest_version(session: aiohttp.ClientSession) -> str | None:
    try:
        async with session.get(PYPI_JSON_URL) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            version = data.get("info", {}).get("version")
            return str(version).strip() if version else None
    except (TimeoutError, aiohttp.ClientError):
        logger.exception("Failed to fetch latest version from PyPI:")
        return None
    except Exception:
        logger.exception("Failed to parse PyPI response:")
        return None


def _auto_update_disabled() -> bool:
    from pythinker_code.utils.envvar import get_env_bool

    return get_env_bool("PYTHINKER_CLI_NO_AUTO_UPDATE")


def _is_running_from_source_checkout() -> bool:
    """Return true when invoked from this repository via ``uv run``/editable source.

    In that mode PyPI can legitimately have a newer released version than the
    checkout's local ``pyproject.toml`` version. Showing the normal upgrade
    banner is noisy and suggests replacing the developer checkout.
    """
    try:
        import pythinker_code

        package_path = Path(pythinker_code.__file__).resolve()
    except Exception:
        return False

    for parent in package_path.parents:
        pyproject = parent / "pyproject.toml"
        git_dir = parent / ".git"
        if pyproject.exists() and git_dir.exists():
            try:
                text = pyproject.read_text(encoding="utf-8")
            except OSError:
                return False
            return 'name = "pythinker-code"' in text or "name = 'pythinker-code'" in text
    return False


def _should_auto_check_for_updates(now: float | None = None) -> bool:
    if _auto_update_disabled() or _is_running_from_source_checkout():
        return False
    if not sys.stdout.isatty():
        return False

    now = time.time() if now is None else now
    try:
        last_check = LAST_UPDATE_CHECK_FILE.stat().st_mtime
    except FileNotFoundError:
        return True
    except OSError:
        logger.exception("Failed to read last update-check timestamp:")
        return True
    return now - last_check >= AUTO_UPDATE_CHECK_INTERVAL_SECONDS


def _mark_auto_update_check_attempt() -> None:
    try:
        LAST_UPDATE_CHECK_FILE.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        logger.exception("Failed to write last update-check timestamp:")


async def prompt_pre_start_update() -> None:
    """pythinker-x-style blocking update prompt for the interactive shell.

    Runs once at startup, before the agent loop. When a newer release exists,
    asks the user whether to update now. Accepting runs the update and exits so
    the user relaunches the new version; declining continues the current session
    (the 24h throttle governs how often the prompt reappears).
    """
    from pythinker_code.constant import VERSION as current_version

    if _auto_update_disabled() or _is_running_from_source_checkout():
        return
    if not sys.stdout.isatty():
        return

    latest_version = await _resolve_latest_version_for_prompt()
    if not latest_version:
        return
    if semver_tuple(latest_version) <= semver_tuple(current_version):
        return

    if not await _confirm_update_now(current_version, latest_version):
        return

    result = await do_update(print=True)
    if result is UpdateResult.UPDATED:
        # do_update() already printed "Updated successfully!" + the relaunch
        # hint. Wait for the user to acknowledge before exiting so the message
        # stays on screen instead of the process vanishing (which reads as a
        # crash) right after they chose "Update now".
        await _await_exit_acknowledgment()
        raise typer.Exit(0)


async def _await_exit_acknowledgment() -> None:
    """Block on a keypress so the update/relaunch message is readable before exit.

    Making the close user-initiated is the point: a fixed sleep would still
    close on its own and read as a crash. Runs ``input`` off the event loop;
    EOF/Ctrl-C just proceed to exit.
    """
    _t = _get_tui_tokens()
    console.print(
        f"\n[{_t.muted}]Press Enter to close Pythinker, then relaunch to use the new version.[/]"
    )
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, input)
    except (EOFError, KeyboardInterrupt):
        return


async def _resolve_latest_version_for_prompt() -> str | None:
    """Return the latest known release, fetching from PyPI only when the 24h
    throttle is due; otherwise fall back to the cached value."""
    if _should_auto_check_for_updates():
        _mark_auto_update_check_attempt()
        try:
            await do_update(print=False, check_only=True)
        except Exception:
            logger.exception("Pre-start update check failed:")
    try:
        return LATEST_VERSION_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


async def _confirm_update_now(current_version: str, latest_version: str) -> bool:
    from prompt_toolkit.shortcuts.choice_input import ChoiceInput

    console.print(_update_prompt_text(current_version, latest_version))
    try:
        selection = await ChoiceInput(
            message="Update now?",
            options=[("update", "Update now"), ("skip", "Skip")],
            default="update",
        ).prompt_async()
    except (EOFError, KeyboardInterrupt):
        return False
    return selection == "update"


def _update_prompt_text(current_version: str, latest_version: str) -> Text:
    upgrade_command = _detect_upgrade_command()
    if upgrade_command == [NATIVE_INSTALLER_MARKER]:
        update_method = "downloads the native updater automatically"
    else:
        update_method = _format_upgrade_command(upgrade_command)
    _t = _get_tui_tokens()
    return Text.assemble(
        ("\n  ✨ ", f"bold {_t.accent}"),
        ("Update available!", "bold"),
        (f" {current_version} -> {latest_version}", _t.muted),
        ("\n  Release notes: ", _t.muted),
        (CHANGELOG_URL_EN, f"{_t.muted} underline"),
        ("\n  Update method: ", _t.muted),
        (update_method, "bold"),
        ("\n", ""),
    )


async def _fetch_native_release_asset(
    session: aiohttp.ClientSession, asset_name: str, channel: str
) -> tuple[str, str] | None:
    """Return (download_url, sha256) for a native release asset, or None on failure."""
    url = native_installer_release_url(channel=channel)
    try:
        async with session.get(url, headers={"Accept": "application/vnd.github+json"}) as resp:
            if resp.status != 200:
                logger.warning("GitHub release lookup returned {status}", status=resp.status)
                return None
            payload = await resp.json()
    except Exception:
        logger.exception("Failed to look up native release")
        return None

    download_url: str | None = None
    sha256_url: str | None = None
    for asset in payload.get("assets", []):
        name = asset.get("name", "")
        if name == asset_name:
            download_url = asset.get("browser_download_url")
        elif name == asset_name + ".sha256":
            sha256_url = asset.get("browser_download_url")
    if not download_url or not sha256_url:
        logger.warning("Native asset {name} not found on release", name=asset_name)
        return None

    try:
        async with session.get(sha256_url) as resp:
            text = (await resp.text()).strip()
    except Exception:
        logger.exception("Failed to fetch native asset sha256")
        return None
    sha = text.split()[0] if text else ""
    if len(sha) != 64:
        logger.warning("Native asset sha256 has unexpected length: {n}", n=len(sha))
        return None
    return download_url, sha


def _run_native_installer(installer_path: Path) -> None:
    """Spawn the downloaded installer silently and exit this process."""
    subprocess.Popen(
        [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    sys.exit(0)


async def _download_native_asset(
    session: aiohttp.ClientSession, asset_name: str, download_url: str, destination: Path
) -> UpdateResult:
    try:
        async with session.get(download_url) as resp:
            if resp.status != 200:
                logger.warning(
                    "Native asset {name} download returned {status}",
                    name=asset_name,
                    status=resp.status,
                )
                return UpdateResult.FAILED
            with destination.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    fh.write(chunk)
    except Exception:
        logger.exception("Native asset {name} download failed", name=asset_name)
        return UpdateResult.FAILED
    return UpdateResult.UPDATED


def _verify_sha256(path: Path, expected_sha: str) -> bool:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(chunk)
    actual_sha = digest.hexdigest()
    if actual_sha != expected_sha:
        logger.error(
            "Native asset sha mismatch: expected={expected} actual={actual}",
            expected=expected_sha,
            actual=actual_sha,
        )
        return False
    return True


def _install_native_archive(archive: Path) -> UpdateResult:
    target = Path(sys.executable).resolve()
    extract_dir = archive.parent / "extract"
    extract_dir.mkdir()
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extract("pythinker", path=extract_dir, filter="data")
    except Exception:
        logger.exception("Failed to extract native archive")
        return UpdateResult.FAILED

    extracted = extract_dir / "pythinker"
    if not extracted.is_file():
        logger.error("Native archive did not contain a pythinker executable")
        return UpdateResult.FAILED

    replacement = target.with_name(f".{target.name}.new-{os.getpid()}")
    try:
        shutil.copyfile(extracted, replacement)
        replacement.chmod(target.stat().st_mode | 0o755)
        os.replace(replacement, target)
    except OSError:
        logger.exception("Failed to replace native executable:")
        with contextlib.suppress(OSError):
            replacement.unlink()
        return UpdateResult.FAILED
    return UpdateResult.UPDATED


async def _maybe_run_native_update(latest_version: str, channel: str = "latest") -> UpdateResult:
    """Native-build update path. Returns UPDATED on success; UPDATE_AVAILABLE if skipped."""
    if _auto_update_disabled():
        logger.info("PYTHINKER_CLI_NO_AUTO_UPDATE set; skipping native auto-update")
        return UpdateResult.UPDATE_AVAILABLE

    import tempfile

    asset_name = (
        native_installer_asset_name(latest_version)
        if _is_windows()
        else native_archive_asset_name(latest_version)
    )
    if asset_name is None:
        logger.warning("No native updater asset is published for this platform")
        return UpdateResult.FAILED

    timeout = aiohttp.ClientTimeout(total=120, sock_connect=10, sock_read=60)
    async with new_client_session(timeout=timeout) as session:
        fetched = await _fetch_native_release_asset(session, asset_name, channel)
        if fetched is None:
            return UpdateResult.FAILED
        download_url, expected_sha = fetched

        tmpdir = Path(tempfile.mkdtemp(prefix="pythinker-update-"))
        asset = tmpdir / asset_name
        download_result = await _download_native_asset(session, asset_name, download_url, asset)
        if download_result is UpdateResult.FAILED:
            return download_result

    if not _verify_sha256(asset, expected_sha):
        return UpdateResult.FAILED

    if _is_windows():
        _run_native_installer(asset)
        return UpdateResult.UPDATED  # unreachable; sys.exit fires inside _run_native_installer

    return _install_native_archive(asset)


async def do_update(*, print: bool = True, check_only: bool = False) -> UpdateResult:
    async with _UPDATE_LOCK:
        return await _do_update(print=print, check_only=check_only)


async def _do_update(*, print: bool, check_only: bool) -> UpdateResult:
    from pythinker_code.constant import VERSION as current_version

    _t = _get_tui_tokens()

    def _print(message: str) -> None:
        if print:
            console.print(message)

    timeout = aiohttp.ClientTimeout(total=15, sock_connect=5, sock_read=10)
    async with new_client_session(timeout=timeout) as session:
        logger.info("Checking for updates...")
        _print("Checking for updates...")
        latest_version = await _get_latest_version(session)
        if not latest_version:
            _print(f"[{_t.error}]Failed to check for updates.[/]")
            return UpdateResult.FAILED

    logger.debug("Latest version: {latest_version}", latest_version=latest_version)
    try:
        LATEST_VERSION_FILE.write_text(latest_version, encoding="utf-8")
    except OSError:
        logger.exception("Failed to cache latest version:")

    if semver_tuple(current_version) >= semver_tuple(latest_version):
        logger.debug("Already up to date: {current_version}", current_version=current_version)
        _print(f"[{_t.success}]Already up to date.[/]")
        return UpdateResult.UP_TO_DATE

    if check_only:
        logger.info(
            "Update available: current={current_version}, latest={latest_version}",
            current_version=current_version,
            latest_version=latest_version,
        )
        _print(f"[{_t.warning}]Update available: {latest_version}[/]")
        return UpdateResult.UPDATE_AVAILABLE

    upgrade_command = _detect_upgrade_command()
    upgrade_command_text = _format_upgrade_command(upgrade_command)
    logger.info(
        "Updating from {current_version} to {latest_version} via: {cmd}",
        current_version=current_version,
        latest_version=latest_version,
        cmd=upgrade_command_text,
    )
    _print(f"Updating pythinker-code {current_version} → {latest_version}...")
    if upgrade_command != [NATIVE_INSTALLER_MARKER]:
        _print(f"[{_t.muted}]Running: {upgrade_command_text}[/]")

    if upgrade_command == [NATIVE_INSTALLER_MARKER]:
        _print(f"[{_t.muted}]Downloading native updater...[/]")
        native_result = await _maybe_run_native_update(latest_version)
        if native_result is UpdateResult.UPDATE_AVAILABLE:
            _print(
                f"[{_t.warning}]Auto-update disabled. "
                "Download the new installer manually from "
                "https://github.com/mohamed-elkholy95/Pythinker-Code/releases/latest[/]"
            )
            return UpdateResult.UPDATE_AVAILABLE
        if native_result is UpdateResult.FAILED:
            _print(
                f"[{_t.error}]Native update failed. Download manually from the releases page.[/]"
            )
            return UpdateResult.FAILED
        if native_result is UpdateResult.UPDATED:
            _print(f"[{_t.success}]Updated successfully![/]")
            _print(f"[{_t.warning}]Restart Pythinker CLI to use the new version.[/]")
        return native_result

    # On Windows, the running pythinker.exe holds an exclusive lock on its own
    # binary. Any in-process `uv tool upgrade` / `pip install --upgrade` fails
    # with `os error 32` (file in use). Spawn the upgrade in a detached console
    # that waits a few seconds, then exit so the lock releases first.
    if _is_windows() and _spawn_detached_windows_upgrade(upgrade_command):
        _print(
            f"[{_t.warning}]Pythinker will exit so Windows can release the running executable.[/]"
        )
        _print(f"[{_t.muted}]The upgrade will continue in a new console window.[/]")
        # Brief pause so the user can read the banner before the process dies.
        await asyncio.sleep(1.0)
        sys.exit(0)

    try:
        result = subprocess.run(upgrade_command)
    except OSError as e:
        logger.exception("Upgrade failed:")
        _print(f"[{_t.error}]Upgrade failed:[/] {e}")
        _print(f"Please run manually: {upgrade_command_text}")
        return UpdateResult.FAILED

    if result.returncode == 0:
        _print(f"[{_t.success}]Updated successfully![/]")
        _print(f"[{_t.warning}]Restart Pythinker CLI to use the new version.[/]")
        return UpdateResult.UPDATED
    _print(f"[{_t.error}]Upgrade failed. Please try running manually:[/]")
    _print(f"  {upgrade_command_text}")
    return UpdateResult.FAILED
