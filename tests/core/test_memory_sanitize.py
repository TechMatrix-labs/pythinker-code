from __future__ import annotations

from pythinker_code.memory.sanitize import sanitize_candidate_block, strip_private_spans


def test_strip_private_spans_removes_marked_text():
    assert (
        strip_private_spans("keep <private>drop me</private> keep").strip() == "keep  keep".strip()
    )


def test_strip_private_spans_is_case_insensitive_and_multiline():
    text = "a <PRIVATE>line one\nline two</PRIVATE> b"
    assert "line one" not in strip_private_spans(text)
    assert "a" in strip_private_spans(text) and "b" in strip_private_spans(text)


def test_sanitize_drops_block_that_is_only_private():
    assert sanitize_candidate_block("<private>secret</private>") is None


def test_sanitize_drops_unsafe_content():
    assert sanitize_candidate_block("token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX") is None


def test_sanitize_returns_clean_text_for_safe_block():
    out = sanitize_candidate_block("decision: use the lexical retriever")
    assert out == "decision: use the lexical retriever"
