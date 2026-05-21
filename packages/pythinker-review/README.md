# pythinker-review

Agent-first code review, security review, and root-cause debugging engine for Pythinker. Standalone
CLI (`pythinker-review`, `pythinker-secscan`, `pythinker-security-scan`, `pythinker-debug`) and integration into
`pythinker-code` as the `review` / `secscan` / `security-scan` / `debug` subcommands and the
`code-reviewer` / `security-reviewer` / `debugger` subagent roles.

## CLI

```bash
# Branch-vs-main code review
pythinker-review diff --base origin/main --format pretty

# Branch-vs-main code + security in one pass
pythinker-review diff --with-security --fail-on high

# Read-only Reviewflow-style deslopify review
pythinker-review diff --mode deslopify --fail-on none

# Inspect saved diff findings by priority
pythinker-review next
pythinker-review show-finding <finding-id>

# Stateful pure-Python Reviewflow workflow
pythinker-review init
pythinker-review map
pythinker-review review --limit 3 --jobs 3
pythinker-review report --status open
pythinker-review show --finding <finding-id>
pythinker-review triage --finding <finding-id> --status false-positive
pythinker-review fix --finding <finding-id>          # explicit mutating patch attempt
pythinker-review open-pr --patch <patchAttemptId> --dry-run
pythinker-review revalidate --finding <finding-id>

# Code-reviewr-derived read-only PR assistant artifacts
pythinker-review describe --base origin/main --format json
pythinker-review improve --base origin/main --format pretty   # alias: suggest
pythinker-review ask "what changed and what should I test?" --base origin/main
pythinker-review labels --base origin/main
pythinker-review changelog --base origin/main
pythinker-review docs --base origin/main
pythinker-review compliance --base origin/main --ticket-file issue.md

# Security-only scan, SARIF for CI
pythinker-secscan diff --format sarif --fail-on critical

# Repo-wide Pythinker Security Scan pipeline (pure Python runtime)
pythinker-security-scan init --root .
pythinker-security-scan scan --json
pythinker-security-scan process --limit 10
pythinker-security-scan report --write

# Root-cause debugger over a captured failure log
pythinker-debug failure failure.log --command "pytest tests/test_app.py::test_case"
```

## Configuration

`pythinker-review`, `pythinker-secscan`, and `pythinker-security-scan` accept explicit/env model configuration. When invoked via
`pythinker review` / `pythinker secscan` / `pythinker security-scan` / `pythinker debug`, the active Pythinker model is wired in
automatically through a `ReviewLLM` adapter.

## Persistence

Each diff `--save` run writes:

```text
.pythinker-review/
├── index.json
└── runs/
    └── 20260520120000-a1b2c3d4/
        ├── meta.json
        ├── findings.jsonl
        └── diff.patch
```

The stateful Reviewflow workflow writes `.pythinker-review-flow/` by default:

```text
.pythinker-review-flow/
  config.json
  project.json
  features/*.json
  findings/*.json
  patches/*.json
  reports/*.md
  runs/*.json
  locks/*.json
```

`.gitignore` is auto-patched idempotently on first diff save if a `.gitignore` file already exists.

## Blackbox parity hardening

Phase 1 now ports the highest-value behavior from the mounted blackbox repos:

- Reviewflow-style evidence validation rejects findings outside the reviewed chunk/feature, unsafe
  paths, stale line ranges, or non-matching evidence snippets.
- Reviewflow pure-Python stateful commands cover `init`, `map`, `status`, `review`, `ci`,
  `report`, `show --finding`, `next`, `triage`, `revalidate`, `fix`, `open-pr`, `doctor`, and
  `clean-locks`.
- Code-review prompt parity covers partial-diff caveats, concrete trigger scenarios, test analysis,
  suggested regression tests, and minimum fix scope.
- Code-reviewr PR assistant parity adds read-only `describe`, `improve`/`suggest`, `ask`,
  `labels`, `changelog`, and `docs` artifact commands with strict JSON schemas.
- Pythinker Security Scan deterministic signals include CWE/severity hints, expanded vulnerability anchors,
  technology detection, and batch-scoped security advisor context.
- Python-native Pythinker Security Scan repo-wide commands (`pythinker-security-scan` / `pythinker security-scan`) port the
  scan/process/revalidate/triage/report/export/status workflow without Node or pnpm runtime glue.
- Fenced/prose-wrapped JSON is cleaned safely, while truly malformed output remains fail-closed.

## Phase 1

See `docs/superpowers/specs/2026-05-20-pythinker-review-foundation-design.md` for the full spec.
Future phases deepen mapper parity, external matcher plugin marketplaces, and PR-provider comment
publishing integrations.
