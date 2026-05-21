"""Heuristic project detection and feature mapping.

This is a compact Python port of Reviewflow's mapper concept: produce durable,
semantic-ish feature records from repository evidence without invoking a model.
It intentionally favors conservative grouping over exhaustive language-specific
AST parsing so the workflow remains pure Python and dependency-free.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from pythinker_review.reviewflow.models import (
    DetectedProject,
    FeatureEntrypoint,
    FeatureFileRef,
    FeatureRecord,
    FeatureTestRef,
    GitInfo,
    ProjectCommands,
    ProjectRecord,
    ReviewflowConfig,
)
from pythinker_review.reviewflow.utils import (
    discover_git,
    now_iso,
    path_matches,
    read_text_bounded,
    stable_id,
)

SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".cs",
    ".fs",
    ".vb",
    ".rb",
    ".ex",
    ".exs",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".swift",
    ".php",
}
CONFIG_NAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "pnpm-workspace.yaml",
    "yarn.lock",
    "package-lock.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "mix.exs",
    "Makefile",
    "Dockerfile",
}
TEST_MARKERS = ("test", "tests", "spec", "specs", "__tests__")


def detect_project(root: Path, config: ReviewflowConfig | None = None) -> ProjectRecord:
    config = config or ReviewflowConfig()
    git_root, remote, default_branch, current_branch, head_sha, _dirty = discover_git(root)
    languages: set[str] = set()
    frameworks: set[str] = set()
    package_managers: set[str] = set()
    commands = ProjectCommands()

    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        languages.add("python")
        package_managers.add("uv" if (root / "uv.lock").exists() else "pip")
        commands.test = commands.test or "pytest"
        commands.format = commands.format or "ruff format"
        commands.lint = commands.lint or "ruff check"
    package_json = root / "package.json"
    if package_json.exists():
        languages.add("typescript/javascript")
        package_managers.add(_node_package_manager(root))
        scripts = _package_scripts(package_json)
        commands.test = scripts.get("test")
        commands.lint = scripts.get("lint")
        commands.typecheck = scripts.get("typecheck")
        commands.format = scripts.get("format")
        deps = " ".join(_package_deps(package_json))
        for marker, framework in {
            "next": "nextjs",
            "react": "react",
            "@angular/core": "angular",
            "vue": "vue",
            "express": "express",
            "fastify": "fastify",
        }.items():
            if marker in deps:
                frameworks.add(framework)
    if (root / "go.mod").exists():
        languages.add("go")
        package_managers.add("go")
        commands.test = commands.test or "go test ./..."
    if (root / "Cargo.toml").exists():
        languages.add("rust")
        package_managers.add("cargo")
        commands.test = commands.test or "cargo test"
        commands.typecheck = commands.typecheck or "cargo check"
    if (root / "pom.xml").exists():
        languages.add("jvm")
        package_managers.add("maven")
        commands.test = commands.test or "mvn test"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        languages.add("jvm")
        package_managers.add("gradle")
        commands.test = commands.test or "./gradlew test"
    if (root / "composer.json").exists():
        languages.add("php")
        package_managers.add("composer")
    if (root / "mix.exs").exists():
        languages.add("elixir")
        package_managers.add("mix")
        commands.test = commands.test or "mix test"

    for path in iter_repo_files(root, config):
        if path.suffix == ".py":
            languages.add("python")
            text = read_text_bounded(path, limit_chars=4000)
            if "FastAPI(" in text:
                frameworks.add("fastapi")
            if "Flask(" in text:
                frameworks.add("flask")
            if "django" in text.lower():
                frameworks.add("django")
        elif path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            languages.add("typescript/javascript")
        elif path.suffix == ".go":
            languages.add("go")
        elif path.suffix == ".rs":
            languages.add("rust")
        elif path.suffix in {".rb"}:
            languages.add("ruby")
        elif path.suffix in {".swift"}:
            languages.add("swift")
        elif path.suffix in {".cs", ".fs", ".vb"}:
            languages.add("dotnet")
        elif path.suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}:
            languages.add("c/c++")
        elif path.suffix in {".ex", ".exs"}:
            languages.add("elixir")
        elif path.suffix == ".php":
            languages.add("php")

    now = now_iso()
    return ProjectRecord(
        project_id=stable_id("prj", [str(root.resolve())]),
        name=root.name,
        root_path=str(root.resolve()),
        git=GitInfo(
            remote_url=remote,
            default_branch=default_branch,
            current_branch=current_branch,
            head_sha=head_sha,
        ),
        detected=DetectedProject(
            languages=sorted(languages),
            frameworks=sorted(frameworks),
            package_managers=sorted(package_managers),
            commands=commands,
        ),
        created_at=now,
        updated_at=now,
    )


def map_features(
    root: Path,
    project: ProjectRecord,
    config: ReviewflowConfig,
    existing: list[FeatureRecord],
) -> tuple[list[FeatureRecord], dict[str, int]]:
    now = now_iso()
    previous = {feature.feature_id: feature for feature in existing}
    seeds: dict[str, dict[str, object]] = {}
    config_files: list[str] = []
    groups: dict[str, list[str]] = defaultdict(list)
    tests_by_group: dict[str, list[str]] = defaultdict(list)

    for file_path in iter_repo_files(root, config):
        rel = file_path.relative_to(root).as_posix()
        if file_path.name in CONFIG_NAMES or file_path.suffix in {
            ".toml",
            ".yaml",
            ".yml",
            ".json",
        }:
            config_files.append(rel)
        if file_path.suffix not in SOURCE_SUFFIXES:
            continue
        key = _group_key(rel)
        if _is_test_path(rel):
            tests_by_group[key].append(rel)
        else:
            groups[key].append(rel)

    if config_files:
        feature_id = stable_id("feat", ["config", *sorted(config_files)])
        seeds[feature_id] = {
            "title": "Project configuration",
            "summary": "Build, dependency, and tool configuration files.",
            "kind": "config",
            "owned": sorted(config_files)[: config.review.max_owned_files],
            "context": [],
            "tests": [],
            "tags": ["config"],
        }

    for key, files in groups.items():
        sorted_files = sorted(files)
        tests = sorted(tests_by_group.get(key, []))
        title = _title_for_group(key, sorted_files)
        kind = _kind_for_group(key, sorted_files, tests)
        feature_id = stable_id("feat", [key, *sorted_files[:20]])
        seeds[feature_id] = {
            "title": title,
            "summary": f"Source slice for {title}.",
            "kind": kind,
            "owned": sorted_files[: config.review.max_owned_files],
            "context": sorted_files[
                config.review.max_owned_files : config.review.max_owned_files + 6
            ],
            "tests": tests[:8],
            "tags": sorted(_tags_for_files(sorted_files)),
        }

    features: list[FeatureRecord] = []
    created = 0
    changed = 0
    for feature_id, seed in sorted(seeds.items()):
        prior = previous.get(feature_id)
        created_at = prior.created_at if prior else now
        status = prior.status if prior and prior.status not in {"skipped", "claimed"} else "pending"
        finding_ids = prior.finding_ids if prior else []
        patch_ids = prior.patch_attempt_ids if prior else []
        analysis = prior.analysis_history if prior else []
        feature = FeatureRecord(
            feature_id=feature_id,
            title=str(seed["title"]),
            summary=str(seed["summary"]),
            kind=seed["kind"],  # type: ignore[arg-type]
            source="heuristic",
            confidence="medium",
            entrypoints=[
                FeatureEntrypoint(path=path)
                for path in list(seed["owned"])[:3]  # type: ignore[arg-type]
            ],
            owned_files=[
                FeatureFileRef(path=path, reason="owned by heuristic feature slice")
                for path in seed["owned"]  # type: ignore[union-attr]
            ],
            context_files=[
                FeatureFileRef(path=path, reason="nearby source context")
                for path in seed["context"]  # type: ignore[union-attr]
            ],
            tests=[
                FeatureTestRef(path=path, command=project.detected.commands.test)
                for path in seed["tests"]  # type: ignore[union-attr]
            ],
            tags=list(seed["tags"]),  # type: ignore[arg-type]
            trust_boundaries=_trust_boundaries(root, seed["owned"]),  # type: ignore[arg-type]
            status=status,
            finding_ids=finding_ids,
            patch_attempt_ids=patch_ids,
            analysis_history=analysis,
            created_at=created_at,
            updated_at=now,
        )
        features.append(feature)
        if prior is None:
            created += 1
        elif _feature_fingerprint(prior) != _feature_fingerprint(feature):
            changed += 1

    stale = max(len(existing) - len(features), 0)
    return features, {"created": created, "changed": changed, "stale": stale}


def iter_repo_files(root: Path, config: ReviewflowConfig) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if path_matches(rel, config.exclude):
            continue
        if config.include and not path_matches(rel, config.include):
            continue
        if _looks_generated(rel):
            continue
        files.append(path)
    return files


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "package-lock.json").exists():
        return "npm"
    return "npm"


def _package_scripts(package_json: Path) -> dict[str, str]:
    try:
        parsed = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = parsed.get("scripts", {})
    if not isinstance(scripts, dict):
        return {}
    return {key: str(value) for key, value in scripts.items() if isinstance(value, str)}


def _package_deps(package_json: Path) -> list[str]:
    try:
        parsed = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = parsed.get(key, {})
        if isinstance(value, dict):
            out.extend(str(dep) for dep in value)
    return out


def _group_key(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) == 1:
        return "root"
    if parts[0] in {"apps", "packages", "crates", "cmd", "services", "extensions", "plugins"}:
        return "/".join(parts[:2]) if len(parts) > 1 else parts[0]
    if parts[0] in {"src", "lib", "app", "pages", "routes", "components", "tests", "test"}:
        return parts[0]
    return parts[0]


def _title_for_group(key: str, files: list[str]) -> str:
    if key == "root":
        return "Root source files"
    if key in {"tests", "test"}:
        return "Test suite"
    if any("/routes" in file or file.startswith(("app/", "pages/", "routes/")) for file in files):
        return f"Routes: {key}"
    return key.replace("/", " / ").replace("_", " ").title()


def _kind_for_group(key: str, files: list[str], tests: list[str]) -> str:
    if key in {"tests", "test"} or tests and all(_is_test_path(path) for path in files):
        return "test-suite"
    if any(file.startswith(("app/", "pages/", "routes/")) or "/routes/" in file for file in files):
        return "route"
    if any(file.endswith(("cli.py", "cli.ts", "cli.js")) or "/cli/" in file for file in files):
        return "cli-command"
    if any("job" in file.lower() or "worker" in file.lower() for file in files):
        return "job"
    return "library"


def _tags_for_files(files: list[str]) -> set[str]:
    tags: set[str] = set()
    for file in files:
        suffix = Path(file).suffix
        if suffix == ".py":
            tags.add("python")
        elif suffix in {".ts", ".tsx"}:
            tags.add("typescript")
        elif suffix in {".js", ".jsx"}:
            tags.add("javascript")
        elif suffix == ".go":
            tags.add("go")
        elif suffix == ".rs":
            tags.add("rust")
        elif suffix in {".java", ".kt", ".kts"}:
            tags.add("jvm")
        elif suffix in {".rb"}:
            tags.add("ruby")
        elif suffix in {".php"}:
            tags.add("php")
    return tags


def _trust_boundaries(root: Path, files: object) -> list[str]:
    boundaries: set[str] = set()
    for rel in files if isinstance(files, list) else []:
        if not isinstance(rel, str):
            continue
        text = read_text_bounded(root / rel, limit_chars=6000).lower()
        if any(token in text for token in ("request", "input(", "argv", "params", "body")):
            boundaries.add("user-input")
        if any(token in text for token in ("http", "fetch(", "requests.", "axios", "socket")):
            boundaries.add("network")
        if any(token in text for token in ("open(", "readfile", "writefile", "path", "fs.")):
            boundaries.add("filesystem")
        if any(token in text for token in ("token", "secret", "password", "api_key")):
            boundaries.add("secrets")
        if any(token in text for token in ("subprocess", "exec(", "spawn(", "system(")):
            boundaries.add("process-exec")
        if any(token in text for token in ("sql", "query", "database", "db.")):
            boundaries.add("database")
        if any(token in text for token in ("auth", "permission", "role")):
            boundaries.add("auth")
    return sorted(boundaries)


def _feature_fingerprint(feature: FeatureRecord) -> tuple[object, ...]:
    return (
        feature.title,
        feature.summary,
        feature.kind,
        tuple((item.path, item.reason) for item in feature.owned_files),
        tuple((item.path, item.reason) for item in feature.context_files),
        tuple((item.path, item.command) for item in feature.tests),
        tuple(feature.tags),
    )


def _is_test_path(rel: str) -> bool:
    lowered = rel.lower()
    parts = lowered.split("/")
    stem = Path(lowered).stem
    return (
        any(marker in parts for marker in TEST_MARKERS)
        or stem.startswith("test_")
        or stem.endswith(("_test", ".test", ".spec"))
    )


def _looks_generated(rel: str) -> bool:
    lowered = rel.lower()
    return any(
        marker in lowered
        for marker in (
            "/.venv/",
            "/__pycache__/",
            "/node_modules/",
            "/dist/",
            "/build/",
            "/target/",
            ".min.js",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "uv.lock",
        )
    )


__all__ = ["detect_project", "iter_repo_files", "map_features"]
