# Getting Started

## What is Pythinker Code

Pythinker Code is an AI agent that runs in the terminal, helping you complete software development tasks and terminal operations. It can read and edit code, execute shell commands, search and fetch web pages, and autonomously plan and adjust actions during execution.

Pythinker Code is suited for:

- **Writing and modifying code**: Implementing new features, fixing bugs, refactoring code
- **Understanding projects**: Exploring unfamiliar codebases, answering architecture and implementation questions
- **Automating tasks**: Batch processing files, running builds and tests, executing scripts

Pythinker Code supports the following usage modes:

- **[Interactive CLI (`pythinker`)](../reference/pythinker-command.md)**: Chat with AI in the terminal using natural language or execute shell commands directly
- **[Browser UI (`pythinker web`)](../reference/pythinker-web.md)**: Open a graphical interface in your local browser, with session management, file references, code highlighting, and more
- **[Agent integration (`pythinker acp`)](../reference/pythinker-acp.md)**: Run as a service and integrate with [IDEs](./ides.md) and other local agent clients via the [Agent Client Protocol]

::: info Tip
If you encounter issues or have suggestions, please provide feedback on [GitHub Issues](https://github.com/mohamed-elkholy95/Pythinker-Code/issues).
:::

[Agent Client Protocol]: https://agentclientprotocol.com/

## Installation

Run the installation script to complete the installation. The script will first install [uv](https://docs.astral.sh/uv/) (a Python package manager), then install Pythinker Code via uv:

```sh
# Linux / macOS
curl -LsSf https://code.pythinker.com/install.sh | bash
```

```powershell
# Windows (PowerShell)
Invoke-RestMethod https://code.pythinker.com/install.ps1 | Invoke-Expression
```

Verify the installation:

```sh
pythinker --version
```

::: tip
Due to macOS security checks, the first run of the `pythinker` command may take longer. You can add your terminal application in "System Settings → Privacy & Security → Developer Tools" to speed up subsequent launches.
:::

If you already have uv installed, you can also run:

```sh
uv tool install --python 3.13 pythinker-code
```

::: tip
Pythinker Code supports Python 3.12–3.14, with Python 3.13 recommended.
:::

## Upgrade and uninstall

Upgrade to the latest version:

```sh
uv tool upgrade pythinker-code --no-cache
```

Uninstall Pythinker Code:

```sh
uv tool uninstall pythinker-code
```

## First run

Run the `pythinker` command in the project directory where you want to work to start Pythinker Code:

```sh
cd your-project
pythinker
```

On first launch, you need to configure your API source. Enter the `/login` command to start configuration:

```
/login
```

After execution, first select a platform. We recommend **Pythinker**, which automatically opens a browser for OAuth authorization; selecting other platforms requires entering an API key. After configuration, Pythinker Code will automatically save the settings and reload. See [Providers](../configuration/providers.md) for details.

Now you can chat with Pythinker Code directly using natural language. Try describing a task you want to complete, for example:

```
Show me the directory structure of this project
```

::: tip
If the project doesn't have an `AGENTS.md` file, you can run the `/init` command to have Pythinker Code analyze the project and generate this file, helping the AI better understand the project structure and conventions.
:::

Enter `/help` to view all available [slash commands](../reference/slash-commands.md) and usage tips.
