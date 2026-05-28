from __future__ import annotations

import tomllib
from pathlib import Path

_BASELINE = {
    "agent-client-protocol",
    "aiofiles",
    "aiohttp",
    "typer",
    "pythinker-core",
    "loguru",
    "prompt-toolkit",
    "pillow",
    "pyyaml",
    "rich",
    "certifi",
    "click",
    "pyperclip",
    "streamingjson",
    "trafilatura",
    "lxml",
    "tenacity",
    "fastmcp",
    "pydantic",
    "httpx",
    "pythinker-host",
    "pythinker-review",
    "batrachian-toad",
    "tomlkit",
    "jinja2",
    "pyobjc-framework-cocoa",
    "fastapi",
    "uvicorn",
    "scalar-fastapi",
    "websockets",
    "keyring",
    "setproctitle",
    "sentry-sdk",
    "opentelemetry-api",
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp-proto-http",
}


def _dep_names() -> set[str]:
    import re

    root = Path(__file__).resolve().parents[2]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    names: set[str] = set()
    for spec in data["project"]["dependencies"]:
        names.add(re.split(r"[<>=!\[; ]", spec.strip())[0])
    return names


def test_memory_feature_adds_no_runtime_dependency():
    assert _dep_names() == _BASELINE, (
        "New runtime dependency detected. The memory/context feature must be stdlib-only."
    )


def test_memory_modules_import_with_stdlib_only():
    import sys

    before = set(sys.modules)
    import pythinker_code.memory.retriever  # noqa: F401
    import pythinker_code.memory.sanitize  # noqa: F401

    new = set(sys.modules) - before
    forbidden = {"rank_bm25", "numpy", "sentence_transformers", "chromadb", "onnxruntime", "faiss"}
    assert not (new & forbidden), f"forbidden import pulled in: {new & forbidden}"
