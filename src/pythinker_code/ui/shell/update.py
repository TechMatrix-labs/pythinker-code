from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
from enum import Enum, auto
from shutil import which

import aiohttp
from rich.text import Text

from pythinker_code.share import get_share_dir
from pythinker_code.ui.shell.console import console
from pythinker_code.utils.aiohttp import new_client_session
from pythinker_code.utils.logging import logger

PYPI_JSON_URL = "https://pypi.org/pypi/pythinker-code/json"
CHANGELOG_URL_EN = "https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/CHANGELOG.md"

# Default upgrade command. `_detect_upgrade_command()` overrides this when the
# install method is recognizable from `sys.executable`.
UPGRADE_COMMAND = ["uv", "tool", "upgrade", "pythinker-code"]

LATEST_VERSION_FILE = get_share_dir() / "latest_version.txt"
SKIPPED_VERSION_FILE = get_share_dir() / "skipped_version.txt"
LAST_UPDATE_CHECK_FILE = get_share_dir() / "last_update_check.txt"
AUTO_UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60

_UPDATE_LOCK = asyncio.Lock()


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


def _should_auto_check_for_updates(now: float | None = None) -> bool:
    if _auto_update_disabled():
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


def schedule_auto_update_check() -> asyncio.Task[UpdateResult] | None:
    """Schedule a silent, throttled PyPI update check for interactive shell startup."""
    if not _should_auto_check_for_updates():
        return None

    _mark_auto_update_check_attempt()
    task = asyncio.create_task(
        do_update(print=False, check_only=True),
        name="pythinker-update-check",
    )

    def _log_result(done: asyncio.Task[UpdateResult]) -> None:
        try:
            result = done.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Background update check failed:")
            return
        if result is UpdateResult.UPDATE_AVAILABLE:
            logger.info("Update available; showing notification banner")
            print_update_banner()

    task.add_done_callback(_log_result)
    return task


def print_update_banner() -> None:
    """Print a non-blocking 'Update Available' banner if a newer version is cached."""
    from pythinker_code.constant import VERSION as current_version

    if _auto_update_disabled():
        return
    if not sys.stdout.isatty():
        return
    if not LATEST_VERSION_FILE.exists():
        return

    try:
        latest_version = LATEST_VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not latest_version or semver_tuple(latest_version) <= semver_tuple(current_version):
        return

    if SKIPPED_VERSION_FILE.exists():
        try:
            skipped = SKIPPED_VERSION_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            skipped = ""
        if skipped == latest_version:
            return

    _render_update_banner(current_version, latest_version)


def _update_banner_text(current_version: str, latest_version: str) -> Text:
    upgrade_command = _detect_upgrade_command()
    upgrade_command_text = _format_upgrade_command(upgrade_command)
    return Text.assemble(
        ("  ✨ ", "bold cyan"),
        ("Update available!", "bold"),
        (f" {current_version} -> {latest_version}", "grey50"),
        ("\n\n  Release notes: ", "grey50"),
        (CHANGELOG_URL_EN, "grey50 underline"),
        ("\n\n  ", ""),
        ("1", "bold cyan"),
        (". Run ", ""),
        ("pythinker update", "bold cyan"),
        ("\n  ", ""),
        ("2", "bold cyan"),
        (". Or run ", ""),
        (upgrade_command_text, "bold"),
    )


def _render_update_banner(current_version: str, latest_version: str) -> None:
    console.print()
    console.print(_update_banner_text(current_version, latest_version))


async def do_update(*, print: bool = True, check_only: bool = False) -> UpdateResult:
    async with _UPDATE_LOCK:
        return await _do_update(print=print, check_only=check_only)


async def _do_update(*, print: bool, check_only: bool) -> UpdateResult:
    from pythinker_code.constant import VERSION as current_version

    def _print(message: str) -> None:
        if print:
            console.print(message)

    timeout = aiohttp.ClientTimeout(total=15, sock_connect=5, sock_read=10)
    async with new_client_session(timeout=timeout) as session:
        logger.info("Checking for updates...")
        _print("Checking for updates...")
        latest_version = await _get_latest_version(session)
        if not latest_version:
            _print("[red]Failed to check for updates.[/red]")
            return UpdateResult.FAILED

    logger.debug("Latest version: {latest_version}", latest_version=latest_version)
    try:
        LATEST_VERSION_FILE.write_text(latest_version, encoding="utf-8")
    except OSError:
        logger.exception("Failed to cache latest version:")

    if semver_tuple(current_version) >= semver_tuple(latest_version):
        logger.debug("Already up to date: {current_version}", current_version=current_version)
        _print("[green]Already up to date.[/green]")
        return UpdateResult.UP_TO_DATE

    if check_only:
        logger.info(
            "Update available: current={current_version}, latest={latest_version}",
            current_version=current_version,
            latest_version=latest_version,
        )
        _print(f"[yellow]Update available: {latest_version}[/yellow]")
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
    _print(f"[grey50]Running: {upgrade_command_text}[/grey50]")

    # On Windows, the running pythinker.exe holds an exclusive lock on its own
    # binary. Any in-process `uv tool upgrade` / `pip install --upgrade` fails
    # with `os error 32` (file in use). Spawn the upgrade in a detached console
    # that waits a few seconds, then exit so the lock releases first.
    if _is_windows() and _spawn_detached_windows_upgrade(upgrade_command):
        _print(
            "[yellow]Pythinker will exit so Windows can release the running executable.[/yellow]"
        )
        _print("[grey50]The upgrade will continue in a new console window.[/grey50]")
        # Brief pause so the user can read the banner before the process dies.
        await asyncio.sleep(1.0)
        sys.exit(0)

    try:
        result = subprocess.run(upgrade_command)
    except OSError as e:
        logger.exception("Upgrade failed:")
        _print(f"[red]Upgrade failed:[/red] {e}")
        _print(f"Please run manually: {upgrade_command_text}")
        return UpdateResult.FAILED

    if result.returncode == 0:
        _print("[green]Updated successfully![/green]")
        _print("[yellow]Restart Pythinker CLI to use the new version.[/yellow]")
        return UpdateResult.UPDATED
    _print("[red]Upgrade failed. Please try running manually:[/red]")
    _print(f"  {upgrade_command_text}")
    return UpdateResult.FAILED
