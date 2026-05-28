from __future__ import annotations

import sqlite3

from pythinker_code.memory.retriever import LexicalRetriever, RankedBlock, RecallQuery, Retriever


def sqlite_fts5_available() -> bool:
    """Return whether this Python sqlite build supports FTS5."""
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return True


class SqliteFts5Retriever(Retriever):
    """FTS5-capability seam with lexical fallback.

    The SQLite index is intentionally derived/rebuildable and is not wired into the
    default app path yet. Until the indexed path is expanded, this class preserves
    Retriever semantics by delegating to the dependency-free lexical retriever.
    """

    def __init__(
        self, candidates: list[RankedBlock], *, fts5_available: bool | None = None
    ) -> None:
        self._candidates = candidates
        self._fts5_available = sqlite_fts5_available() if fts5_available is None else fts5_available
        self._fallback = LexicalRetriever(candidates)

    @property
    def uses_fts5(self) -> bool:
        return self._fts5_available

    async def retrieve(self, query: RecallQuery, budget_tokens: int) -> list[RankedBlock]:
        # Derived FTS5 indexing is intentionally deferred until measurements justify it.
        return await self._fallback.retrieve(query, budget_tokens)
