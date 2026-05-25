from rich.console import Console

from pythinker_code.ui import shell as shell_module


def test_shell_welcome_uses_pythinker_code_copy(monkeypatch):
    console = Console(record=True, width=120, color_system=None)
    monkeypatch.setattr(shell_module, "console", console)
    monkeypatch.setattr(shell_module, "get_version", lambda: "9.9.9")

    shell_module._print_welcome_info("Pythinker Code", [])

    output = console.export_text()
    assert "Pythinker Code v9.9.9" in output
    assert "Welcome to Pythinker" in output
    assert "think first" in output


def test_directory_label_uses_brand_info_token():
    from pythinker_code.ui.shell import WelcomeInfoItem, _value_style_for_label
    from pythinker_code.ui.theme import get_tui_tokens, set_active_theme

    set_active_theme("dark")
    style = _value_style_for_label("Directory", WelcomeInfoItem.Level.INFO)
    assert get_tui_tokens("dark").info in style  # "#AFE3F1"
