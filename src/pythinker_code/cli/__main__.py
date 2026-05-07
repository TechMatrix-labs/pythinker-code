from __future__ import annotations

import sys

from pythinker_code.cli import cli

if __name__ == "__main__":
    from pythinker_code.telemetry.crash import install_crash_handlers, set_phase
    from pythinker_code.utils.proxy import normalize_proxy_env

    # Same entry treatment as pythinker_code.__main__: install excepthook before
    # anything else so startup-phase crashes in subcommand subprocesses
    # (background-task-worker, __web-worker, acp via toad) are captured.
    install_crash_handlers()
    normalize_proxy_env()
    try:
        sys.exit(cli())
    finally:
        set_phase("shutdown")
