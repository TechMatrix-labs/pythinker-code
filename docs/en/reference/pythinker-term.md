# `pythinker term` Subcommand

The `pythinker term` command launches the [Toad](https://github.com/batrachianai/toad) terminal UI, a modern terminal interface built with [Textual](https://textual.textualize.io/).

```sh
pythinker term [OPTIONS]
```

## Description

[Toad](https://github.com/batrachianai/toad) is a graphical terminal interface for Pythinker Code that communicates with the Pythinker Code backend via the ACP protocol. It provides a richer interactive experience with better output rendering and layout.

When you run `pythinker term`, it automatically starts a `pythinker acp` server in the background, and Toad connects to it as an ACP client.

## Options

All extra options are passed through to the internal `pythinker acp` command. For example:

```sh
pythinker term --work-dir /path/to/project --model pythinker-ai
```

Common options:

| Option | Description |
|--------|-------------|
| `--work-dir PATH` | Specify working directory |
| `--model NAME` | Specify model |
| `--yolo` | Auto-approve all tool calls |

For the full list of options, see [`pythinker` command](./pythinker-command.md).

## System requirements

::: warning Note
`pythinker term` requires Python 3.14+. If you installed Pythinker Code with an older Python version, you need to reinstall with Python 3.14:

```sh
uv tool install --python 3.14 pythinker-code
```
:::
