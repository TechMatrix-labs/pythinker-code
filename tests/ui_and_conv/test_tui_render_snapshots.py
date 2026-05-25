"""Snapshot-style tests for ToolExecutionComponent."""

from __future__ import annotations

import pytest
from rich.console import Console, Group, RenderableType
from rich.text import Text

from pythinker_code.ui.shell.components import (
    ToolExecutionComponent,
    ToolExecutionStatus,
    render_plain,
)
from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
    clear_tool_renderers,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    clear_tool_renderers()
    yield
    clear_tool_renderers()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_renderer() -> ToolRenderDefinition:
    """A small ReadFile-shaped renderer used across these tests."""

    def render_call(ctx: ToolRenderContext) -> RenderableType:
        path = ctx.args.get("path", "?")
        head = Text("read ", style="bold")
        head.append(str(path), style="grey70")
        return head

    def render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
        if not result.text:
            return None
        line_count = result.text.count("\n") + 1
        suffix = "lines" if line_count > 1 else "line"
        text = Text()
        text.append("✓ ", style="green")
        text.append(f"{line_count} {suffix}", style="grey70")
        return Group(text, Text(result.text, style="grey50"))

    return ToolRenderDefinition(
        name="ReadFile",
        label="Read",
        render_call=render_call,
        render_result=render_result,
    )


def _ansi(renderable: RenderableType, *, width: int = 60) -> str:
    """Render *renderable* keeping ANSI escapes — used to assert bg colors."""
    console = Console(
        width=width,
        record=True,
        force_terminal=True,
        color_system="truecolor",
        legacy_windows=False,
    )
    console.print(renderable)
    return console.export_text(styles=True)


# ---------------------------------------------------------------------------
# Status -> background color
# ---------------------------------------------------------------------------


def test_pending_card_renders_without_background_tint():
    comp = ToolExecutionComponent(
        "ReadFile",
        "t1",
        definition=_read_renderer(),
    )
    comp.update_args({"path": "src/foo.py"})

    assert comp.status == ToolExecutionStatus.PENDING
    text = render_plain(comp.render(), width=60)
    assert "read" in text
    assert "src/foo.py" in text

    coloured = _ansi(comp.render(), width=60)
    # Blackbox-style pending/running tool rows sit on the terminal background.
    assert "48;2;27;34;48" not in coloured


def test_success_card_renders_compact_without_success_bg():
    comp = ToolExecutionComponent(
        "ReadFile",
        "t1",
        definition=_read_renderer(),
    )
    comp.update_args({"path": "src/foo.py"})
    comp.mark_execution_started()
    comp.set_result(ToolResultPayload(text="hello\nworld"))

    assert comp.status == ToolExecutionStatus.SUCCESS
    coloured = _ansi(comp.render(), width=60)
    # Compact cards no longer paint a full success background.
    assert "48;2;22;39;28" not in coloured

    text = render_plain(comp.render(), width=60)
    assert "2 lines" in text


def test_error_card_uses_tool_error_bg():
    comp = ToolExecutionComponent(
        "ReadFile",
        "t1",
        definition=_read_renderer(),
    )
    comp.update_args({"path": "missing.py"})
    comp.set_result(ToolResultPayload(text="ENOENT", is_error=True))

    assert comp.status == ToolExecutionStatus.ERROR
    coloured = _ansi(comp.render(), width=60)
    # Default dark theme tool_error_bg = #2E1D24 -> rgb(46,29,36).
    assert "48;2;46;29;36" in coloured


def test_denied_card_uses_error_bg():
    comp = ToolExecutionComponent(
        "ReadFile",
        "t1",
        definition=_read_renderer(),
    )
    comp.set_status(ToolExecutionStatus.DENIED)
    coloured = _ansi(comp.render(), width=60)
    # Denied also uses error background.
    assert "48;2;46;29;36" in coloured


# ---------------------------------------------------------------------------
# Hide-when-empty behavior
# ---------------------------------------------------------------------------


def test_no_content_renders_blank_text():
    """Renderer produces nothing → Pythinker's hidden-component equivalent."""

    def render_call(_ctx: ToolRenderContext) -> RenderableType | None:
        return None

    defn = ToolRenderDefinition(
        name="Quiet",
        label="Quiet",
        render_call=render_call,
    )
    comp = ToolExecutionComponent("Quiet", "t1", definition=defn)
    out = comp.render()
    assert isinstance(out, Text)
    assert out.plain == ""


def test_call_renderer_crash_falls_back_to_label():
    def render_call(_ctx: ToolRenderContext) -> RenderableType:
        raise RuntimeError("renderer broke")

    defn = ToolRenderDefinition(
        name="Crashy",
        label="CrashyTool",
        render_call=render_call,
    )
    comp = ToolExecutionComponent("Crashy", "t1", definition=defn)
    rendered = render_plain(comp.render(), width=40)
    assert "CrashyTool" in rendered


def test_result_renderer_crash_falls_back_to_text():
    defn = _read_renderer()

    def render_result(_ctx: ToolRenderContext, _r: ToolResultPayload) -> RenderableType:
        raise RuntimeError("result broke")

    crashy = ToolRenderDefinition(
        name=defn.name,
        label=defn.label,
        render_call=defn.render_call,
        render_result=render_result,
    )
    comp = ToolExecutionComponent("ReadFile", "t1", definition=crashy)
    comp.update_args({"path": "x"})
    comp.set_result(ToolResultPayload(text="payload-body"))
    rendered = render_plain(comp.render(), width=40)
    assert "payload-body" in rendered


# ---------------------------------------------------------------------------
# Expand / collapse
# ---------------------------------------------------------------------------


def test_long_result_shows_expand_hint_when_collapsed():
    comp = ToolExecutionComponent("ReadFile", "t1", definition=_read_renderer())
    comp.update_args({"path": "big.py"})
    long_text = "\n".join(f"line {i}" for i in range(50))
    comp.set_result(ToolResultPayload(text=long_text))
    rendered = render_plain(comp.render(), width=60)
    assert "ctrl+o" in rendered
    assert "expand" in rendered


def test_long_result_hides_expand_hint_when_expanded():
    comp = ToolExecutionComponent("ReadFile", "t1", definition=_read_renderer())
    comp.update_args({"path": "big.py"})
    long_text = "\n".join(f"line {i}" for i in range(50))
    comp.set_result(ToolResultPayload(text=long_text))
    comp.set_expanded(True)
    rendered = render_plain(comp.render(), width=60)
    assert "ctrl+o" not in rendered


def test_short_result_does_not_show_expand_hint():
    comp = ToolExecutionComponent("ReadFile", "t1", definition=_read_renderer())
    comp.update_args({"path": "a.py"})
    comp.set_result(ToolResultPayload(text="ok"))
    rendered = render_plain(comp.render(), width=60)
    assert "ctrl+o" not in rendered


# ---------------------------------------------------------------------------
# render_shell="self" skips the bg padding
# ---------------------------------------------------------------------------


def test_self_shell_skips_padding():
    def render_call(_ctx: ToolRenderContext) -> RenderableType:
        return Text("self-rendered", style="bold")

    defn = ToolRenderDefinition(
        name="Self",
        label="Self",
        render_shell="self",
        render_call=render_call,
    )
    comp = ToolExecutionComponent("Self", "t1", definition=defn)
    coloured = _ansi(comp.render(), width=40)
    # No tool_pending_bg fill should be applied when render_shell == "self".
    assert "48;2;27;34;48" not in coloured


# ---------------------------------------------------------------------------
# Width-narrow stability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", [40, 80, 120])
def test_renders_at_multiple_widths(width: int):
    comp = ToolExecutionComponent("ReadFile", "t1", definition=_read_renderer())
    comp.update_args({"path": "a/b/c/d/e/f/g.py"})
    comp.set_result(ToolResultPayload(text="hello\nworld"))
    rendered = render_plain(comp.render(width), width=width)
    assert "read" in rendered
    # Render should not raise for any reasonable width.
    assert rendered.strip() != ""
