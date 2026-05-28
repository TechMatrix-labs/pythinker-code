from __future__ import annotations

import time

from pythinker_code.memory.retriever import (
    LexicalRetriever,
    RankedBlock,
    RecallQuery,
    estimate_tokens,
)


def _block(title: str, content: str, *, age_days: float = 0.0, labels=(), files=()) -> RankedBlock:
    return RankedBlock(
        tier="memory",
        source_path="MEMORY.md",
        source_id=None,
        session_id=None,
        title=title,
        labels=tuple(labels),
        files=tuple(files),
        created_at_epoch=time.time() - age_days * 86400,
        token_estimate=estimate_tokens(content),
        score=0.0,
        content=content,
    )


async def test_term_overlap_ranks_relevant_block_first():
    blocks = [
        _block("a", "the cat sat on the mat"),
        _block("b", "lexical retriever bm25 ranking memory recall"),
    ]
    retriever = LexicalRetriever(blocks)
    out = await retriever.retrieve(
        RecallQuery(text="how does the bm25 retriever rank recall"), budget_tokens=1000
    )
    assert out[0].content.startswith("lexical retriever")


async def test_recency_decay_breaks_ties_toward_newer():
    blocks = [
        _block("old", "alpha beta gamma", age_days=60),
        _block("new", "alpha beta gamma", age_days=0),
    ]
    retriever = LexicalRetriever(blocks)
    out = await retriever.retrieve(RecallQuery(text="alpha beta gamma"), budget_tokens=1000)
    assert out[0].title == "new"


async def test_budget_is_never_exceeded():
    blocks = [_block(str(i), "alpha " * 100) for i in range(20)]
    retriever = LexicalRetriever(blocks)
    out = await retriever.retrieve(RecallQuery(text="alpha"), budget_tokens=50)
    assert sum(block.token_estimate for block in out) <= 50


async def test_empty_corpus_returns_empty():
    retriever = LexicalRetriever([])
    assert await retriever.retrieve(RecallQuery(text="anything"), budget_tokens=100) == []


async def test_label_and_path_boost_applies():
    blocks = [
        _block("plain", "alpha beta"),
        _block("boosted", "alpha beta", labels=("file:src/x.py",), files=("src/x.py",)),
    ]
    retriever = LexicalRetriever(blocks)
    out = await retriever.retrieve(
        RecallQuery(text="alpha beta", paths=("src/x.py",), labels=("file:src/x.py",)),
        budget_tokens=1000,
    )
    assert out[0].title == "boosted"
