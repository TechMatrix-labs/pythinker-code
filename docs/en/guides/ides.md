# Using in IDEs

Pythinker Code supports integration with IDEs through the [Agent Client Protocol (ACP)](https://agentclientprotocol.com/), allowing you to use AI-assisted programming directly within your editor.

## Prerequisites

Before configuring your IDE, make sure you have installed Pythinker Code and completed the `/login` configuration.

## Using in Zed

[Zed](https://zed.dev/) is a modern IDE that supports ACP.

Add the following to Zed's configuration file `~/.config/zed/settings.json`:

```json
{
  "agent_servers": {
    "Pythinker Code": {
      "type": "custom",
      "command": "pythinker",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

Configuration notes:

- `type`: Fixed value `"custom"`
- `command`: Path to the Pythinker Code command. If `pythinker` is not in PATH, use the full path
- `args`: Startup arguments. `acp` enables ACP mode
- `env`: Environment variables, usually left empty

After saving the configuration, you can create Pythinker Code sessions in Zed's Agent panel.

## Using in JetBrains IDEs

JetBrains IDEs (IntelliJ IDEA, PyCharm, WebStorm, etc.) support ACP through the AI Chat plugin.

If you don't have a JetBrains AI subscription, you can enable `llm.enable.mock.response` in the Registry to use the AI Chat feature. Press Shift twice to search for "Registry" to open it.

In the AI Chat panel menu, click "Configure ACP agents" and add the following configuration:

```json
{
  "agent_servers": {
    "Pythinker Code": {
      "command": "~/.local/bin/pythinker",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

`command` needs to be the full path. You can run `which pythinker` in the terminal to get it. After saving, you can select Pythinker Code in the AI Chat Agent selector.
