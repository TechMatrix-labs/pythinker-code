# Data Locations

Pythinker Code stores all data in the `~/.pythinker/` directory under the user's home directory. This page describes the locations and purposes of various data files.

::: tip
You can customize the share directory path by setting the `PYTHINKER_SHARE_DIR` environment variable. See [Environment Variables](./env-vars.md#pythinker-share-dir) for details.

Note: `PYTHINKER_SHARE_DIR` only affects the storage location of the runtime data listed above, not the [Agent Skills](../customization/skills.md) search paths. Skills, as cross-tool shared capability extensions, are a different type of data from application runtime data.
:::

## Directory structure

```
~/.pythinker/
├── config.toml           # Main configuration file
├── pythinker.json             # Metadata
├── mcp.json              # MCP server configuration
├── credentials/          # OAuth credentials
│   └── <provider>.json
├── sessions/             # Session data
│   └── <work-dir-hash>/
│       └── <session-id>/
│           ├── context.jsonl
│           ├── wire.jsonl
│           └── state.json
├── imported_sessions/    # Imported session data (via pythinker vis)
│   └── <session-id>/
│       ├── context.jsonl
│       ├── wire.jsonl
│       └── state.json
├── plans/                # Plan mode plan files
│   └── <slug>.md
├── user-history/         # Input history
│   └── <work-dir-hash>.jsonl
└── logs/                 # Logs
    └── pythinker.log
```

## Configuration and metadata

### `config.toml`

Main configuration file, stores providers, models, services, and runtime parameters. See [Config Files](./config-files.md) for details.

You can specify a configuration file at a different location with the `--config-file` flag.

### `pythinker.json`

Metadata file, stores Pythinker Code's runtime state, including:

- `work_dirs`: List of working directories and their last used session IDs
- `thinking`: Whether thinking mode was enabled in the last session

This file is automatically managed by Pythinker Code and typically doesn't need manual editing.

### `mcp.json`

MCP server configuration file, stores MCP servers added via the `pythinker mcp add` command. See [MCP](../customization/mcp.md) for details.

Example structure:

```json
{
  "mcpServers": {
    "context7": {
      "url": "https://mcp.context7.com/mcp",
      "transport": "http",
      "headers": {
        "CONTEXT7_API_KEY": "ctx7sk-xxx"
      }
    }
  }
}
```

## Credentials

OAuth credentials are stored in the `~/.pythinker/credentials/` directory. After logging in to your Pythinker account via `/login`, OAuth tokens are saved in this directory.

Files in this directory have permissions set to read/write for the current user only (600) to protect sensitive information.

## Session data

Session data is grouped by working directory and stored under `~/.pythinker/sessions/`. Each working directory corresponds to a subdirectory named with the path's MD5 hash, and each session corresponds to a subdirectory named with the session ID.

### `context.jsonl`

Context history file, stores the session's full context in JSON Lines (JSONL) format. The first line is a system prompt record (`_system_prompt`), followed by messages (user input, model response, tool calls, etc.) and internal records (checkpoints, token usage, etc.).

The system prompt is generated and frozen at session creation time, and reused on session restore instead of being regenerated.

Pythinker Code uses this file to restore session context when using `--continue` or `--session`.

### `wire.jsonl`

Wire message log file, stores Wire events during the session in JSON Lines (JSONL) format. Used for session replay and extracting session titles.

### `state.json`

Session state file, stores the session's runtime state, including:

- `title`: User-set session title
- `approval`: Approval decision state (YOLO and auto mode on/off, auto-approved operation types)
- `plan_mode`: Plan mode on/off status
- `plan_session_id`: Unique identifier for the current plan session, used to associate the plan file
- `plan_slug`: The file path identifier for the plan (the slug in `~/.pythinker/plans/<slug>.md`), preserved so restarts resume the same file
- `subagent_instances`: Subagent instance state and metadata
- `additional_dirs`: Additional workspace directories added via `--add-dir` or `/add-dir`

When resuming a session, Pythinker Code reads this file to restore the session state. This file uses atomic writes to prevent data corruption on crash.

### `subagents/<agent_id>/`

Each subagent instance created via the `Agent` tool has its own storage directory under the session directory, containing:

- `context.jsonl`: Subagent conversation history
- `wire.jsonl`: Subagent Wire event log
- `meta.json`: Instance metadata (status, type, creation time, etc.)
- `prompt.txt`: Last executed prompt
- `output`: Execution output

When resuming a session, subagent instance context and state are automatically restored, allowing continuation via the `resume` parameter.

## Plan files

Plan mode plan files are stored in the `~/.pythinker/plans/` directory. Each plan session corresponds to a randomly named Markdown file (e.g. `<slug>.md`).

The `plan_slug` is saved in `state.json`, so the same plan file is resumed after a process restart. Use `/plan clear` to delete the current plan session's file.

## Input history

User input history is stored in the `~/.pythinker/user-history/` directory. Each working directory corresponds to a `.jsonl` file named with the path's MD5 hash.

Input history is used for history browsing (up/down arrow keys) and search (Ctrl-R) in shell mode.

## Logs

Runtime logs are stored in `~/.pythinker/logs/pythinker.log`. Default log level is INFO, use the `--debug` flag to enable TRACE level.

Log files are used for troubleshooting. When reporting bugs, please include relevant log content.

## Cleaning data

Deleting the share directory (default `~/.pythinker/`, or the path specified by `PYTHINKER_SHARE_DIR`) completely clears all Pythinker Code data, including configuration, sessions, and history.

To clean only specific data:

| Need | Action |
| --- | --- |
| Reset configuration | Delete `~/.pythinker/config.toml` |
| Clear all sessions | Delete `~/.pythinker/sessions/` directory |
| Clear sessions for specific working directory | Use `/sessions` in shell mode to view and delete |
| Clear plan files | Delete `~/.pythinker/plans/` directory, or use `/plan clear` in plan mode |
| Clear input history | Delete `~/.pythinker/user-history/` directory |
| Clear logs | Delete `~/.pythinker/logs/` directory |
| Clear MCP configuration | Delete `~/.pythinker/mcp.json` or use `pythinker mcp remove` |
| Clear login credentials | Delete `~/.pythinker/credentials/` directory or use `/logout` |
