from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_HELP = """Usage: pythinker [OPTIONS] COMMAND [ARGS]...

  Pythinker, your next CLI agent.

Options:
  -h, --help                       Show this message and exit.
  -V, --version                    Show version and exit.
  --verbose                        Print verbose information.
  --debug                          Log debug information.
  -w, --work-dir DIRECTORY         Working directory for the agent.
  --add-dir DIRECTORY              Add an additional workspace directory.
  -S, -r, --session, --resume TEXT Resume a session.
  -C, --continue                   Continue the previous session.
  --config TEXT                    Config TOML/JSON string to load.
  --config-file FILE               Config TOML/JSON file to load.
  -m, --model TEXT                 LLM model to use.
  --thinking / --no-thinking       Enable or disable thinking mode.
  -y, --yolo, --yes, --auto-approve
                                   Dangerously skip permission approvals.
  --plan                           Start in plan mode.
  --auto                           Run in auto mode (no user present).
  -p, -c, --prompt, --command TEXT User prompt to the agent.
  --print                          Run in print mode.
  --acp                            Deprecated; use `pythinker acp`.
  --wire                           Run as Wire server.
  --quiet                          Print only the final assistant message.
  --agent [default|okabe]          Builtin agent specification to use.
  --agent-file FILE                Custom agent specification file.
  --mcp-config-file FILE           MCP config file to load; repeatable.
  --mcp-config TEXT                MCP config JSON to load; repeatable.
  --skills-dir DIRECTORY           Custom skills directory; repeatable.
  --no-telemetry                   Disable anonymous telemetry & error reporting.

Commands:
  acp      Run Pythinker CLI ACP server.
  term     Run Toad TUI backed by Pythinker CLI ACP server.
  login    Login with a model provider.
  logout   Logout from a model provider.
  info     Show version and protocol information.
  export   Export session data.
  mcp      Manage MCP server configurations.
  plugin   Manage plugins.
  review          Diff-focused code review (delegates to pythinker-review).
  secscan         Diff-focused security review (delegates to pythinker-review).
  security-scan   Repo-wide Pythinker Security Scan pipeline (Python-native).
  debug           Failure/log root-cause analysis (delegates to pythinker-review).
  update   Check for and install Pythinker CLI updates.
  vis      Run Pythinker Agent Tracing Visualizer.
  web      Run Pythinker CLI web interface.

Documentation:        https://mohamed-elkholy95.github.io/Pythinker-Code/
LLM friendly version: https://mohamed-elkholy95.github.io/Pythinker-Code/llms.txt
"""


def _prog_name() -> str:
    return Path(sys.argv[0]).name or "pythinker"


def main(argv: Sequence[str] | None = None) -> int | str | None:
    args = list(sys.argv[1:] if argv is None else argv)

    if len(args) == 1 and args[0] in {"--version", "-V"}:
        from pythinker_code.constant import get_version

        print(f"pythinker, version {get_version()}")
        return 0

    if len(args) == 1 and args[0] in {"--help", "-h"}:
        print(ROOT_HELP, end="")
        return 0

    from pythinker_code.telemetry.crash import install_crash_handlers, set_phase
    from pythinker_code.utils.proxy import normalize_proxy_env

    # Install excepthook before anything else so startup-phase crashes are captured.
    install_crash_handlers()
    normalize_proxy_env()

    from pythinker_code.cli import cli

    try:
        return cli(args=args, prog_name=_prog_name())
    except SystemExit as exc:
        return exc.code
    finally:
        set_phase("shutdown")


if __name__ == "__main__":
    raise SystemExit(main())
