from rich.console import Console

from pythinker_code.ui import shell as shell_module


def test_shell_welcome_uses_pythinker_code_copy(monkeypatch):
    console = Console(record=True, width=120, color_system=None)
    monkeypatch.setattr(shell_module, "console", console)
    monkeypatch.setattr(shell_module, "get_version", lambda: "9.9.9")

    shell_module._print_welcome_info("Pythinker Code", [])

    output = console.export_text()
    assert "Pythinker Code v9.9.9" in output
    assert "Welcome to Pythinker Code!" in output
    assert "Welcome to Pythinker CLI!" not in output
