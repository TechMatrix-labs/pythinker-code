"""PyInstaller entry shim for pythinker.exe.

Delegates to ``pythinker_code.__main__.main`` so the frozen exe behaves
identically to ``python -m pythinker_code`` — including the crash-handler
install, proxy-env normalization, and the ``--version`` / ``--help``
short-circuits that live in ``__main__``.
"""
from __future__ import annotations

import sys


def _entrypoint() -> int:
    from pythinker_code.__main__ import main

    result = main()
    if isinstance(result, int):
        return result
    if result is None:
        return 0
    # Typer/Click sometimes returns a string (legacy); coerce to non-zero.
    return 1


if __name__ == "__main__":
    sys.exit(_entrypoint())
