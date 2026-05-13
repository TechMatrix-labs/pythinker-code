from __future__ import annotations

from pathlib import Path

from pythinker_code.tools.plan.handoff import (
    build_implementation_handoff,
    handoff_path_for_plan,
    persist_implementation_handoff,
)


def test_build_implementation_handoff_includes_plan_and_selected_option() -> None:
    handoff = build_implementation_handoff(
        "# Plan\n\n- Change one file\n- Run tests",
        selected_option="Small slice",
    )

    assert handoff.startswith("# Implementation Handoff")
    assert "Small slice" in handoff
    assert "# Plan" in handoff
    assert "Run tests" in handoff


def test_persist_implementation_handoff_writes_sibling_artifact(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan", encoding="utf-8")

    handoff_path, handoff = persist_implementation_handoff(plan_path, "# Plan")

    assert handoff_path == handoff_path_for_plan(plan_path)
    assert handoff_path.name == "plan.handoff.md"
    assert handoff_path.read_text(encoding="utf-8") == handoff
    assert "Implementation Handoff" in handoff


def test_build_implementation_handoff_truncates_large_plans() -> None:
    handoff = build_implementation_handoff("x" * 20_000)

    assert "Plan truncated for handoff" in handoff
    assert len(handoff) < 13_000
