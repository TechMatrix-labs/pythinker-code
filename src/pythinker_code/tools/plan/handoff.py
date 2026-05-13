from __future__ import annotations

from pathlib import Path

MAX_HANDOFF_CHARS = 12_000


def build_implementation_handoff(
    plan_content: str,
    *,
    selected_option: str | None = None,
) -> str:
    """Build a compact implementation handoff from an approved plan.

    The handoff is deterministic and local: plan approval should never require
    another LLM call, and handoff generation must be safe to use in auto mode.
    """
    normalized = "\n".join(line.rstrip() for line in plan_content.strip().splitlines()).strip()
    if not normalized:
        normalized = "(Approved plan was empty.)"
    if len(normalized) > MAX_HANDOFF_CHARS:
        normalized = (
            normalized[:MAX_HANDOFF_CHARS].rstrip()
            + "\n\n[Plan truncated for handoff; read the saved plan file for full details.]"
        )

    lines = [
        "# Implementation Handoff",
        "",
        "Use this handoff to continue in the current session or start an implementer/coder "
        "subagent without losing the approved plan context.",
        "",
    ]
    if selected_option:
        lines.extend(["## Selected approach", "", selected_option.strip(), ""])
    lines.extend(
        [
            "## Execution guidance",
            "",
            "- Treat the approved plan below as the source of truth.",
            "- Keep changes surgical and verify with the smallest relevant tests first.",
            "- If starting a subagent, pass this whole handoff as the prompt context.",
            "",
            "## Approved plan",
            "",
            normalized,
            "",
        ]
    )
    return "\n".join(lines)


def handoff_path_for_plan(plan_path: Path) -> Path:
    """Return the sibling handoff artifact path for a plan file."""
    return plan_path.with_suffix(".handoff.md")


def persist_implementation_handoff(
    plan_path: Path,
    plan_content: str,
    *,
    selected_option: str | None = None,
) -> tuple[Path, str]:
    """Persist an implementation handoff next to the approved plan artifact."""
    handoff = build_implementation_handoff(plan_content, selected_option=selected_option)
    target = handoff_path_for_plan(plan_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(handoff, encoding="utf-8")
    return target, handoff
