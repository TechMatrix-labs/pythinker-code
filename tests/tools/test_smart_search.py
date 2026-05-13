from __future__ import annotations

from pathlib import Path

from pythinker_code.tools.file.grep_local import SmartSearch, SmartSearchParams


async def test_smart_search_returns_bounded_cited_lines(tmp_path: Path):
    target = tmp_path / "module.py"
    target.write_text(
        "def alpha_feature():\n    return 'needle value'\n\ndef beta():\n    return 'other'\n",
        encoding="utf-8",
    )

    result = await SmartSearch()(SmartSearchParams(query="alpha feature", path=str(tmp_path)))

    assert not result.is_error
    assert "module.py" in result.output
    assert "alpha_feature" in result.output
    assert "SmartSearch ran" in result.message


async def test_smart_search_no_matches_is_success(tmp_path: Path):
    (tmp_path / "module.py").write_text("print('hello')\n", encoding="utf-8")

    result = await SmartSearch()(SmartSearchParams(query="missing symbol", path=str(tmp_path)))

    assert not result.is_error
    assert "No matches found" in result.message
