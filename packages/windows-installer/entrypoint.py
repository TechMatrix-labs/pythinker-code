"""PyInstaller entry shim for pythinker.exe.

We re-export the existing Typer app so PyInstaller can freeze a single
exe that behaves identically to `python -m pythinker_code`.
"""
from __future__ import annotations

import sys


def main() -> int:
    from pythinker_code.cli import app  # Typer instance

    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
