# Changelog

## 1.0.0 (2026-05-06)

Initial release of Pythinker CLI.

- Interactive terminal AI coding agent with shell command mode (Ctrl-X)
- ACP server (`pythinker acp`) for IDE integrations such as Zed and JetBrains
- MCP tool support: `pythinker mcp` sub-commands and ad-hoc `--mcp-config-file`
- Multi-provider auth: OpenAI, OpenAI Codex, Anthropic, OpenRouter, DeepSeek, MiniMax, Opencode-Go
- Skills, plugins, and slash commands across project / user / built-in scopes
- Session persistence with subagents and approval workflows
- Print mode and wire mode for non-interactive and programmatic use
- Plan mode for read-only research and design before code changes
- YOLO mode (`--yolo` / `/yolo`) to dangerously skip permission approvals while keeping the user reachable via `AskUserQuestion`
- Auto mode (`--auto` / `/auto`) for unattended runs: auto-approves tool calls and auto-dismisses `AskUserQuestion` so the agent finishes end-to-end without a user
