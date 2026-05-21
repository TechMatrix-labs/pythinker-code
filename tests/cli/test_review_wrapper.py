import subprocess

import pytest


@pytest.mark.parametrize("cmd", ["review", "secscan", "security-scan", "debug"])
def test_top_level_help_lists_command(cmd: str) -> None:
    proc = subprocess.run(
        ["uv", "run", "pythinker", "--help"], check=True, capture_output=True, text=True
    )
    assert cmd in proc.stdout


def test_review_diff_help_works() -> None:
    proc = subprocess.run(
        ["uv", "run", "pythinker", "review", "diff", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--with-security" in proc.stdout
    assert "--mode" in proc.stdout


def test_review_artifact_help_works() -> None:
    proc = subprocess.run(
        ["uv", "run", "pythinker", "review", "describe", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--budget-chars" in proc.stdout
    assert "--timeout-s" in proc.stdout


def test_review_compliance_help_works() -> None:
    proc = subprocess.run(
        ["uv", "run", "pythinker", "review", "compliance", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--checklist" in proc.stdout
    assert "--ticket-file" in proc.stdout


def test_security_scan_help_works() -> None:
    proc = subprocess.run(
        ["uv", "run", "pythinker", "security-scan", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "scan" in proc.stdout
    assert "process" in proc.stdout


def test_debug_failure_help_works() -> None:
    proc = subprocess.run(
        ["uv", "run", "pythinker", "debug", "failure", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--command" in proc.stdout
