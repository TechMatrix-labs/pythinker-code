# Pythinker CLI Tools

## Guidelines

- Tools should not refer to types in `pythinker_code/wire/` unless they are explicitly implementing a UI / runtime bridge. When importing things like `ToolReturnValue` or `DisplayBlock`, prefer `pythinker_core.tooling`.
- Current bridge exceptions include `ask_user`, `plan`, and `file` media/display helpers; keep new tool logic in `pythinker_core.tooling` unless it must emit wire-facing requests or display blocks.
