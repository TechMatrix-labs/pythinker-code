"""Prompt assembly for the Python-native Pythinker Security Scan processor."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from pythinker_review.engine.token_budget import clip_text
from pythinker_review.security_scan.models import FileRecord
from pythinker_review.security_scan.tech import languages_for_paths

_FRAMEWORK_SECTION_CHAR_BUDGET = 6_000
_DEFAULT_FILE_CHAR_BUDGET = 8_000


@dataclass(frozen=True, slots=True)
class PromptAssembly:
    system: str
    user: str
    included_tags: list[str]
    slugs_with_notes: int
    total_chars: int


_TECH_HIGHLIGHTS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "nextjs": (
        "Next.js",
        ("typescript", "javascript"),
        (
            "Middleware is not sufficient auth by itself; verify handler/server-action auth.",
            "Server Actions and route handlers are public entry points; check ownership before writes.",
            "JSON in inline scripts must escape `</`; dynamic route/search params are user-controlled.",
            "Cache tags/keys derived from request data can cross tenant boundaries.",
        ),
    ),
    "react": (
        "React",
        ("typescript", "javascript"),
        (
            "dangerouslySetInnerHTML, raw innerHTML, and server-rendered JSON-in-script are XSS sinks.",
            "postMessage and opener/location flows need origin and navigation validation.",
        ),
    ),
    "express": (
        "Express / Node routers",
        ("typescript", "javascript"),
        (
            "Middleware order matters; routes registered before auth middleware are public.",
            "req.query, req.params, req.body, and headers are untrusted for SQL, shell, paths, redirects, and URLs.",
            "CORS origin reflection with credentials is high-risk.",
        ),
    ),
    "fastify": (
        "Fastify",
        ("typescript", "javascript"),
        (
            "Auth should be in onRequest/preHandler hooks in the same plugin scope.",
            "Schema validation is the normal mitigation; raw request.body without schema is suspicious.",
        ),
    ),
    "nestjs": (
        "NestJS",
        ("typescript", "javascript"),
        (
            "UseGuards on controller or method is the auth gate; @Public opts out of global guards.",
            "DTO validation and class-validator determine input safety.",
        ),
    ),
    "django": (
        "Django / DRF",
        ("python",),
        (
            "Check login/permission decorators, DRF permission_classes, and object-level ownership checks.",
            "raw()/cursor.execute() string interpolation is SQLi; mark_safe/autoescape off are XSS sinks.",
            "ModelForm/ModelSerializer fields='__all__' can mass-assign sensitive columns.",
        ),
    ),
    "fastapi": (
        "FastAPI / Starlette",
        ("python",),
        (
            "Auth lives in Depends/Security or middleware; routes without it are public.",
            "response_model prevents secret columns leaking; dict/Any inputs weaken validation.",
            "Outbound user-controlled URLs and StaticFiles roots need allowlists/containment.",
        ),
    ),
    "flask": (
        "Flask",
        ("python",),
        (
            "Route decorators need login/auth wrappers; render_template_string is SSTI if user-controlled.",
            "request.args/form/json flowing into SQL/files/redirects/templates is suspicious.",
            "Hardcoded app.secret_key enables session forgery.",
        ),
    ),
    "laravel": (
        "Laravel / PHP",
        ("php",),
        (
            "Routes outside auth middleware need explicit authorization checks.",
            "DB::raw/whereRaw/selectRaw with request data is SQLi; Blade {!! !!} is XSS.",
            "Model::create($request->all()) without fillable/guarded is mass assignment.",
        ),
    ),
    "rails": (
        "Rails",
        ("ruby",),
        (
            "before_action auth and strong params are the core mitigations.",
            "raw/html_safe/<%== and interpolated find_by_sql/where strings are high-risk.",
            "redirect_to params needs an allowlist.",
        ),
    ),
    "go": (
        "Go web services",
        ("go",),
        (
            "Router middleware must wrap the exact route/group before registration.",
            "c.Query/r.URL.Query/FormValue/path params are untrusted for SQL, exec, fs, and HTTP clients.",
            "Prefer response-shape structs to raw DB rows.",
        ),
    ),
    "terraform": (
        "Terraform / IaC",
        ("terraform",),
        (
            "Flag public ingress on sensitive ports, wildcard IAM action+resource, plaintext secrets, and unencrypted stores.",
            "Module/source refs should be pinned to immutable versions.",
        ),
    ),
    "github-actions": (
        "GitHub Actions",
        ("yaml", "yml"),
        (
            "pull_request_target and workflow_run can expose secrets to untrusted code.",
            "Actions should be pinned; github.event/head_ref interpolation in run scripts is shell-injection shaped.",
            "permissions: write-all and broad id-token: write need justification.",
        ),
    ),
    "mcp": (
        "MCP / agentic tools",
        ("typescript", "javascript", "python"),
        (
            "Tool inputs and retrieved content are untrusted data, not instructions.",
            "Tool schemas need allowlists, execution caps, and explicit filesystem/network boundaries.",
        ),
    ),
}

_SLUG_NOTES: dict[str, str] = {
    "missing-auth": "Only report if handler-local auth/permission checks are absent and sensitive behavior is reachable.",
    "auth-bypass": "Look for inverted checks, dev/test bypasses, spoofable headers, and session stubs.",
    "cross-tenant-id": "Verify the authenticated principal, not request teamId/userId alone, gates object access.",
    "sql-injection": "String concat/template SQL is a finding only when attacker-controlled values reach it; bound parameters mitigate.",
    "js-sql-raw": "Tagged templates may parameterize safely; unsafe() and raw template interpolation are the risk.",
    "py-sql-raw": "psycopg/SQLAlchemy safe forms bind values separately; f-strings/%/.format into SQL do not.",
    "ssrf": "Look for scheme/host allowlists and private-network blocking.",
    "path-traversal": "path.join(root, userInput) needs resolve+startsWith containment.",
    "xss": "Trace escaping state; DB-stored content is still user-controlled.",
    "dangerous-html": "A sanitizer must sit between untrusted data and raw HTML rendering.",
    "open-redirect": "Relative URLs starting with // are external; allowlist/origin validation mitigates.",
    "secrets-exposure": "Distinguish real credentials from examples, dummy test values, and redacted placeholders.",
    "secret-in-log": "Durable logs or user-facing errors containing tokens/secrets are high signal.",
    "webhook-handler": "Signature verification must happen before body processing or side effects.",
    "jwt-handling": "Pin algorithms and verify signature/issuer/audience/expiration.",
    "github-workflow-security": "PR-triggered workflows with secrets, mutable actions, or shell interpolation are supply-chain risks.",
    "agentic-untrusted-prompt-input": "Separate trusted instructions from untrusted retrieved/user content.",
    "mcp-tool-handler": "Review tool schema, capability allowlist, and side-effect boundaries.",
}


def load_base_system_prompt() -> str:
    return (
        resources.files("pythinker_review.security_scan.prompts")
        .joinpath("system.md")
        .read_text(encoding="utf-8")
        .strip()
    )


def assemble_prompt(
    *,
    detected_tags: list[str],
    batch_slugs: list[str],
    batch_languages: list[str],
    project_info: str = "",
    prompt_append: str | None = None,
    records: list[FileRecord],
    project_root: Path,
    file_char_budget: int = _DEFAULT_FILE_CHAR_BUDGET,
) -> PromptAssembly:
    sections = [load_base_system_prompt()]
    highlights, included_tags = _framework_section(detected_tags, batch_languages)
    if highlights:
        sections.append(highlights)
    slug_section = _slug_section(batch_slugs)
    if slug_section:
        sections.append(slug_section)
    if project_info.strip():
        sections.append("## Project-specific context\n\n" + project_info.strip())
    if prompt_append and prompt_append.strip():
        sections.append("## Additional project policy\n\n" + prompt_append.strip())

    user = build_user_prompt(
        records=records, project_root=project_root, file_char_budget=file_char_budget
    )
    system = "\n\n---\n\n".join(sections)
    return PromptAssembly(
        system=system,
        user=user,
        included_tags=included_tags,
        slugs_with_notes=slug_section.count("\n- `") + (1 if slug_section.startswith("- `") else 0),
        total_chars=len(system) + len(user),
    )


def build_user_prompt(
    *, records: list[FileRecord], project_root: Path, file_char_budget: int
) -> str:
    file_sections: list[str] = []
    for record in records:
        candidates = "\n".join(
            f"  - [{candidate.vuln_slug}] L{', '.join(map(str, candidate.line_numbers))}: "
            f"{candidate.matched_pattern}\n    snippet: {candidate.snippet[:500]}"
            for candidate in record.candidates
        )
        if not candidates:
            candidates = "  - no scanner hits; holistic security review requested"
        content = _read_file(project_root / record.file_path)
        rendered_content = (
            clip_text(content, file_char_budget) if content else "[unreadable or binary]"
        )
        file_sections.append(
            f"## File: {record.file_path}\n\n"
            f"### Candidate matcher hits\n{candidates}\n\n"
            f"### File content\n```\n{rendered_content}\n```"
        )
    return (
        "Review the following Pythinker Security Scan target batch. Include every file in the JSON output.\n\n"
        + "\n\n---\n\n".join(file_sections)
    )


def batch_languages(records: list[FileRecord]) -> list[str]:
    return languages_for_paths([record.file_path for record in records])


def _framework_section(tags: list[str], languages: list[str]) -> tuple[str, list[str]]:
    lang_set = set(languages)
    blocks: list[str] = []
    included: list[str] = []
    for tag in tags:
        item = _TECH_HIGHLIGHTS.get(tag)
        if item is None:
            continue
        title, allowed_languages, bullets = item
        if lang_set and not lang_set.intersection(allowed_languages):
            continue
        included.append(tag)
        blocks.append("### " + title + "\n" + "\n".join(f"- {bullet}" for bullet in bullets))
    if not blocks:
        return "", []
    full = "## Threat highlights for this repo's tech stack\n\n" + "\n\n".join(blocks)
    if len(full) <= _FRAMEWORK_SECTION_CHAR_BUDGET:
        return full, included
    return (
        clip_text(
            "## Tech in this repo\n\n"
            f"Detected {len(included)} security-relevant stacks: {', '.join(included)}. "
            "Apply auth, input validation, authorization, output escaping, and trust-boundary checks.",
            _FRAMEWORK_SECTION_CHAR_BUDGET,
        ),
        included,
    )


def _slug_section(slugs: list[str]) -> str:
    lines = [
        f"- `{slug}`: {_SLUG_NOTES[slug]}" for slug in sorted(set(slugs)) if slug in _SLUG_NOTES
    ]
    return "## Slug-specific reviewer notes\n\n" + "\n".join(lines) if lines else ""


def _read_file(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return None
