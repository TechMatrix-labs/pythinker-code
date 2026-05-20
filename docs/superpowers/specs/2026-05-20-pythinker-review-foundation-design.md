# Pythinker Review — Phase 1: Foundation + Diff-Only Gate

**Date:** 2026-05-20
**Status:** Spec — revised after blackbox design review
**Scope:** Phase 1 of a multi-phase project to add code-review and security-review
capabilities to Pythinker, porting selected concepts from `blackbox/clawpatch-main`,
`blackbox/code-review`, and `blackbox/deepsec-main`.

## 1. Goal

Ship the substrate and one immediately useful capability: a diff-only review gate.

- Substrate: a new `packages/pythinker-review` workspace package containing the
  reusable review engine, findings data model, JSON-on-disk store, structured
  diff renderer, deterministic security-signal scanner, output formatters, and
  standalone Typer CLIs.
- Pythinker integration: `pythinker-code` owns the root CLI wrappers and built-in
  subagent YAML roles (`code-reviewer`, `security-reviewer`). The package does
  not auto-register subagents because the current Pythinker subagent registry is
  populated from agent YAML at runtime.
- Capability: `pythinker review diff` and `pythinker secscan diff` review only
  issues introduced by the current diff against a base ref, emit findings in
  pretty / JSON / SARIF, and optionally fail the build on a configurable severity
  threshold.

Out of scope for Phase 1 (each gets its own future spec):

- Phase 2: clawpatch-style whole-repo semantic slicing + local audit.
- Phase 3: deepsec-style extensible matcher plugins, INFO.md authoring workflow,
  revalidation, and multi-machine worker fan-out. Phase 1 includes only a small
  built-in security signal scanner as prompt anchors.
- Phase 4: PR-provider integrations (GitHub / GitLab / Bitbucket / Azure DevOps).
- Phase 5: clawpatch-style fix loop (`fix --finding <id>`, patch attempts).

## 2. Success criteria

A change is done when:

1. `make check-pythinker-review && make test-pythinker-review` pass.
2. From any git repo on `main`, after creating a branch with a planted bug and
   a planted security issue, `pythinker review diff --with-security` produces
   at least one finding for each, in pretty / JSON / SARIF format.
3. `pythinker review diff --fail-on high` exits non-zero when a high-or-above
   finding is produced and exits zero otherwise.
4. Any chunk timeout, malformed model output after retry, LLM error, or worker
   exception makes the run fail non-green by default. A partial run can complete
   only when the user passes `--allow-partial`, and the output must make partial
   coverage obvious.
5. `--save` writes a complete `runs/<id>/` directory; `pythinker review list`
   and `pythinker review show <id>` reproduce the run's findings without another
   LLM call.
6. `pythinker review diff` defaults `--model` to the active Pythinker model by
   having `pythinker-code` inject a model adapter into `pythinker-review`; the
   standalone `pythinker-review` CLI never imports `pythinker-code` to discover
   config/auth.
7. Inside an interactive Pythinker session, dispatching to `code-reviewer` or
   `security-reviewer` uses YAML-defined built-in roles and returns output in the
   existing `SUMMARY / EVIDENCE / CHANGES / RISKS / BLOCKERS` shape.
8. No regression in existing `pythinker` commands; existing `review` and
   `verifier` subagent roles continue to work.
9. Phase 1 adds no unapproved third-party runtime dependencies. Use stdlib
   `subprocess` for git and a stdlib timestamp-random run ID instead of GitPython
   or `ulid-py`.

## 3. Non-goals

- Auto-applying fixes. Findings may carry a `suggestion.patch` string for the
  user to review, but Phase 1 never writes to source files.
- Posting comments to GitHub / GitLab / etc. Pretty / JSON / SARIF only.
- Whole-repo scanning. Diff-only, plus bounded current-file / related-file
  context when needed to judge the diff.
- Full deepsec matcher plugin architecture. Phase 1 has a minimal built-in signal
  scanner only.
- Package-based subagent discovery. Phase 1 registers subagents through the
  existing agent YAML mechanism.
- Parallel worker machines. In-process asyncio fan-out only.
- New telemetry endpoints, hosted services, GitPython, `ulid-py`, or other new
  third-party runtime dependencies without explicit maintainer approval.

## 4. Architecture

### 4.1 Package layout

```
packages/pythinker-review/
├── pyproject.toml                 # console_scripts: pythinker-review, pythinker-secscan
├── README.md
├── src/pythinker_review/
│   ├── __init__.py
│   ├── cli/                       # standalone Typer apps
│   ├── engine/                    # diff_source, structured_diff, chunker, runner, dedupe
│   ├── llm/                       # tiny ReviewLLM protocol + adapters used by tests/standalone CLI
│   ├── reviewers/                 # code_review, security_review, schema, prompt assets
│   ├── signals/                   # built-in deterministic security signal scanner
│   ├── store/                     # findings_store, run, models, gitignore
│   └── output/                    # pretty, json, sarif
└── tests/
    ├── unit/
    └── e2e/
```

Pythinker integration edits live in `pythinker-code`:

```
src/pythinker_code/cli/review.py              # delegates to pythinker_review CLI/app
src/pythinker_code/cli/secscan.py             # delegates to pythinker_review CLI/app
src/pythinker_code/cli/_lazy_group.py         # adds review/secscan lazy commands
src/pythinker_code/agents/default/agent.yaml  # registers new built-in subagents
src/pythinker_code/agents/default/code_reviewer.yaml
src/pythinker_code/agents/default/security_reviewer.yaml
```

`make` targets follow the existing package pattern:
`make check-pythinker-review`, `make test-pythinker-review`, plus inclusion from
root `make check` / `make test` after the package is added to the workspace. The
verification matrix in `AGENTS.md` gets one new row.

### 4.2 Dependency direction and model injection

```
pythinker-code  ──imports/wraps──▶  pythinker-review  ──uses──▶  pythinker-core
                                                        └──▶  stdlib subprocess + existing deps
```

`pythinker-review` does not import `pythinker-code`. It exposes a small
`ReviewLLM` protocol, for example:

```python
class ReviewLLM(Protocol):
    model_display_name: str

    async def complete_json(self, *, system: str, user: str, timeout_s: float) -> str: ...
```

- `pythinker-code` creates the active model using existing Pythinker config,
  OAuth, managed-provider, and session code, then passes a `ReviewLLM` adapter
  into the review engine. This is what makes `pythinker review diff --model`
  default to the active Pythinker provider.
- The standalone `pythinker-review` / `pythinker-secscan` console scripts use
  only explicit CLI/env configuration or the fake test LLM. They are useful for
  package tests and simple automation, but they do not claim to know the active
  Pythinker session model.
- Tests inject a fake `ReviewLLM` returning canned JSON; no real secrets or LLM
  calls are required for normal CI.

### 4.3 Root CLI and standalone CLI

The shared engine powers four surfaces:

- `pythinker review diff` → Pythinker-integrated code review.
- `pythinker review diff --with-security` → code + security passes in parallel.
- `pythinker secscan diff` → Pythinker-integrated security pass.
- `pythinker-review diff` / `pythinker-secscan diff` → standalone package CLIs
  with explicit/env model configuration.

The two root commands are added through `_lazy_group.py` so `pythinker --help`
shows them without importing heavy review code during normal startup.

## 5. Components

All paths in this section are inside `src/pythinker_review/` unless explicitly
marked as `pythinker-code` integration.

### 5.1 `engine/`

**`diff_source.py`** — resolves the diff, file list, and SHAs.

Algorithm:

1. If `--range A..B` is given, use it directly.
2. Else if `--working-tree`, resolve tracked working-tree changes plus staged
   changes; include untracked non-ignored files as added files.
3. Else if `--staged`, use `git diff --cached`.
4. Else (default): resolve base ref by trying `--base` (default `origin/main`),
   falling back to `main`, then `master`. Diff is `git merge-base HEAD <base>`
   .. HEAD.
5. Use stdlib `subprocess.run(...)` with bounded timeouts. Do not add GitPython.
6. Reject the run with exit 2 if the diff/file list is empty after filters.

Output: a `ResolvedDiff` containing raw patch text, base/head SHAs, base ref,
source label, and POSIX repo-relative changed file paths.

**`structured_diff.py`** — converts unified diff to blackbox-style review input.

For each file and hunk, render:

```text
## File: 'src/file.py'

@@ ... @@ optional section header
__new hunk__
42   unchanged context
43 + added or changed line
44   unchanged context
__old hunk__
     unchanged context
-    removed line
     unchanged context
```

Rules:

- New hunk lines are numbered with post-change file line numbers.
- Old hunk lines keep removed content for comparison but are not the primary
  location target.
- Reviewers must flag only issues introduced by the diff. A finding location
  must point to a changed post-change line when possible. For pure deletions
  that introduce risk, anchor to the nearest post-change hunk line and include
  the removed line in `evidence_snippet`.
- The renderer keeps enough context to understand scope boundaries and must not
  treat an opening brace / block boundary at the end of a hunk as incomplete code.

**`context.py`** — gathers bounded file context.

- Include the full current changed file when it fits the chunk budget.
- Otherwise include the structured diff plus bounded current-file sections around
  each hunk.
- Include base-file snippets from `git show <base_sha>:<path>` only for the
  hunks under review, so the model can compare before/after behavior.
- For security pass only, include small related-file snippets when cheaply
  discoverable from imports or obvious local call targets. This is bounded,
  best-effort context, not whole-repo scanning.

**`chunker.py`** — splits review work.

- Default: one chunk per changed file.
- If a single file exceeds the per-chunk budget, split at hunk boundaries.
- Honors `--include <glob>` / `--exclude <glob>` before chunking.
- Skips binary diffs and vendored/generated paths by default:
  `node_modules/`, `.venv/`, `dist/`, `build/`, `.pythinker-review/`, `.git/`,
  coverage/build artifacts, and common generated lock/output directories.
- `--no-skip-vendored` disables only the vendored/generated skip list, not git
  safety checks.

Output: `Chunk(file, hunks, structured_diff, current_context, base_context,
security_signals, related_context)`.

**`runner.py`** — concurrency, retry, and fail-closed behavior.

- Asyncio worker pool sized by `--jobs` (default 4).
- For each `(chunk, pass)` pair, schedule one LLM call.
- Per-chunk timeout (default 120s).
- Malformed JSON gets one retry with a stricter suffix. A second failure marks
  the chunk failed.
- Any timeout, chunk LLM error, worker exception, or malformed output after
  retry increments `chunks_failed` and makes the whole run fail non-green by
  default.
- `--allow-partial` converts those chunk failures into a completed-with-warnings
  result, but output must list the skipped chunks and JSON output must include a
  `warnings` array.
- On Ctrl-C: cancel pending, mark run `cancelled`, flush partial findings, exit
  130.

**`dedupe.py`** — collapses duplicates.

Key: `(file, max(start_line, 1), min(end_line, +inf), rule_id)`. When two
findings collide, keep higher `severity`, then higher `confidence`, then earlier
`pass` order (`security_review` wins ties on intent).

### 5.2 `signals/`

Phase 1 includes a small deterministic security signal scanner inspired by
Deepsec's direct mode. Signals are prompt anchors only; they are not emitted as
findings unless the reviewer validates them.

Built-in signal families:

- secrets/credentials added in the diff;
- command/process execution fed by changed variables;
- SQL/template/query construction from user-controlled-looking values;
- SSRF-like fetch/request/proxy patterns;
- deserialization/archive extraction of untrusted-looking data;
- crypto misuse and insecure random/token generation;
- authn/authz/permission bypass hints;
- dependency or workflow changes that introduce supply-chain risk.

`Signal` fields: `rule_id`, `file`, `line`, `snippet`, `reason`, `confidence`.
The security prompt receives signals grouped by file with an explicit reminder:
"Signals are starting points; verify in code before emitting a finding."

### 5.3 `reviewers/`

**`schema.py`** — pydantic models the LLM is asked to produce.

```python
class ReviewerOutput(BaseModel):
    findings: list[RawFinding]

class RawFinding(BaseModel):
    rule_id: str
    title: str = Field(max_length=80)
    rationale: str
    category: Category
    severity: Severity
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_snippet: str | None = None
    suggestion: Suggestion | None = None
```

Reviewer post-processing converts `RawFinding` → `Finding` by attaching `id`,
`pass`, `created_at`, `run_id`, and the head SHA for `Location`. It validates
that file paths are repo-relative POSIX paths and that line ranges intersect the
changed post-change file where possible.

**`code_review.py`** — prompt + caller for the code-review pass. Covers
correctness, design, performance, readability, missing tests, and API breakage.
Prompt rules are adapted from `blackbox/code-review` and must include:

- focus on issues introduced by this diff;
- prefer no finding over vague speculation;
- flag clear bugs/security issues even when trigger scenarios are narrow;
- low-severity concerns require high confidence;
- cite concrete failure modes and changed lines;
- output strict JSON only.

**`security_review.py`** — prompt + caller for the security pass. Covers
injection, authn/authz, secrets, SSRF, deserialization, crypto misuse,
supply-chain risk, unsafe defaults, and project-specific mitigations found in
bounded context. The prompt receives deterministic `signals` and project context
but must verify findings against code before output.

Both reviewers:

- Use strict pydantic validation at the model boundary.
- Retry once on malformed JSON with a stricter prompt suffix.
- Treat the second malformed response as a chunk failure. The runner decides
  whether that fails the whole run (`default`) or becomes a warning
  (`--allow-partial`).

### 5.4 `store/`

**`models.py`** — pydantic models defined in §6 below.

**`findings_store.py`** — append-only JSONL writer.

- `runs/<run-id>/findings.jsonl` is opened once per run and appended per finding
  (`fsync` on close, not per write).
- `runs/<run-id>/meta.json` and `index.json` updates use `.tmp` + atomic rename
  to avoid partial writes on crash.
- Run ID uses stdlib only: `YYYYMMDDHHMMSS-<secrets.token_hex(4)>`. It sorts
  lexicographically by time and avoids an unapproved `ulid-py` dependency.

**`run.py`** — `RunMeta` lifecycle helpers. Wraps create / update / finalize
transitions and records failed chunk metadata.

**`gitignore.py`** — idempotent `.gitignore` patcher.

- Triggers only on first `--save` per repo.
- Only modifies `.gitignore` if it already exists. If it doesn't, the run still
  succeeds; it logs an info note that `.pythinker-review/` was not added.
- Adds one line `.pythinker-review/` under a `# pythinker-review` marker comment,
  only if not already present.

### 5.5 `output/`

**`pretty.py`** — human rendering using existing workspace dependencies only.
Per finding: severity chip, file:line, title, rationale, optional suggestion.
Findings are grouped by file and sorted by `(severity desc, file, start_line)`.
If partial failures occurred, a warning block appears before findings.

**`json.py`** — emits:

```json
{"run": {}, "findings": []}
```

`run` is the full `RunMeta` (so `run.chunk_failures` carries any partial-coverage
warnings — no separate `warnings` array needed at this layer). The `findings`
schema is the same as on-disk JSONL after re-aggregation.

**`sarif.py`** — SARIF 2.1.0. Severity mapping:

| Our severity | SARIF level |
|---|---|
| critical, high | `error` |
| medium | `warning` |
| low, info | `note` |

`rule_id` maps to `ruleId`; `Location` maps to one `physicalLocation` with
`region.startLine` / `endLine`. Chunk/runtime failures are represented as tool
notifications when SARIF supports them, and remain visible in JSON/pretty.

### 5.6 `cli/`

Standalone package CLIs:

```text
pythinker-review diff [--with-security] [shared flags]
pythinker-review list [--limit N]
pythinker-review show <run-id> [--format pretty|json|sarif]

pythinker-secscan diff [shared flags]
```

`pythinker-code` exposes root commands by adding lazy wrappers:

```text
pythinker review diff [--with-security] [shared flags]
pythinker review list [--limit N]
pythinker review show <run-id> [--format pretty|json|sarif]

pythinker secscan diff [shared flags]
```

The wrappers import `pythinker_review`, build a Pythinker-backed `ReviewLLM`
adapter from the active config/session model, and call the shared app/engine.
They do not shell out to `pythinker-review`.

### 5.7 `pythinker-code` subagent roles

Phase 1 adds two YAML agent specs, not package auto-registration:

- `src/pythinker_code/agents/default/code_reviewer.yaml`
- `src/pythinker_code/agents/default/security_reviewer.yaml`

`src/pythinker_code/agents/default/agent.yaml` registers them under:

```yaml
subagents:
  code-reviewer:
    path: ./code_reviewer.yaml
    description: "Diff-focused code review with severity-scored findings."
  security-reviewer:
    path: ./security_reviewer.yaml
    description: "Diff-focused security review with validated findings."
```

Each role is read-only by convention and uses existing shell/read/grep tools to
run `pythinker review diff` or `pythinker secscan diff`, then reformats output
into the structured response block below.

This shell-out path is intentional for Phase 1: it keeps the YAML role free of
new Python wiring, lets the subagent reuse the exact CLI users hit, and lines
up with how `coder` / `review` / `verifier` currently operate. Cost: one
subprocess + re-import of the review engine per dispatch. Acceptable for diff-
sized runs. Future work (deferred, separate spec): an in-process call path that
shares the parent agent's `ReviewLLM` adapter to avoid the subprocess hop.


```text
### SUMMARY
### EVIDENCE
### CHANGES
None.
### RISKS
### BLOCKERS
```

The existing `review` subagent role is left untouched.

## 6. Data model

```python
class Severity(str, Enum):
    critical = "critical"   # exploitable now, or correctness break with prod impact
    high     = "high"       # likely bug or vuln; fix before merge
    medium   = "medium"     # real issue, defer-with-issue acceptable
    low      = "low"        # nit, style, micro-perf
    info     = "info"       # FYI, no action required

class Category(str, Enum):
    correctness   = "correctness"
    security      = "security"
    performance   = "performance"
    readability   = "readability"
    test_coverage = "test_coverage"
    api_design    = "api_design"
    dependency    = "dependency"
    secret        = "secret"

class Location(BaseModel):
    file: str                  # repo-relative POSIX path
    start_line: int            # 1-indexed post-change line, inclusive
    end_line: int              # 1-indexed post-change line, inclusive
    sha: str | None = None     # commit SHA the line numbers refer to

class Suggestion(BaseModel):
    summary: str               # one-sentence what-to-change
    patch: str | None = None   # unified diff; validated parseable, not applied

class Finding(BaseModel):
    id: str                    # sha256(rule_id + file + start_line + title)[:12]
    rule_id: str               # e.g. "sec.injection.sql", "review.error_handling"
    title: str                 # ≤80 chars
    rationale: str             # markdown
    category: Category
    severity: Severity
    location: Location
    pass_: Literal["code_review", "security_review"] = Field(alias="pass")
    suggestion: Suggestion | None = None
    evidence_snippet: str | None = None
    confidence: float          # 0.0–1.0
    triage: Literal["open", "false_positive", "accepted", "wont_fix"] = "open"
    triage_note: str | None = None
    created_at: datetime
    run_id: str

class ChunkFailure(BaseModel):
    file: str
    pass_: Literal["code_review", "security_review"] = Field(alias="pass")
    reason: Literal["timeout", "llm_error", "malformed_output", "worker_error"]
    message: str

class RunMeta(BaseModel):
    id: str                    # YYYYMMDDHHMMSS-<8 hex chars>
    started_at: datetime
    finished_at: datetime | None
    status: Literal["running", "completed", "completed_with_warnings", "failed", "cancelled"]
    repo_root: str
    branch: str | None
    head_sha: str
    base_ref: str
    base_sha: str
    source_label: str          # e.g. git-diff:origin/main, staged, working-tree
    passes: list[Literal["code_review", "security_review"]]
    model: str                 # provider:model-id or standalone model id
    chunks_total: int
    chunks_done: int
    chunks_failed: int
    findings_count: int
    allow_partial: bool
    chunk_failures: list[ChunkFailure]
    config_hash: str           # hash of reviewer prompts + rule list + signal rules
```

### 6.1 On-disk layout

```
.pythinker-review/
├── index.json                       # {"runs": [{id, started_at, branch, head_sha, status, findings_count}, ...]}
└── runs/
    └── 20260520123045-a1b2c3d4/
        ├── meta.json                # RunMeta, including chunk_failures + allow_partial
        ├── findings.jsonl           # one Finding per line, append-only
        └── diff.patch               # the diff reviewed (for reproducibility)
```

`index.json` is trimmed to the most recent 200 runs; older entries stay on disk
under `runs/` but are not indexed. `pythinker review list` reads `index.json`;
`pythinker review show <id>` reads `runs/<id>/` directly so unindexed older runs
are still recoverable when the user knows the ID.

## 7. CLI surface

Shared option group for `review diff` / `secscan diff`:

| Flag | Default | Purpose |
|---|---|---|
| `--base <ref>` | `origin/main` → `main` → `master` | Base ref for `merge-base HEAD <ref>` |
| `--staged` | off | Diff staged vs HEAD |
| `--working-tree` | off | Diff working tree, staged changes, and untracked non-ignored files |
| `--range A..B` | — | Arbitrary range |
| `--format pretty\|json\|sarif` | `pretty` if TTY else `json` | Output format |
| `--fail-on critical\|high\|medium\|low\|none` | `high` | Exit non-zero when finding ≥ threshold |
| `--allow-partial` | off | Permit completed-with-warnings output when chunks fail; otherwise chunk failures exit 4 |
| `--jobs N` | `4` | Worker pool size |
| `--model <id>` | active Pythinker provider for `pythinker ...`; explicit/env for standalone CLI | Override LLM |
| `--save / --no-save` | `--save` | Persist to `.pythinker-review/runs/<id>/` |
| `--quiet` | off | Suppress progress UI |
| `--include <glob>` | — (repeatable) | Filter to matching files (gitignore-style glob, matched against repo-relative POSIX path) |
| `--exclude <glob>` | — (repeatable) | Skip matching files (same glob semantics as `--include`; `--exclude` wins on conflict) |
| `--no-skip-vendored` | off | Don't auto-skip vendored/generated paths |

Exit codes:

- `0` — success, no finding ≥ `--fail-on`, and no chunk/runtime failures.
- `1` — success, at least one finding ≥ `--fail-on`.
- `2` — preflight error (no git, no diff, base ref unresolvable, bad flags).
- `3` — environment/provider error (LLM auth, quota, network, or other failure
  that prevents the run from making progress). Rerunning without fixing
  credentials/connectivity will fail again. CI should treat this as
  "operator-actionable".
- `4` — chunk-level failure without `--allow-partial` (per-chunk timeout,
  malformed output after retry, worker exception). The run completed enough to
  finalize `meta.json` with `status: failed` and `chunk_failures` populated.
  Rerunning may succeed.
- `130` — Ctrl-C (run marked `cancelled`).

If `--allow-partial` is set and chunks fail, exit code is governed by
`--fail-on` instead of `4`, but output must show
`status: completed_with_warnings`, `chunks_failed > 0`, and the populated
`chunk_failures` list.

## 8. Error handling

Fail loud at the boundary and fail closed for CI.

| Condition | Where caught | Behavior |
|---|---|---|
| `git` missing / not a repo | preflight | exit 2 with clear message |
| base ref unresolvable | preflight | exit 2 |
| empty diff after filters | preflight | exit 2, "no changes to review" |
| LLM auth / quota / network error at runner startup | runner startup | exit 3, surface provider name |
| LLM auth / quota / network error mid-run, affecting all chunks | runner | finalize partials, exit 3 |
| Per-chunk timeout | runner | record `ChunkFailure(reason="timeout")`; default exit 4 |
| Per-chunk LLM error (non-systemic) | runner | record `ChunkFailure(reason="llm_error")`; default exit 4 |
| Malformed JSON | reviewer | one retry; second failure records `ChunkFailure(reason="malformed_output")`; default exit 4 |
| Worker exception | runner | record `ChunkFailure(reason="worker_error")`; default exit 4 |
| Ctrl-C | runner | cancel pending, mark `cancelled`, flush partials, exit 130 |

`--allow-partial` is the only way for `chunks_failed > 0` to produce a completed
run. Without it, `meta.json` is finalized with `status: failed` and the process
exits 4. This mirrors Deepsec direct mode's fail-loud behavior and prevents a
broken reviewer from masquerading as a green "0 findings" gate.

Splitting exit 3 (environment/provider) from exit 4 (chunk failure) lets CI
alert differently: exit 3 means "fix your key/network and rerun"; exit 4 means
"the run hit transient or model-quality issues — rerun may succeed, or set
`--allow-partial` and inspect `chunk_failures`".

## 9. Testing

Three layers matching existing Pythinker convention:

**`tests/unit/`** — fake LLM returning canned JSON. Covers:

- Diff source resolution (range, working-tree, staged, base-ref fallback, empty
  diff, untracked files).
- Structured diff rendering with numbered `__new hunk__` / `__old hunk__`, added
  files, renamed files, pure deletions, and line-range validation.
- Context gathering budget behavior and bounded related-file snippets.
- Security signal scanner rules and prompt-anchor formatting.
- Chunker boundaries (per-file, per-hunk split, vendored skip, glob filters).
- Runner fail-closed behavior for timeouts, malformed output after retry, worker
  exceptions, and `--allow-partial` warnings.
- Dedupe rules (file/line/rule collision, severity tiebreak).
- Store atomicity (mid-write crash leaves no half-files).
- `gitignore.py` idempotency.
- SARIF schema shape, validated against the official SARIF 2.1.0 JSON Schema
  using `jsonschema` (already in `uv.lock` transitively; declared as a
  `pythinker-review` dev dependency, not a runtime one).
- Severity threshold gate (exit code for each `--fail-on` setting).

**`tests/e2e/`** — real CLI invocations against fixture git repos with planted
bugs/vulns. Still fake LLM (model selection injected via env var). Verifies exit
codes, file outputs, `--save` persistence, root `pythinker review/secscan`
wrappers, standalone `pythinker-review/pythinker-secscan`, and lazy CLI command
registration.

**`tests_ai/`** — small set of real-model runs on a curated diff fixture,
asserting recall on planted issues. Gated behind `PYTHINKER_AI_TESTS=1` so
default CI doesn't burn tokens.

Pythinker integration tests additionally cover:

- `src/pythinker_code/agents/default/agent.yaml` registers `code-reviewer` and
  `security-reviewer` without changing `review` / `verifier`.
- The new YAML files are included in PyInstaller/package data tests.
- `pythinker review diff` uses the active model adapter path, while standalone
  package tests do not import `pythinker_code`.

## 10. Rollout

Phase 1 is additive:

- No behavior change to existing `pythinker` commands.
- Add `packages/pythinker-review` to `[tool.uv.workspace].members` and
  `[tool.uv.sources]`.
- Add root dependency from `pythinker-code` to `pythinker-review` so lazy wrapper
  modules can import it.
- Add Make targets: `format/check/test/build-pythinker-review`, and include check
  / test / build in aggregate targets.
- Update `uv.lock` with `uv sync`; no unapproved new third-party runtime deps.
- Add root CLI wrappers and `_lazy_group.py` entries for `review` and `secscan`.
- Add `code_reviewer.yaml` / `security_reviewer.yaml` and register them in
  default `agent.yaml`.
- Update package/PyInstaller data inclusion tests for the new YAML files and any
  prompt/rule assets inside `pythinker-review`.
- AGENTS.md verification matrix gains one row for `packages/pythinker-review`.
- Existing `review` subagent role stays untouched. New roles use distinct
  identifiers (`code-reviewer`, `security-reviewer`).
- README's "What's New" gets a Phase 1 entry once shipped.

Allowed dependencies for Phase 1 are stdlib plus dependencies already present in
the workspace. Specifically: use `subprocess` instead of GitPython and a stdlib
sortable ID instead of `ulid-py`.

## 11. Phasing (forward look)

This spec only covers Phase 1. Subsequent phases each get their own spec:

- **Phase 2 — Local audit (clawpatch-style)**: semantic slicer for the whole
  repo, per-slice review, triage CLI (`pythinker review triage <id>`),
  regression diffing between runs.
- **Phase 3 — Deep security (deepsec-style)**: matcher plugin system, INFO.md
  project context authoring, FP-cutting revalidation pass, multi-machine worker
  fan-out.
- **Phase 4 — PR provider integrations**: vendor/adapt `blackbox/code-review`'s
  `git_providers/` concepts for GitHub / GitLab / Bitbucket / Azure DevOps; add
  `pythinker review pr <url|number>`; ship a GitHub Action.
- **Phase 5 — Fix loop**: `pythinker review fix --finding <id>` runs an isolated
  worktree, validates with configured commands, records a patch attempt. Never
  auto-applies.

Each phase builds on Phase 1's findings store, data model, structured diff
substrate, deterministic signal anchors, and Pythinker subagent roles.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM cost on large diffs | `--jobs` cap, per-chunk size limit, `--exclude`, hard-skip vendored/generated paths by default. Document recommended diff size. |
| False positives erode trust | Phase 1 ships `confidence` and `triage` fields; prompt says low-severity findings require high confidence; Phase 3 revalidation will reduce FP further. |
| False negatives from partial failures | Default fail-closed behavior exits 3 on any chunk failure; `--allow-partial` must be explicit and visibly warns. |
| Prompt regressions silently change output | `config_hash` includes reviewer prompts, rule list, and signal rules. CI `tests_ai/` recall checks on a fixed fixture catch large regressions. |
| SARIF tooling expects specific severities | Mapping documented; SARIF emitter is unit-tested against schema shape. |
| `.gitignore` patcher modifies user files unexpectedly | Only on first `--save`, only if file exists, only adds one line under a marker comment, only if not already present. Documented in README. |
| Active-model integration leaks into standalone package | `pythinker-review` accepts a `ReviewLLM` protocol; only `pythinker-code` builds the active Pythinker adapter. Standalone package tests assert no `pythinker_code` import is required. |
| Subagent registration expectations drift | Phase 1 uses current YAML registration. A separate future design is required for package-discovered subagents. |
| New dependency creep | Use stdlib for git and run IDs; any additional third-party runtime dependency requires explicit maintainer approval. |

## 13. Open questions

Implementation planning must choose exact numeric defaults, but the architectural
questions from the blackbox review are resolved above.

- Exact per-chunk token/character budget for default models.
- Exact list of Phase 1 security signal regexes and their confidence labels.
- Whether `--allow-partial` should be hidden/advanced or documented as a normal
  local-development escape hatch.
