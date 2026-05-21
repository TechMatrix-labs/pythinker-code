import subprocess


def test_secscan_diff_help_works() -> None:
    proc = subprocess.run(
        ["uv", "run", "pythinker", "secscan", "diff", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--fail-on" in proc.stdout
