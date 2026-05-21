"""Small Pythinker Security Scan technology detector for security prompt scoping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DetectedTech:
    tags: tuple[str, ...]
    languages: tuple[str, ...]
    sentinels: tuple[str, ...]


def detect_tech(repo: Path) -> DetectedTech:
    tags: set[str] = set()
    languages: set[str] = set()
    sentinels: list[str] = []
    if pkg := _read_json(repo / "package.json"):
        sentinels.append("package.json")
        tags.add("node")
        languages.update({"javascript", "typescript"})
        deps = _deps(pkg)
        for dep, tag in {
            "next": "nextjs",
            "react": "react",
            "react-dom": "react",
            "express": "express",
            "fastify": "fastify",
            "@sveltejs/kit": "sveltekit",
            "@remix-run/node": "remix",
            "nuxt": "nuxt",
            "@trpc/server": "trpc",
            "@modelcontextprotocol/sdk": "mcp",
            "@prisma/client": "prisma",
            "prisma": "prisma",
            "drizzle-orm": "drizzle",
        }.items():
            if dep in deps:
                tags.add(tag)
    py_text = "\n".join(
        text
        for rel in ("pyproject.toml", "requirements.txt", "setup.py")
        if (text := _read_text(repo / rel, sentinels, rel))
    ).lower()
    if py_text or (repo / "manage.py").exists():
        tags.add("python")
        languages.add("python")
        if (repo / "manage.py").exists():
            sentinels.append("manage.py")
            tags.add("django")
        for pattern, tag in (
            (r"\bdjango\b", "django"),
            (r"\bflask\b", "flask"),
            (r"\bfastapi\b", "fastapi"),
            (r"\bstarlette\b", "starlette"),
            (r"\baiohttp\b", "aiohttp"),
            (r"\bcelery\b", "celery"),
            (r"\bairflow\b|apache-airflow", "airflow"),
        ):
            if re.search(pattern, py_text):
                tags.add(tag)
    if (repo / "go.mod").exists():
        sentinels.append("go.mod")
        tags.add("go")
        languages.add("go")
    if (repo / "Cargo.toml").exists():
        sentinels.append("Cargo.toml")
        tags.add("rust")
        languages.add("rust")
    if (repo / "Gemfile").exists() or (repo / "Gemfile.lock").exists():
        sentinels.append("Gemfile")
        tags.add("ruby")
        languages.add("ruby")
    if (repo / "composer.json").exists():
        sentinels.append("composer.json")
        tags.add("php")
        languages.add("php")
    if (repo / "pom.xml").exists() or (repo / "build.gradle").exists():
        tags.add("jvm")
        languages.add("java")
    if any(repo.glob("*.csproj")) or (repo / "global.json").exists():
        tags.add("dotnet")
        languages.add("csharp")
    return DetectedTech(
        tags=tuple(sorted(tags)),
        languages=tuple(sorted(languages)),
        sentinels=tuple(dict.fromkeys(sentinels)),
    )


def language_for_path(path: str) -> str | None:
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".swift": "swift",
        ".ex": "elixir",
        ".exs": "elixir",
    }.get(Path(path).suffix.lower())


def _read_text(path: Path, sentinels: list[str], rel: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return None
    sentinels.append(rel)
    return text


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _deps(pkg: dict[str, object]) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = pkg.get(key)
        if isinstance(value, dict):
            names.update(str(name) for name in value)
    return names
