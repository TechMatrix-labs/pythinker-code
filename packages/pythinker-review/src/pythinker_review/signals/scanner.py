"""Deterministic Pythinker Security Scan signal scanner. Prompt anchors only."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pythinker_review.signals.models import Signal


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: str
    pattern: re.Pattern[str]
    reason: str
    confidence: float
    source_kind: str | None = None
    sink_kind: str | None = None
    exploitability: str | None = None
    mitigation_hint: str | None = None
    cwe: str | None = None
    severity_hint: str | None = None


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "sec.signal.secrets_exposure.aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "Looks like an AWS access key ID added to source.",
        0.95,
        source_kind="literal",
        sink_kind="source",
        exploitability="Committed credentials can be used directly if active.",
        mitigation_hint="Remove the key, rotate it, and load credentials from a secret store.",
        cwe="CWE-798",
        severity_hint="critical",
    ),
    _Rule(
        "sec.signal.secrets_exposure.generic_token",
        re.compile(
            r"""(?ix)
            (?:api[_-]?key|secret|token|password|passwd|pwd|client[_-]?secret)\s*[=:]\s*
            ['\"][A-Za-z0-9_\-./+=]{16,}['\"]
            """
        ),
        "Possible hardcoded credential.",
        0.7,
        source_kind="literal",
        sink_kind="source",
        mitigation_hint="Load secrets from environment or a secret manager.",
        cwe="CWE-798",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.secret_in_log.credential_logging",
        re.compile(
            r"(?i)\b(?:log|logger)\.(?:debug|info|warn|error)\([^)]*(?:token|secret|password|api[_-]?key)"
        ),
        "Credential-looking value appears in a log statement.",
        0.7,
        sink_kind="logging",
        mitigation_hint="Never log credentials; redact before logging.",
        cwe="CWE-532",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.rce.shell_true",
        re.compile(
            r"""(?x)
            (?:subprocess\.(?:run|Popen|call|check_call|check_output)|os\.(?:system|popen))
            \([^)]*\bshell\s*=\s*True
            """
        ),
        "shell=True with dynamic argument shape.",
        0.75,
        sink_kind="command_execution",
        mitigation_hint="Pass argv as a list and avoid shell=True unless input is fixed.",
        cwe="CWE-78",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.rce.eval_exec",
        re.compile(
            r"""(?x)
            \b(?:eval|exec|Function|setTimeout|setInterval)\s*\(
            [^)]*
            \b(?:req|request|userInput|user_input|user_id|user_data|input|body|query|params|payload)\b
            """
        ),
        "Dynamic code execution appears to use request/user-controlled data.",
        0.7,
        sink_kind="code_execution",
        mitigation_hint="Remove dynamic evaluation or constrain input to a vetted allowlist.",
        cwe="CWE-94",
        severity_hint="critical",
    ),
    _Rule(
        "sec.signal.sql_injection.python_concat",
        re.compile(
            r"""(?ix)
            (?:cursor|conn|connection|db)\.execute\s*\(
            \s*["'][^"']*\b(?:SELECT|INSERT|UPDATE|DELETE)\b[^"']*["']\s*[+%]
            """
        ),
        "SQL string concatenation passed to execute().",
        0.85,
        sink_kind="sql_execution",
        mitigation_hint="Use parameterized queries.",
        cwe="CWE-89",
        severity_hint="critical",
    ),
    _Rule(
        "sec.signal.sql_injection.js_template",
        re.compile(
            r"(?i)\b(?:query|execute|raw)\s*\(\s*`[^`]*(?:SELECT|INSERT|UPDATE|DELETE)[^`]*\$\{"
        ),
        "Template-interpolated SQL passed to a raw/query API.",
        0.85,
        sink_kind="sql_execution",
        mitigation_hint="Use bound parameters or ORM query builders.",
        cwe="CWE-89",
        severity_hint="critical",
    ),
    _Rule(
        "sec.signal.nosql_injection.mongo_operator",
        re.compile(
            r"\b(?:findOne|find|updateOne|deleteOne)\s*\([^)]*(?:req\.(?:body|query|params)|request\.)"
        ),
        "Request data appears to flow directly into a NoSQL query object.",
        0.55,
        sink_kind="database_query",
        mitigation_hint="Pick allowed fields and reject operator keys such as `$ne`/`$where`.",
        cwe="CWE-943",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.unsafe_deserialization.pickle",
        re.compile(r"\b(?:pickle|yaml)\.(?:load|loads)\s*\("),
        "Unsafe deserialization of potentially untrusted data.",
        0.7,
        sink_kind="deserialization",
        mitigation_hint="Use a safe format or prove the input is trusted; for YAML use safe_load.",
        cwe="CWE-502",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.ssrf.variable_url",
        re.compile(
            r"""(?x)
            (?:
                # method-style: requests.get(url), axios.post(url), httpx.request(url)
                (?:requests|urllib|httpx|aiohttp|axios)
                \.(?:get|post|put|delete|patch|request|head)
                \s*\(\s*[A-Za-z_]
                |
                # bare-fetch (JS Fetch API): fetch(url, ...)
                \bfetch\s*\(\s*[A-Za-z_]
            )
            """
        ),
        "HTTP request to a URL held in a variable; check for SSRF guard.",
        0.5,
        sink_kind="http_client",
        mitigation_hint="Validate scheme/host and block private-network destinations.",
        cwe="CWE-918",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.path_traversal.file_join_user_input",
        re.compile(
            r"\b(?:open|readFile|writeFile|send_file|FileResponse|path\.join)\s*\([^)]*(?:req|request|user|input|filename|path)"
        ),
        "File path operation appears to include user-controlled input.",
        0.6,
        sink_kind="filesystem",
        mitigation_hint="Normalize, resolve, and enforce containment inside an allowlisted base directory.",
        cwe="CWE-22",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.xss.unsafe_html",
        re.compile(r"\b(?:dangerouslySetInnerHTML|innerHTML\s*=|v-html|html\s*\()"),
        "Unsafe HTML rendering sink; trace whether data is attacker-controlled and escaped.",
        0.65,
        sink_kind="html_rendering",
        mitigation_hint="Use framework escaping or sanitize with a vetted HTML sanitizer.",
        cwe="CWE-79",
        severity_hint="high",
    ),
    _Rule(
        "sec.signal.open_redirect.user_controlled_redirect",
        re.compile(
            r"\b(?:redirect|RedirectResponse|res\.redirect|router\.push)\s*\([^)]*(?:next|url|redirect|returnTo|req|request)"
        ),
        "Redirect target appears user-controlled.",
        0.6,
        sink_kind="redirect",
        mitigation_hint="Use a same-origin or explicit allowlist check before redirecting.",
        cwe="CWE-601",
        severity_hint="medium",
    ),
    _Rule(
        "sec.signal.cors_wildcard.allow_all",
        re.compile(
            r"(?i)(?:Access-Control-Allow-Origin|allow_origins|origin)\s*[:=]\s*['\"]\*['\"]"
        ),
        "Wildcard CORS configuration; check credentialed or sensitive routes.",
        0.55,
        sink_kind="cors_config",
        mitigation_hint="Use an explicit trusted-origin allowlist.",
        cwe="CWE-942",
        severity_hint="medium",
    ),
    _Rule(
        "sec.signal.jwt_handling.algorithm_confusion",
        re.compile(
            r"(?i)jwt\.(?:decode|verify)\s*\([^)]*(?:verify\s*[:=]\s*False|algorithms\s*[:=]\s*None|none)"
        ),
        "JWT verification appears disabled or algorithm handling is weak.",
        0.8,
        sink_kind="auth",
        mitigation_hint="Require signature verification, expiration, issuer/audience, and pinned algorithms.",
        cwe="CWE-347",
        severity_hint="critical",
    ),
    _Rule(
        "sec.signal.missing_auth.public_handler",
        re.compile(
            r"""(?ix)
            # State-changing route only (POST/PUT/DELETE/PATCH); GET is too noisy.
            \b(?:app|router|api)\.(?:post|put|delete|patch)\b
            # Reject lines that already carry common auth markers — same-line check
            # only; the LLM still gets multi-line context to catch the rest.
            (?![^\n]*\b(?:Depends|Security|requires_auth|require_auth|login_required|
                         authenticated|permission_classes|auth_required|HTTPBearer|
                         OAuth2|api_key|APIKey|@protected|@admin)\b)
            """
        ),
        "State-changing route without inline auth marker; verify auth/authz coverage.",
        0.35,
        sink_kind="http_handler",
        mitigation_hint="Ensure handler-level auth/permission checks wrap the route directly.",
        cwe="CWE-306",
        severity_hint="medium",
    ),
    _Rule(
        "sec.signal.rate_limit_bypass.expensive_operation",
        re.compile(r"(?i)\b(?:openai|anthropic|stripe|sendgrid|twilio|llm|completion|embedding)\b"),
        "Expensive or paid operation touched; check abuse/rate limiting and auth.",
        0.35,
        sink_kind="external_api",
        mitigation_hint="Add auth, quota, and rate limits close to the handler.",
        cwe="CWE-770",
        severity_hint="medium",
    ),
    _Rule(
        "sec.signal.agentic_untrusted_prompt_input.prompt_injection",
        re.compile(
            r"""(?ix)
            # Require a sink shape (assignment, concat, append, format) where a
            # prompt/messages container is fed something that *looks* untrusted —
            # not just a bare mention of "prompt" anywhere in the file.
            \b(?:system_prompt|developer_prompt|prompt|messages|user_message|tool_output)\b
            \s*(?:=\s*f?["']|\+=|\.append\b|\.extend\b|\.format\b)
            [^\n]*?
            \b(?:user(?:_|\b)|request\b|req\b|webpage\b|issue_body\b|pull_request_body\b|comment\b|input\b|body\b|payload\b)
            """
        ),
        "Untrusted content flows into a prompt/messages container; treat as data, not instructions.",
        0.4,
        sink_kind="agent_context",
        mitigation_hint="Separate trusted instructions from untrusted retrieved/user content and quote it as data.",
        cwe="CWE-20",
        severity_hint="medium",
    ),
    _Rule(
        "sec.signal.crypto_weak_hash.md5_sha1",
        re.compile(r"\b(?:hashlib\.(?:md5|sha1)|crypto\.createHash\(['\"](?:md5|sha1)['\"])"),
        "Weak hash used; verify it is not a security boundary.",
        0.6,
        sink_kind="crypto",
        mitigation_hint="Use SHA-256+ or a password-hashing/KDF primitive as appropriate.",
        cwe="CWE-327",
        severity_hint="medium",
    ),
    _Rule(
        "sec.signal.debug_endpoint.enabled",
        re.compile(
            r"(?i)\b(?:debug\s*=\s*True|DEBUG\s*=\s*True|/debug|/admin/debug|werkzeug\.debug)\b"
        ),
        "Debug mode or endpoint appears enabled.",
        0.55,
        sink_kind="debug_surface",
        mitigation_hint="Disable debug surfaces in production and guard internal diagnostics.",
        cwe="CWE-489",
        severity_hint="medium",
    ),
)


def scan_signals(*, file_path: str, added_lines: list[tuple[int, str]]) -> list[Signal]:
    out: list[Signal] = []
    for lineno, text in added_lines:
        for rule in _RULES:
            if rule.pattern.search(text):
                out.append(
                    Signal(
                        rule_id=rule.rule_id,
                        file=file_path,
                        line=lineno,
                        snippet=text.strip(),
                        reason=rule.reason,
                        confidence=rule.confidence,
                        source_kind=rule.source_kind,
                        sink_kind=rule.sink_kind,
                        exploitability=rule.exploitability,
                        mitigation_hint=rule.mitigation_hint,
                        cwe=rule.cwe,
                        severity_hint=rule.severity_hint,
                    )
                )
    return out
