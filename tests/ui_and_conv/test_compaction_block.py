from pythinker_code.ui.shell.components import render_plain
from pythinker_code.ui.shell.visualize._blocks import _CompactionBlock


def test_compaction_block_matches_reference_shape():
    block = _CompactionBlock(context_tokens=37_600)
    block._start -= 30.0
    rendered = render_plain(block._render(), width=100)

    assert "✢ Compacting conversation…" in rendered
    assert "↑ 37.6k tokens" in rendered
    assert "▰" in rendered
    assert "▱" in rendered
    assert "⎿  Tip:" in rendered


def test_compaction_block_context_tokens_can_update():
    block = _CompactionBlock(context_tokens=None)
    block.update_context_tokens(12_345)

    rendered = render_plain(block._render(), width=100)

    assert "↑ 12.3k tokens" in rendered
