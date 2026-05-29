"""
The local version of the Grep tool using ripgrep.
Be cautious that `HostPath` is not used in this implementation.
"""

import asyncio
import fnmatch
import os
import platform
import re
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import override

import aiohttp
from pydantic import BaseModel, Field, field_validator
from pythinker_core.tooling import CallableTool2, ToolError, ToolReturnValue

import pythinker_code
from pythinker_code.share import get_share_dir
from pythinker_code.tools.utils import ToolResultBuilder, load_desc
from pythinker_code.utils.aiohttp import new_client_session
from pythinker_code.utils.logging import logger
from pythinker_code.utils.sensitive import is_sensitive_file, sensitive_file_warning


class Params(BaseModel):
    pattern: str = Field(
        description="The regular expression pattern to search for in file contents"
    )
    path: str = Field(
        description=(
            "File or directory to search in. Defaults to current working directory. "
            "If specified, it must be an absolute path."
        ),
        default=".",
    )
    glob: str | None = Field(
        description=(
            "Glob pattern to filter files (e.g. `*.js`, `*.{ts,tsx}`). No filter by default."
        ),
        default=None,
    )
    output_mode: str = Field(
        description=(
            "`content`: Show matching lines (supports `-B`, `-A`, `-C`, `-n`, `head_limit`); "
            "`files_with_matches`: Show file paths (supports `head_limit`); "
            "`count_matches`: Show total number of matches. "
            "Defaults to `files_with_matches`."
        ),
        default="files_with_matches",
    )
    before_context: int | None = Field(
        alias="-B",
        description=(
            "Number of lines to show before each match (the `-B` option). "
            "Requires `output_mode` to be `content`."
        ),
        default=None,
    )
    after_context: int | None = Field(
        alias="-A",
        description=(
            "Number of lines to show after each match (the `-A` option). "
            "Requires `output_mode` to be `content`."
        ),
        default=None,
    )
    context: int | None = Field(
        alias="-C",
        description=(
            "Number of lines to show before and after each match (the `-C` option). "
            "Requires `output_mode` to be `content`."
        ),
        default=None,
    )
    line_number: bool = Field(
        alias="-n",
        description=(
            "Show line numbers in output (the `-n` option). "
            "Requires `output_mode` to be `content`. Defaults to true."
        ),
        default=True,
    )
    ignore_case: bool = Field(
        alias="-i",
        description="Case insensitive search (the `-i` option).",
        default=False,
    )
    type: str | None = Field(
        description=(
            "File type to search. Examples: py, rust, js, ts, go, java, etc. "
            "More efficient than `glob` for standard file types."
        ),
        default=None,
    )
    head_limit: int | None = Field(
        description=(
            "Limit output to first N lines/entries, equivalent to `| head -N`. "
            "Works across all output modes: content (limits output lines), "
            "files_with_matches (limits file paths), count_matches (limits count entries). "
            "Defaults to 250. "
            "Pass 0 for unlimited (use sparingly — large result sets waste context)."
        ),
        default=250,
        ge=0,
    )
    offset: int = Field(
        description=(
            "Skip first N lines/entries before applying head_limit, "
            "equivalent to `| tail -n +N | head -N`. "
            "Works across all output modes. Defaults to 0."
        ),
        default=0,
        ge=0,
    )
    multiline: bool = Field(
        description=(
            "Enable multiline mode where `.` matches newlines and patterns can span "
            "lines (the `-U` and `--multiline-dotall` options). "
            "By default, multiline mode is disabled."
        ),
        default=False,
    )
    include_ignored: bool = Field(
        description=(
            "Include files that are ignored by `.gitignore`, `.ignore`, and other ignore "
            "rules. Useful for searching gitignored artifacts such as build outputs "
            "(e.g. `dist/`, `build/`) or `node_modules`. Sensitive files (like `.env`) "
            "remain filtered by the sensitive-file protection layer. Defaults to false."
        ),
        default=False,
    )


RG_VERSION = "15.0.0"
RG_BASE_URL = "http://cdn.pythinker.com/binaries/pythinker-code/rg"
RG_GITHUB_BASE_URL = "https://github.com/BurntSushi/ripgrep/releases/download"
RG_TIMEOUT = 20  # seconds
RG_MAX_BUFFER = 20_000_000  # 20MB stdout/stderr buffer limit
RG_KILL_GRACE = 5  # seconds: SIGTERM → SIGKILL
_RG_DOWNLOAD_LOCK = asyncio.Lock()
_PYTHON_FALLBACK_TYPE_GLOBS = {
    "bash": ("*.bash", "*.sh"),
    "c": ("*.c", "*.h"),
    "cpp": ("*.cc", "*.cpp", "*.cxx", "*.hpp", "*.hxx"),
    "go": ("*.go",),
    "java": ("*.java",),
    "js": ("*.cjs", "*.js", "*.jsx", "*.mjs"),
    "json": ("*.json",),
    "markdown": ("*.markdown", "*.md"),
    "md": ("*.markdown", "*.md"),
    "py": ("*.py", "*.pyw"),
    "rust": ("*.rs",),
    "sh": ("*.bash", "*.sh"),
    "toml": ("*.toml",),
    "ts": ("*.ts", "*.tsx"),
    "txt": ("*.txt",),
    "yaml": ("*.yaml", "*.yml"),
    "zsh": ("*.zsh",),
}


def _rg_binary_name() -> str:
    return "rg.exe" if platform.system() == "Windows" else "rg"


def _find_existing_rg(bin_name: str) -> Path | None:
    if env_path := os.getenv("PYTHINKER_RG_PATH"):
        configured = Path(env_path).expanduser()
        if configured.is_file():
            return configured

    share_bin = get_share_dir() / "bin" / bin_name
    if share_bin.is_file():
        return share_bin

    assert pythinker_code.__file__ is not None
    local_dep = Path(pythinker_code.__file__).parent / "deps" / "bin" / bin_name
    if local_dep.is_file():
        return local_dep

    system_rg = shutil.which("rg")
    if system_rg:
        return Path(system_rg)

    for candidate in (
        Path("/usr/bin") / bin_name,
        Path("/usr/local/bin") / bin_name,
        Path.home() / ".cargo" / "bin" / bin_name,
        Path.home() / ".local" / "bin" / bin_name,
        Path.home() / ".pi" / "agent" / "bin" / bin_name,
    ):
        if candidate.is_file():
            return candidate

    return None


def _detect_target() -> str | None:
    sys_name = platform.system()
    mach = platform.machine().lower()

    if mach in ("x86_64", "amd64"):
        arch = "x86_64"
    elif mach in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        logger.error("Unsupported architecture for ripgrep: {mach}", mach=mach)
        return None

    if sys_name == "Darwin":
        os_name = "apple-darwin"
    elif sys_name == "Linux":
        os_name = "unknown-linux-musl" if arch == "x86_64" else "unknown-linux-gnu"
    elif sys_name == "Windows":
        os_name = "pc-windows-msvc"
    else:
        logger.error("Unsupported operating system for ripgrep: {sys_name}", sys_name=sys_name)
        return None

    return f"{arch}-{os_name}"


async def _download_and_install_rg(bin_name: str) -> Path:
    target = _detect_target()
    if not target:
        raise RuntimeError("Unsupported platform for ripgrep download")

    is_windows = "windows" in target
    archive_ext = "zip" if is_windows else "tar.gz"
    filename = f"ripgrep-{RG_VERSION}-{target}.{archive_ext}"
    urls = [
        f"{RG_BASE_URL}/{filename}",
        f"{RG_GITHUB_BASE_URL}/{RG_VERSION}/{filename}",
    ]

    share_bin_dir = get_share_dir() / "bin"
    share_bin_dir.mkdir(parents=True, exist_ok=True)
    destination = share_bin_dir / bin_name

    # Downloading the ripgrep binary can be slow on constrained networks.
    download_timeout = aiohttp.ClientTimeout(total=600, sock_read=60, sock_connect=15)
    async with new_client_session(timeout=download_timeout) as session:
        with tempfile.TemporaryDirectory(prefix="pythinker-rg-") as tmpdir:
            tar_path = Path(tmpdir) / filename

            download_errors: list[str] = []
            for url in urls:
                logger.info("Downloading ripgrep from {url}", url=url)
                try:
                    async with session.get(url) as resp:
                        resp.raise_for_status()
                        with open(tar_path, "wb") as fh:
                            async for chunk in resp.content.iter_chunked(1024 * 64):
                                if chunk:
                                    fh.write(chunk)
                    break
                except (aiohttp.ClientError, TimeoutError) as exc:
                    download_errors.append(f"{url}: {exc}")
            else:
                raise RuntimeError(
                    "Failed to download ripgrep binary from configured mirrors: "
                    + "; ".join(download_errors)
                )

            try:
                if is_windows:
                    with zipfile.ZipFile(tar_path, "r") as zf:
                        member_name = next(
                            (name for name in zf.namelist() if Path(name).name == bin_name),
                            None,
                        )
                        if not member_name:
                            raise RuntimeError("Ripgrep binary not found in archive")
                        with zf.open(member_name) as source, open(destination, "wb") as dest_fh:
                            shutil.copyfileobj(source, dest_fh)
                else:
                    with tarfile.open(tar_path, "r:gz") as tar:
                        member = next(
                            (m for m in tar.getmembers() if Path(m.name).name == bin_name),
                            None,
                        )
                        if not member:
                            raise RuntimeError("Ripgrep binary not found in archive")
                        extracted = tar.extractfile(member)
                        if not extracted:
                            raise RuntimeError("Failed to extract ripgrep binary")
                        with open(destination, "wb") as dest_fh:
                            shutil.copyfileobj(extracted, dest_fh)
            except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
                raise RuntimeError("Failed to extract ripgrep archive") from exc

    destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    logger.info("Installed ripgrep to {destination}", destination=destination)
    return destination


async def _ensure_rg_path() -> str:
    bin_name = _rg_binary_name()
    existing = _find_existing_rg(bin_name)
    if existing:
        return str(existing)

    async with _RG_DOWNLOAD_LOCK:
        existing = _find_existing_rg(bin_name)
        if existing:
            return str(existing)

        downloaded = await _download_and_install_rg(bin_name)
        return str(downloaded)


def _build_rg_args(rg_path: str, params: Params, *, single_threaded: bool = False) -> list[str]:
    """Build ripgrep command-line arguments from Params."""
    args: list[str] = [rg_path]

    # Fixed args
    if params.output_mode != "content":
        args.extend(["--max-columns", "500"])
    args.append("--hidden")
    if params.include_ignored:
        args.append("--no-ignore")
    for vcs_dir in (".git", ".svn", ".hg", ".bzr", ".jj", ".sl"):
        args.extend(["--glob", f"!{vcs_dir}"])

    if single_threaded:
        args.extend(["-j", "1"])

    # Search options
    if params.ignore_case:
        args.append("--ignore-case")
    if params.multiline:
        args.extend(["--multiline", "--multiline-dotall"])

    # Content display options (only for content mode)
    if params.output_mode == "content":
        if params.before_context is not None:
            args.extend(["--before-context", str(params.before_context)])
        if params.after_context is not None:
            args.extend(["--after-context", str(params.after_context)])
        if params.context is not None:
            args.extend(["--context", str(params.context)])
        if params.line_number:
            args.append("--line-number")

    # File filtering options
    if params.glob:
        args.extend(["--glob", params.glob])
    if params.type:
        args.extend(["--type", params.type])

    # Output mode
    if params.output_mode == "files_with_matches":
        args.append("--files-with-matches")
    elif params.output_mode == "count_matches":
        args.append("--count-matches")

    # Separate pattern from flags to avoid ambiguity (e.g. pattern starting with -)
    args.append("--")
    args.append(params.pattern)
    args.append(os.path.expanduser(params.path))

    return args


async def _read_stream(
    stream: asyncio.StreamReader,
    buffer: bytearray,
    limit: int,
    truncated_flag: list[bool] | None = None,
) -> bool:
    """Incrementally read from stream into buffer, up to limit bytes.

    After hitting the limit, continues draining the pipe (discarding data)
    so the child process doesn't block on a full pipe buffer.

    Args:
        truncated_flag: If provided, truncated_flag[0] is set to True at the
            moment truncation occurs (synchronously, before the next await).
            This ensures the flag is available even if the coroutine is
            cancelled by asyncio.wait_for timeout.

    Returns True if output was truncated (exceeded limit).
    """
    truncated = False
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        if len(buffer) < limit:
            needed = limit - len(buffer)
            buffer.extend(chunk[:needed])
            if len(chunk) > needed:
                truncated = True
                if truncated_flag is not None:
                    truncated_flag[0] = True
        else:
            truncated = True
            if truncated_flag is not None:
                truncated_flag[0] = True
    return truncated


async def _kill_process(process: asyncio.subprocess.Process) -> None:
    """Two-phase kill: SIGTERM → grace period → SIGKILL."""
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=RG_KILL_GRACE)
    except TimeoutError:
        process.kill()
        await process.wait()


def _is_eagain(stderr: str) -> bool:
    return "os error 11" in stderr or "Resource temporarily unavailable" in stderr


def _strip_path_prefix(output: str, search_base: str) -> str:
    """Strip search_base prefix from each line to produce relative paths."""
    prefix = search_base.rstrip("/\\") + os.sep
    return "\n".join(
        line[len(prefix) :] if line.startswith(prefix) else line for line in output.split("\n")
    )


def _relative_output_path(path: Path, search_base: Path) -> str:
    try:
        return str(path.relative_to(search_base))
    except ValueError:
        return os.path.relpath(path, search_base)


def _load_basic_ignore_patterns(search_base: Path) -> list[str]:
    patterns: list[str] = []
    for ignore_file in (search_base / ".gitignore", search_base / ".ignore"):
        try:
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            pattern = line.strip()
            if not pattern or pattern.startswith("#") or pattern.startswith("!"):
                continue
            patterns.append(pattern)
    return patterns


def _matches_basic_ignore_pattern(rel_path: str, pattern: str) -> bool:
    normalized = rel_path.replace(os.sep, "/")
    pattern = pattern.lstrip("/").replace(os.sep, "/")
    if pattern.endswith("/"):
        directory = pattern.rstrip("/")
        return normalized == directory or normalized.startswith(f"{directory}/")
    if "/" in pattern:
        return fnmatch.fnmatch(normalized, pattern)
    parts = normalized.split("/")
    return any(fnmatch.fnmatch(part, pattern) for part in parts)


def _is_ignored_by_basic_patterns(rel_path: str, patterns: list[str]) -> bool:
    return any(_matches_basic_ignore_pattern(rel_path, pattern) for pattern in patterns)


def _matches_python_type_filter(rel_path: str, file_type: str | None) -> bool:
    if not file_type:
        return True
    globs = _PYTHON_FALLBACK_TYPE_GLOBS.get(file_type.lower())
    if globs is None:
        return False
    return any(fnmatch.fnmatch(rel_path, glob_pattern) for glob_pattern in globs)


def _iter_python_search_files(params: Params) -> Iterator[Path]:
    # Lazy by design: ``rglob`` is itself an iterator, so yielding candidates one
    # at a time lets the consumer's per-file deadline check fire *during*
    # discovery. Materializing the full list here would let a large tree blow the
    # RG_TIMEOUT budget before the first timeout check could run.
    search_path = Path(os.path.expanduser(params.path))
    search_base = search_path if search_path.is_dir() else search_path.parent
    candidates = [search_path] if search_path.is_file() else search_path.rglob("*")
    excluded_vcs = {".git", ".svn", ".hg", ".bzr", ".jj", ".sl"}
    ignore_patterns = [] if params.include_ignored else _load_basic_ignore_patterns(search_base)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if any(part in excluded_vcs for part in candidate.parts):
            continue
        rel_path = _relative_output_path(candidate, search_base)
        if ignore_patterns and _is_ignored_by_basic_patterns(rel_path, ignore_patterns):
            continue
        if params.glob and not fnmatch.fnmatch(rel_path, params.glob):
            continue
        if not _matches_python_type_filter(rel_path, params.type):
            continue
        yield candidate


def _apply_python_pagination(lines: list[str], params: Params) -> tuple[list[str], str]:
    message = ""
    if params.offset > 0:
        lines = lines[params.offset :]
    effective_limit = params.head_limit
    if effective_limit and len(lines) > effective_limit:
        total = len(lines) + params.offset
        lines = lines[:effective_limit]
        message = (
            f"Results truncated to {effective_limit} lines (total: {total}). "
            f"Use offset={params.offset + effective_limit} to see more."
        )
    return lines, message


def _python_grep(params: Params, unavailable_reason: str) -> ToolReturnValue:
    builder = ToolResultBuilder()
    flags = re.IGNORECASE if params.ignore_case else 0
    if params.multiline:
        flags |= re.DOTALL | re.MULTILINE
    try:
        pattern = re.compile(params.pattern, flags)
    except re.error as exc:
        return ToolError(message=f"Failed to grep. Error: {exc}", brief="Failed to grep")

    search_path = Path(os.path.expanduser(params.path))
    search_base = search_path if search_path.is_dir() else search_path.parent
    matched_lines: list[str] = []
    filtered_paths: list[str] = []

    # Bound the total wall-clock spent here, mirroring the ripgrep path's
    # RG_TIMEOUT. This caps runaway many-file scans; it cannot interrupt a
    # single catastrophic-backtracking regex mid-file (stdlib `re` has no
    # timeout and the zero-dependency policy rules out a regex engine that does).
    deadline = time.monotonic() + RG_TIMEOUT
    timed_out = False

    for file_path in _iter_python_search_files(params):
        if time.monotonic() > deadline:
            timed_out = True
            break
        rel_path = _relative_output_path(file_path, search_base)
        if is_sensitive_file(rel_path):
            filtered_paths.append(rel_path)
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if params.output_mode == "files_with_matches":
            if pattern.search(text):
                matched_lines.append(rel_path)
            continue

        if params.output_mode == "count_matches":
            count = len(pattern.findall(text))
            if count:
                matched_lines.append(f"{rel_path}:{count}")
            continue

        lines = text.splitlines()
        matching_indexes = [idx for idx, line in enumerate(lines) if pattern.search(line)]
        if params.context is not None:
            before = after = params.context
        else:
            before = params.before_context or 0
            after = params.after_context or 0
        emitted: set[int] = set()
        for match_idx in matching_indexes:
            start = max(0, match_idx - before)
            end = min(len(lines), match_idx + after + 1)
            for idx in range(start, end):
                if idx in emitted:
                    continue
                emitted.add(idx)
                sep = ":" if idx == match_idx else "-"
                line_no = f"{idx + 1}{sep}" if params.line_number else ""
                matched_lines.append(f"{rel_path}{sep}{line_no}{lines[idx]}")

    if params.output_mode == "files_with_matches":
        matched_lines.sort(
            key=lambda p: os.path.getmtime(search_base / p) if (search_base / p).exists() else 0,
            reverse=True,
        )

    matched_lines, pagination_message = _apply_python_pagination(matched_lines, params)
    messages = [f"ripgrep unavailable ({unavailable_reason}); used Python fallback."]
    if timed_out:
        messages.append(f"Search exceeded {RG_TIMEOUT}s; returning partial results.")
    if filtered_paths:
        messages.append(sensitive_file_warning(filtered_paths))
    if pagination_message:
        messages.append(pagination_message)

    if not matched_lines:
        return builder.ok(message="No matches found. " + " ".join(messages))
    builder.write("\n".join(matched_lines))
    return builder.ok(message=" ".join(messages))


class SmartSearchParams(BaseModel):
    query: str = Field(description="Natural-language or symbol query to search for")
    path: str = Field(
        default=".",
        description="File or directory to search in. If specified, prefer an absolute path.",
    )
    type: str | None = Field(default=None, description="Optional ripgrep file type filter")
    glob: str | None = Field(default=None, description="Optional glob filter")
    max_results: int = Field(
        default=60,
        ge=1,
        le=200,
        description="Maximum combined result lines across planned search passes.",
    )

    @field_validator("query")
    @classmethod
    def query_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value


def _smart_search_patterns(query: str) -> list[tuple[str, str]]:
    tokens = [token for token in re.split(r"\W+", query) if len(token) >= 3]
    patterns: list[tuple[str, str]] = [("exact", re.escape(query))]
    if tokens:
        patterns.append(("all terms nearby", ".*".join(re.escape(token) for token in tokens[:5])))
        patterns.append(("any term", "|".join(re.escape(token) for token in tokens[:8])))
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for label, pattern in patterns:
        if pattern in seen:
            continue
        seen.add(pattern)
        unique.append((label, pattern))
    return unique


class SmartSearch(CallableTool2[SmartSearchParams]):
    name: str = "SmartSearch"
    description: str = (
        "Plan and run a small set of bounded local grep passes for a symbol or concept. "
        "Returns cited file/line spans and truncation guidance; use for exploration before "
        "falling back to broad shell searches."
    )
    params: type[SmartSearchParams] = SmartSearchParams

    @override
    async def __call__(self, params: SmartSearchParams) -> ToolReturnValue:
        seen_lines: set[str] = set()
        sections: list[str] = []
        per_pass_limit = max(10, min(params.max_results, 80))
        grep = Grep()
        for label, pattern in _smart_search_patterns(params.query):
            grep_params = Params.model_validate(
                {
                    "pattern": pattern,
                    "path": params.path,
                    "glob": params.glob,
                    "type": params.type,
                    "output_mode": "content",
                    "-C": 2,
                    "-n": True,
                    "-i": True,
                    "head_limit": per_pass_limit,
                }
            )
            result = await grep(grep_params)
            if result.is_error:
                sections.append(f"## {label}\nERROR: {result.message}")
                continue
            text = str(result.output or "").strip()
            if not text:
                continue
            kept: list[str] = []
            for line in text.splitlines():
                if line in seen_lines:
                    continue
                seen_lines.add(line)
                kept.append(line)
                if len(seen_lines) >= params.max_results:
                    break
            if kept:
                sections.append(f"## {label}\n" + "\n".join(kept))
            if len(seen_lines) >= params.max_results:
                break

        builder = ToolResultBuilder()
        if not sections:
            return builder.ok(message="No matches found across smart search passes.")
        builder.write("\n\n".join(sections))
        message = (
            f"SmartSearch ran {len(_smart_search_patterns(params.query))} planned grep passes; "
            f"returned {len(seen_lines)} unique result lines."
        )
        if len(seen_lines) >= params.max_results:
            message += " Results truncated; narrow query/path or increase max_results."
        return builder.ok(message=message)


class Grep(CallableTool2[Params]):
    name: str = "Grep"
    description: str = load_desc(Path(__file__).parent / "grep.md")
    params: type[Params] = Params

    @override
    async def __call__(self, params: Params, *, _retry: bool = False) -> ToolReturnValue:
        try:
            builder = ToolResultBuilder()
            message = ""

            # Build rg command
            try:
                rg_path = await _ensure_rg_path()
            except Exception as exc:
                logger.warning("ripgrep unavailable, using Python fallback: {error}", error=exc)
                return _python_grep(params, str(exc))
            logger.debug("Using ripgrep binary: {rg_bin}", rg_bin=rg_path)
            args = _build_rg_args(rg_path, params, single_threaded=_retry)

            # Execute search as async subprocess (non-blocking, cancellable)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Stream stdout/stderr incrementally with buffer limit
            stdout_buf = bytearray()
            stderr_buf = bytearray()
            timed_out = False
            stdout_truncated_flag: list[bool] = [False]

            try:
                assert process.stdout is not None
                assert process.stderr is not None
                await asyncio.wait_for(
                    asyncio.gather(
                        _read_stream(
                            process.stdout, stdout_buf, RG_MAX_BUFFER, stdout_truncated_flag
                        ),
                        _read_stream(process.stderr, stderr_buf, RG_MAX_BUFFER),
                    ),
                    timeout=RG_TIMEOUT,
                )
                await process.wait()
            except asyncio.CancelledError:
                await _kill_process(process)
                raise
            except TimeoutError:
                await _kill_process(process)
                timed_out = True

            output = stdout_buf.decode("utf-8", errors="replace")
            stderr_str = stderr_buf.decode("utf-8", errors="replace")

            # truncated_flag is set synchronously inside _read_stream at
            # the moment of truncation, so it's available even after timeout.
            buffer_truncated = stdout_truncated_flag[0]

            # Drop last incomplete line if buffer was truncated
            if buffer_truncated:
                last_nl = output.rfind("\n")
                output = output[:last_nl] if last_nl >= 0 else ""
                message = "Output exceeded buffer limit. Some results omitted."

            # Timeout: return partial results if available, otherwise error
            if timed_out:
                if not output.strip():
                    return ToolError(
                        message=(
                            f"Grep timed out after {RG_TIMEOUT}s. "
                            "Try a more specific path or pattern."
                        ),
                        brief="Grep timed out",
                    )
                timeout_msg = f"Grep timed out after {RG_TIMEOUT}s. Partial results returned."
                message = f"{message} {timeout_msg}" if message else timeout_msg

            # rg exit codes: 0=matches found, 1=no matches, 2+=error
            if not timed_out and process.returncode not in (0, 1):
                # EAGAIN: retry once with single-threaded mode
                if not _retry and _is_eagain(stderr_str):
                    logger.warning("rg EAGAIN error, retrying with -j 1")
                    return await self.__call__(params, _retry=True)
                return ToolError(
                    message=f"Failed to grep. Error: {stderr_str}",
                    brief="Failed to grep",
                )

            # --- Post-processing pipeline ---

            # Step 1: mtime sorting (files_with_matches only, skip on timeout)
            if not timed_out and params.output_mode == "files_with_matches":
                lines = [x for x in output.split("\n") if x.strip()]
                lines.sort(
                    key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
                    reverse=True,
                )
                output = "\n".join(lines)

            # Step 2: shorten paths to relative (prefix stripping)
            search_base = os.path.abspath(os.path.expanduser(params.path))
            if os.path.isfile(search_base):
                search_base = os.path.dirname(search_base)
            output = _strip_path_prefix(output, search_base)

            # Step 3: filter sensitive files from output
            # Regex for ripgrep content lines: path:linenum:text (match) or
            # path-linenum-text (context). The separator is `:` or `-` followed
            # by digits then the same separator again.
            _RG_LINE_RE = re.compile(r"^(.*?)([:\-])(\d+)\2")

            out_lines = output.split("\n")
            filtered_paths: list[str] = []
            kept_lines: list[str] = []
            sensitive_path_set: set[str] = set()
            for line in out_lines:
                if params.output_mode == "content":
                    # Match lines: "file.py:10:matched text"
                    # Context lines: "file.py-10-context text"
                    # Separator: "--"
                    if line == "--":
                        kept_lines.append(line)
                        continue
                    m = _RG_LINE_RE.match(line)
                    file_path = m.group(1) if m else line
                elif params.output_mode == "count_matches":
                    # Count lines: "file.py:42"
                    idx = line.rfind(":")
                    file_path = line[:idx] if idx > 0 else line
                else:
                    # files_with_matches: pure path per line
                    file_path = line

                if file_path and is_sensitive_file(file_path):
                    if file_path not in sensitive_path_set:
                        sensitive_path_set.add(file_path)
                        filtered_paths.append(file_path)
                else:
                    kept_lines.append(line)

            if filtered_paths:
                # Remove trailing "--" separators left after filtering
                while kept_lines and kept_lines[-1] == "--":
                    kept_lines.pop()
                output = "\n".join(kept_lines)
                warning = sensitive_file_warning(filtered_paths)
                message = f"{message} {warning}" if message else warning

            # Step 4: count_matches summary (before pagination, on full results)
            lines = output.split("\n")
            if lines and lines[-1] == "":
                lines = lines[:-1]

            if params.output_mode == "count_matches":
                total_matches = 0
                total_files = 0
                for line in lines:
                    idx = line.rfind(":")
                    if idx > 0:
                        try:
                            total_matches += int(line[idx + 1 :])
                            total_files += 1
                        except ValueError:
                            pass
                count_summary = (
                    f"Found {total_matches} total occurrences across {total_files} files."
                )
                message = f"{message} {count_summary}" if message else count_summary

            # Step 5: offset + head_limit pagination
            if params.offset > 0:
                lines = lines[params.offset :]

            effective_limit = params.head_limit
            if effective_limit and len(lines) > effective_limit:
                total = len(lines) + params.offset
                lines = lines[:effective_limit]
                output = "\n".join(lines)
                truncation_msg = (
                    f"Results truncated to {effective_limit} lines (total: {total}). "
                    f"Use offset={params.offset + effective_limit} to see more."
                )
                message = f"{message} {truncation_msg}" if message else truncation_msg
            else:
                output = "\n".join(lines)

            if not output and not buffer_truncated:
                no_match_msg = "No matches found"
                if message:
                    no_match_msg = f"{no_match_msg}. {message}"
                return builder.ok(message=no_match_msg)

            builder.write(output)
            return builder.ok(message=message)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            from pythinker_code.telemetry.errors import report_handled_error

            report_handled_error(e, site="tool.grep", tool="Grep")
            logger.warning(
                "Grep failed: pattern={pattern}, path={path}: {error}",
                pattern=params.pattern,
                path=params.path,
                error=e,
            )
            return ToolError(
                message=f"Failed to grep. Error: {str(e)}",
                brief="Failed to grep",
            )
