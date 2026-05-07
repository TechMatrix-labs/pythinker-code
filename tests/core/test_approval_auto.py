"""Tests for Approval's yolo / auto orthogonal state model."""

from __future__ import annotations

from pythinker_code.soul.approval import Approval, ApprovalState


def test_yolo_only() -> None:
    approval = Approval(yolo=True)
    assert approval.is_yolo() is True
    assert approval.is_yolo_flag() is True
    assert approval.is_auto_approve() is True
    assert approval.is_auto() is False


def test_auto_only() -> None:
    state = ApprovalState(yolo=False, auto=True)
    approval = Approval(state=state)
    assert approval.is_auto_approve() is True
    assert approval.is_yolo() is False
    assert approval.is_yolo_flag() is False  # explicit flag only
    assert approval.is_auto() is True
    assert approval.is_auto_flag() is True


def test_yolo_and_auto() -> None:
    state = ApprovalState(yolo=True, auto=True)
    approval = Approval(state=state)
    assert approval.is_yolo() is True
    assert approval.is_auto_approve() is True
    assert approval.is_auto() is True


def test_neither_flag_set() -> None:
    approval = Approval(yolo=False)
    assert approval.is_yolo() is False
    assert approval.is_auto_approve() is False
    assert approval.is_auto() is False


def test_runtime_auto_only() -> None:
    state = ApprovalState(yolo=False, auto=False, runtime_auto=True)
    approval = Approval(state=state)
    assert approval.is_auto_approve() is True
    assert approval.is_yolo() is False
    assert approval.is_auto() is True
    assert approval.is_auto_flag() is False
    assert approval.is_runtime_auto() is True


def test_set_runtime_auto_does_not_trigger_on_change() -> None:
    fired: list[bool] = []
    state = ApprovalState(on_change=lambda: fired.append(True))
    approval = Approval(state=state)
    approval.set_runtime_auto(True)
    assert approval.is_auto() is True
    assert approval.is_auto_flag() is False
    assert fired == []


def test_set_yolo_does_not_touch_auto() -> None:
    state = ApprovalState(yolo=False, auto=True)
    approval = Approval(state=state)
    approval.set_yolo(True)
    assert approval.is_auto() is True
    assert approval.is_yolo() is True
    assert approval.is_auto_approve() is True
    approval.set_yolo(False)
    # Auto keeps auto-approve on even after the explicit yolo flag is cleared.
    assert approval.is_auto() is True
    assert approval.is_yolo() is False
    assert approval.is_auto_approve() is True


def test_shared_state_preserves_auto() -> None:
    state = ApprovalState(yolo=False, auto=True, runtime_auto=True)
    parent = Approval(state=state)
    child = parent.share()
    assert child.is_auto() is True
    assert child.is_yolo() is False
    assert child.is_auto_approve() is True
    assert child.is_runtime_auto() is True


def test_set_auto_toggles_with_on_change() -> None:
    """set_auto persists session auto and triggers on_change."""
    fired: list[bool] = []
    state = ApprovalState(yolo=False, auto=False, on_change=lambda: fired.append(True))
    approval = Approval(state=state)
    approval.set_auto(True)
    assert approval.is_auto() is True
    assert approval.is_auto_flag() is True
    assert fired == [True]
    approval.set_auto(False)
    assert approval.is_auto() is False
    assert approval.is_auto_flag() is False
    assert fired == [True, True]


def test_set_auto_false_clears_runtime_auto() -> None:
    state = ApprovalState(yolo=False, auto=False, runtime_auto=True)
    approval = Approval(state=state)
    assert approval.is_auto() is True
    approval.set_auto(False)
    assert approval.is_auto() is False
    assert approval.is_runtime_auto() is False
