from __future__ import annotations

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.style import Style as RichStyle
from rich.table import Table
from rich.text import Text

from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.ui.theme import tui_rich_style


def build_panel(report: UsageReport) -> Panel:
    return _build_usage_panel(report.summary, report.limits, notes=report.notes)


def _build_usage_panel(
    summary: UsageRow | None,
    limits: list[UsageRow],
    *,
    notes: list[str] | None = None,
) -> Panel:
    rows = ([summary] if summary else []) + limits
    if not rows and not notes:
        return Panel(
            Text("No usage data", style=tui_rich_style("muted")),
            title="API Usage",
            border_style=tui_rich_style("border_muted"),
            box=box.ROUNDED,
        )

    label_width = max((len(r.label) for r in rows), default=6)
    label_width = max(label_width, 6)

    lines: list[RenderableType] = []
    for row in rows:
        lines.append(_format_row(row, label_width))
    for note in notes or []:
        lines.append(Text(note, style=tui_rich_style("warning")))

    return Panel(
        Group(*lines),
        title="API Usage",
        border_style=tui_rich_style("border_muted"),
        box=box.ROUNDED,
        padding=(0, 2),
        expand=False,
    )


def _format_row(row: UsageRow, label_width: int) -> RenderableType:
    if row.limit <= 0 and row.unit is not None:
        return _format_unbounded_row(row, label_width)
    if row.unit == "%":
        return _format_percent_row(row, label_width)

    remaining, remaining_ratio, bar_total = _remaining_quota(row)
    color = _ratio_color(remaining_ratio)

    label = Text(f"{row.label:<{label_width}}  ", style=tui_rich_style("info"))
    bar = ProgressBar(
        total=bar_total,
        completed=remaining,
        width=20,
        complete_style=color,
        finished_style=color,
    )

    detail = Text()
    percent = remaining_ratio * 100
    detail.append(f"  {percent:.0f}% left", style="bold")
    if row.reset_hint:
        detail.append(f"  ({row.reset_hint})", style=tui_rich_style("muted"))

    return _row_table(label_width, label, bar, detail)


def _format_percent_row(row: UsageRow, label_width: int) -> RenderableType:
    percent_left = min(max(row.used, 0), 100)
    color = _ratio_color(percent_left / 100)
    label = Text(f"{row.label:<{label_width}}  ", style=tui_rich_style("info"))
    bar = ProgressBar(
        total=100,
        completed=percent_left,
        width=20,
        complete_style=color,
        finished_style=color,
    )
    detail = Text(f"  {_format_value(percent_left, row.unit)} left", style="bold")
    if row.reset_hint:
        detail.append(f"  ({row.reset_hint})", style=tui_rich_style("muted"))
    return _row_table(label_width, label, bar, detail)


def _format_unbounded_row(row: UsageRow, label_width: int) -> RenderableType:
    label = Text(f"{row.label:<{label_width}}  ", style=tui_rich_style("info"))
    detail = Text(f"  {_format_value(row.used, row.unit)} used", style="bold")
    if row.reset_hint:
        detail.append(f"  ({row.reset_hint})", style=tui_rich_style("muted"))
    t = Table.grid(padding=0)
    t.add_column(width=label_width + 2)
    t.add_column()
    t.add_row(label, detail)
    return t


def _row_table(
    label_width: int,
    label: Text,
    bar: ProgressBar,
    detail: Text,
) -> Table:
    t = Table.grid(padding=0)
    t.add_column(width=label_width + 2)
    t.add_column(width=20)
    t.add_column()
    t.add_row(label, bar, detail)
    return t


def _remaining_quota(row: UsageRow) -> tuple[int, float, int]:
    if row.limit <= 0:
        return 0, 0, 1

    remaining = min(max(row.limit - row.used, 0), row.limit)
    return remaining, remaining / row.limit, row.limit


def _ratio_color(remaining_ratio: float) -> RichStyle:
    if remaining_ratio <= 0.1:
        return tui_rich_style("error")
    if remaining_ratio <= 0.3:
        return tui_rich_style("warning")
    return tui_rich_style("success")


def _format_value(value: int, unit: str | None) -> str:
    if unit is None:
        return _format_count(value)
    if unit == "%":
        return f"{value}%"
    if unit == "USD":
        return f"${value / 100:.2f}"
    if unit == "CNY":
        return f"¥{value / 100:.2f}"
    return f"{_format_count(value)} {unit}"


def _format_count(value: int) -> str:
    return f"{value:,}"


format_row = _format_row
remaining_quota = _remaining_quota
ratio_color = _ratio_color
