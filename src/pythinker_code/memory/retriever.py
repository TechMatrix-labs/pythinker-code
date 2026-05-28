from __future__ import annotations

import math
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_RECENCY_HALF_LIFE_DAYS = 14.0
_BM25_K1 = 1.5
_BM25_B = 0.75
_LABEL_BOOST = 0.5
_PATH_BOOST = 0.5


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True, slots=True)
class RecallQuery:
    text: str = ""
    paths: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RankedBlock:
    tier: str
    source_path: str
    source_id: str | None
    session_id: str | None
    title: str
    labels: tuple[str, ...]
    files: tuple[str, ...]
    created_at_epoch: float
    token_estimate: int
    score: float
    content: str


class Retriever(ABC):
    @abstractmethod
    async def retrieve(self, query: RecallQuery, budget_tokens: int) -> list[RankedBlock]: ...


class LexicalRetriever(Retriever):
    """Hand-rolled BM25 + recency decay + label/path boost. Stdlib only."""

    def __init__(self, candidates: list[RankedBlock], *, now: float | None = None) -> None:
        self._candidates = candidates
        self._now = now if now is not None else time.time()

    async def retrieve(self, query: RecallQuery, budget_tokens: int) -> list[RankedBlock]:
        if not self._candidates or budget_tokens <= 0:
            return []
        docs = [_tokenize(c.content + " " + c.title) for c in self._candidates]
        n = len(docs)
        avgdl = sum(len(d) for d in docs) / n if n else 0.0
        df: dict[str, int] = {}
        for doc in docs:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1

        q_terms = _tokenize(query.text)
        scored: list[RankedBlock] = []
        for cand, doc in zip(self._candidates, docs, strict=True):
            dl = len(doc) or 1
            tf: dict[str, int] = {}
            for term in doc:
                tf[term] = tf.get(term, 0) + 1
            bm25 = 0.0
            for term in q_terms:
                if term not in tf:
                    continue
                term_df = df.get(term, 0)
                idf = math.log(1 + (n - term_df + 0.5) / (term_df + 0.5))
                freq = tf[term]
                bm25 += (
                    idf
                    * (freq * (_BM25_K1 + 1))
                    / (freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / (avgdl or 1)))
                )
            age_days = max(0.0, (self._now - cand.created_at_epoch) / 86400.0)
            decay = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)
            boost = 0.0
            if any(path in cand.files for path in query.paths):
                boost += _PATH_BOOST
            if set(query.labels) & set(cand.labels):
                boost += _LABEL_BOOST
            if not q_terms and not query.paths and not query.labels:
                boost += 0.01
            scored.append(replace(cand, score=bm25 * decay + boost))

        scored.sort(key=lambda b: (b.score, b.created_at_epoch), reverse=True)

        out: list[RankedBlock] = []
        used = 0
        for block in scored:
            if block.score <= 0.0:
                if not out:
                    continue
                break
            if used + block.token_estimate > budget_tokens:
                continue
            out.append(block)
            used += block.token_estimate
        return out
