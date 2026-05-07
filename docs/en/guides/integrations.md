# Integrations with Tools

Besides using in the terminal and IDEs, Pythinker Code can also be integrated with other tools.

## Zsh plugin

[zsh-pythinker-code](https://github.com/mohamed-elkholy95/zsh-pythinker-code) is a Zsh plugin that lets you quickly switch to Pythinker Code in Zsh.

**Installation**

If you use Oh My Zsh, you can install it like this:

```sh
git clone https://github.com/mohamed-elkholy95/zsh-pythinker-code.git \
  ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/pythinker-code
```

Then add the plugin in `~/.zshrc`:

```sh
plugins=(... pythinker-code)
```

Reload the Zsh configuration:

```sh
source ~/.zshrc
```

**Usage**

After installation, press `Ctrl-X` in Zsh to quickly switch to Pythinker Code without manually typing the `pythinker` command.

::: tip
If you use other Zsh plugin managers (like zinit, zplug, etc.), please refer to the [zsh-pythinker-code repository](https://github.com/mohamed-elkholy95/zsh-pythinker-code) README for installation instructions.
:::
