"""Local similar-issue search for code-reviewr-derived workflows."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata as importlib_metadata
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal, cast

from pythinker_review.engine.token_budget import clip_text
from pythinker_review.reviewers.artifacts import SimilarIssueMatch, SimilarIssuesOutput

_ALLOWED_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}
_MAX_ISSUE_FILES = 1_000
_MAX_ISSUE_CHARS = 12_000
_EMBED_DIM = 384
_COLLECTION_NAME = "pythinker_similar_issues"
_MIN_CHROMADB_VERSION = (0, 4, 0)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")
SimilarIssuesBackend = Literal["auto", "chroma", "lexical"]


class SimilarIssuesError(ValueError):
    """Raised when local similar-issue search cannot run."""


def find_similar_issues(
    *,
    repo: Path,
    issues_dir: Path,
    issue_text: str,
    issue_file: Path | None,
    top_k: int,
    budget_chars: int,
    backend: SimilarIssuesBackend = "lexical",
    chroma_path: Path | None = None,
    rebuild_index: bool = True,
    persist_index: bool = False,
) -> tuple[SimilarIssuesOutput, dict[str, str]]:
    """Find likely related local issue documents.

    The default lexical backend is dependency-free. The optional ChromaDB backend uses
    deterministic local hash embeddings when ChromaDB is already installed; no hosted embedding API
    or model download is required.
    """
    root = repo.resolve()
    query = _load_query(root=root, issue_text=issue_text, issue_file=issue_file)
    docs_root = _resolve_repo_path(root, issues_dir)
    candidates = _load_candidates(docs_root, issues_dir=issues_dir, repo_root=root)
    if backend in {"auto", "chroma"}:
        try:
            return _find_similar_issues_chroma(
                root=root,
                docs_root=docs_root,
                query=query,
                candidates=candidates,
                top_k=top_k,
                budget_chars=budget_chars,
                chroma_path=chroma_path,
                rebuild_index=rebuild_index,
                persist_index=persist_index,
            )
        except ModuleNotFoundError:
            if backend == "chroma":
                raise SimilarIssuesError(
                    "ChromaDB is not installed; install it separately or use --backend lexical"
                ) from None
        except Exception as exc:  # noqa: BLE001 - vector backend boundary
            if backend == "chroma":
                raise SimilarIssuesError(f"ChromaDB similar-issues search failed: {exc}") from exc
    return _find_similar_issues_lexical(
        root=root,
        docs_root=docs_root,
        query=query,
        candidates=candidates,
        top_k=top_k,
        budget_chars=budget_chars,
    )


def _load_query(*, root: Path, issue_text: str, issue_file: Path | None) -> str:
    query_parts = [issue_text.strip()]
    if issue_file is not None:
        resolved_issue = _resolve_repo_path(root, issue_file)
        if not resolved_issue.is_file():
            raise SimilarIssuesError(f"issue file is not a file: {issue_file}")
        try:
            query_parts.append(resolved_issue.read_text(encoding="utf-8", errors="replace").strip())
        except OSError as exc:
            raise SimilarIssuesError(f"failed to read issue file: {issue_file}") from exc
    query = "\n\n".join(part for part in query_parts if part)
    if not query:
        raise SimilarIssuesError("provide --issue-text or --issue-file for similar-issues")
    return query


def _load_candidates(
    docs_root: Path, *, issues_dir: Path, repo_root: Path
) -> list[tuple[Path, str]]:
    if not docs_root.exists():
        raise SimilarIssuesError(f"issues directory does not exist: {issues_dir}")
    candidates: list[tuple[Path, str]] = []
    for path in list(_iter_issue_files(docs_root, repo_root))[:_MAX_ISSUE_FILES]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text.strip():
            candidates.append((path, text))
    if not candidates:
        raise SimilarIssuesError(f"no issue documents found under: {issues_dir}")
    return candidates


def _find_similar_issues_lexical(
    *,
    root: Path,
    docs_root: Path,
    query: str,
    candidates: Sequence[tuple[Path, str]],
    top_k: int,
    budget_chars: int,
) -> tuple[SimilarIssuesOutput, dict[str, str]]:
    query_counts = _token_counts(query)
    matches: list[SimilarIssueMatch] = []
    remaining_budget = max(500, budget_chars)
    for path, text in candidates:
        score = _cosine(query_counts, _token_counts(text))
        if score <= 0:
            continue
        snippet = _best_snippet(text, query_counts)
        snippet = clip_text(snippet, min(remaining_budget, 600))
        remaining_budget = max(0, remaining_budget - len(snippet))
        matches.append(
            SimilarIssueMatch(
                issue_id=_display_path(path, docs_root),
                title=_title_for(text, path),
                path=_display_path(path, root),
                score=round(score, 4),
                snippet=snippet,
            )
        )
    matches.sort(key=lambda item: item.score, reverse=True)
    output = SimilarIssuesOutput(query=clip_text(query, 1_000), matches=matches[:top_k])
    metadata = _metadata(root=root, docs_root=docs_root, candidates=candidates, backend="lexical")
    return output, metadata


def _find_similar_issues_chroma(
    *,
    root: Path,
    docs_root: Path,
    query: str,
    candidates: Sequence[tuple[Path, str]],
    top_k: int,
    budget_chars: int,
    chroma_path: Path | None,
    rebuild_index: bool,
    persist_index: bool,
) -> tuple[SimilarIssuesOutput, dict[str, str]]:
    _validate_chromadb_distribution()
    chromadb = importlib.import_module("chromadb")
    config = importlib.import_module("chromadb.config")
    settings_cls = config.Settings
    store: Path | None = None
    if persist_index:
        store = _resolve_repo_path(root, chroma_path or Path(".pythinker-review/chroma"))
        store.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=str(store),
            settings=settings_cls(anonymized_telemetry=False),
        )
    else:
        client = chromadb.EphemeralClient(settings=settings_cls(anonymized_telemetry=False))
    collection = client.get_or_create_collection(
        _COLLECTION_NAME,
        embedding_function=None,
        metadata={"hnsw:space": "cosine"},
    )
    scope = _scope_key(root=root, docs_root=docs_root)
    if rebuild_index:
        collection.delete(where={"scope": scope})
    _upsert_chroma_documents(
        collection=collection,
        root=root,
        docs_root=docs_root,
        scope=scope,
        candidates=candidates,
    )
    query_result = collection.query(
        query_embeddings=[_hash_embedding(query)],
        where={"scope": scope},
        n_results=max(1, min(top_k, len(candidates))),
        include=["documents", "metadatas", "distances"],
    )
    matches = _matches_from_chroma_result(
        result=cast(dict[str, Any], query_result),
        query=query,
        top_k=top_k,
        budget_chars=budget_chars,
    )
    metadata = _metadata(root=root, docs_root=docs_root, candidates=candidates, backend="chroma")
    if store is not None:
        metadata["chroma_path"] = _display_path(store, root)
    return SimilarIssuesOutput(query=clip_text(query, 1_000), matches=matches), metadata


def _upsert_chroma_documents(
    *,
    collection: Any,
    root: Path,
    docs_root: Path,
    scope: str,
    candidates: Sequence[tuple[Path, str]],
) -> None:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []
    embeddings: list[list[float]] = []
    for path, text in candidates:
        rel_to_issues = _display_path(path, docs_root)
        rel_to_repo = _display_path(path, root)
        document = clip_text(text.strip(), _MAX_ISSUE_CHARS)
        ids.append(f"{scope}:{rel_to_issues}")
        documents.append(document)
        embeddings.append(_hash_embedding(document))
        metadatas.append(
            {
                "scope": scope,
                "issue_id": rel_to_issues,
                "path": rel_to_repo,
                "title": _title_for(text, path),
            }
        )
    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)


def _matches_from_chroma_result(
    *, result: dict[str, Any], query: str, top_k: int, budget_chars: int
) -> list[SimilarIssueMatch]:
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    query_counts = _token_counts(query)
    remaining_budget = max(500, budget_chars)
    matches: list[SimilarIssueMatch] = []
    for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
        meta = metadata if isinstance(metadata, dict) else {}
        text = str(document or "")
        snippet = clip_text(_best_snippet(text, query_counts), min(remaining_budget, 600))
        remaining_budget = max(0, remaining_budget - len(snippet))
        matches.append(
            SimilarIssueMatch(
                issue_id=str(meta.get("issue_id") or meta.get("path") or ""),
                title=str(meta.get("title") or "Untitled issue"),
                path=str(meta.get("path") or ""),
                score=_distance_to_score(distance),
                snippet=snippet,
            )
        )
        if len(matches) >= top_k:
            break
    return matches


def _distance_to_score(distance: Any) -> float:
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, 1.0 / (1.0 + value)), 4)


def _metadata(
    *, root: Path, docs_root: Path, candidates: Sequence[tuple[Path, str]], backend: str
) -> dict[str, str]:
    return {
        "source_label": f"local-issues:{_display_path(docs_root, root)}",
        "issues_path": _display_path(docs_root, root),
        "issues_scanned": str(len(candidates)),
        "similarity_backend": backend,
    }


def _scope_key(*, root: Path, docs_root: Path) -> str:
    raw = f"{root.resolve()}\0{docs_root.resolve()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _resolve_repo_path(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    if _has_symlink_component(candidate, root):
        raise SimilarIssuesError(f"path contains symlink: {path}")
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise SimilarIssuesError(f"path escapes repository: {path}") from exc
    return resolved


def _validate_chromadb_distribution() -> None:
    try:
        version = importlib_metadata.version("chromadb")
    except importlib_metadata.PackageNotFoundError as exc:
        raise SimilarIssuesError(
            "ChromaDB backend requested but chromadb is not installed"
        ) from exc
    parsed = _version_tuple(version)
    if parsed < _MIN_CHROMADB_VERSION:
        required = ".".join(str(part) for part in _MIN_CHROMADB_VERSION)
        raise SimilarIssuesError(f"ChromaDB backend requires chromadb>={required}; found {version}")


def _version_tuple(version: str) -> tuple[int, int, int]:
    parts = re.split(r"[^0-9]+", version, maxsplit=3)
    numbers = [int(part) for part in parts if part][:3]
    major, minor, patch = (numbers + [0, 0, 0])[:3]
    return major, minor, patch


def _has_symlink_component(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if ".." in relative.parts:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _is_safe_issue_file(path: Path, root: Path) -> bool:
    try:
        if _has_symlink_component(path, root):
            return False
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    return resolved.is_file() and resolved.suffix.lower() in _ALLOWED_EXTENSIONS


def _iter_issue_files(root: Path, repo_root: Path) -> Iterable[Path]:
    if root.is_file():
        if _is_safe_issue_file(root, repo_root):
            yield root.resolve()
        return
    for path in sorted(root.rglob("*")):
        if _is_safe_issue_file(path, repo_root):
            yield path.resolve()


def _token_counts(text: str) -> Counter[str]:
    return Counter(token.lower() for token in _TOKEN_RE.findall(clip_text(text, _MAX_ISSUE_CHARS)))


def _hash_embedding(text: str) -> list[float]:
    vector = [0.0] * _EMBED_DIM
    for token, count in _token_counts(text).items():
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % _EMBED_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in overlap)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _best_snippet(text: str, query_counts: Counter[str]) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return clip_text(text.strip(), 600)
    query_terms = set(query_counts)
    best = max(
        paragraphs,
        key=lambda part: len(set(_TOKEN_RE.findall(part.lower())) & query_terms),
    )
    return best


def _title_for(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        return clip_text(stripped, 120)
    return path.stem.replace("-", " ").replace("_", " ").strip() or path.name


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = ["SimilarIssuesBackend", "SimilarIssuesError", "find_similar_issues"]
