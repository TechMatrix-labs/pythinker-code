"""Security-review pass: receives deterministic signals and verifies them via the model."""

from __future__ import annotations

from pythinker_review.engine.chunker import Chunk
from pythinker_review.llm.protocol import ReviewLLM
from pythinker_review.reviewers.common import ReviewerResult, complete_reviewer_json, load_prompt
from pythinker_review.signals.models import Signal


def _format_signals(signals: list[Signal]) -> str:
    if not signals:
        return "_No deterministic signals matched. Review the diff cold._"
    lines = ["Signals (verify in code before emitting):"]
    for signal in signals:
        extra = []
        if signal.severity_hint:
            extra.append(f"severity_hint={signal.severity_hint}")
        if signal.cwe:
            extra.append(f"cwe={signal.cwe}")
        if signal.exploitability:
            extra.append(f"exploitability={signal.exploitability}")
        if signal.mitigation_hint:
            extra.append(f"mitigation={signal.mitigation_hint}")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        lines.append(
            f"- [{signal.rule_id}] {signal.file}:{signal.line} "
            f"(conf={signal.confidence:.2f}) — {signal.reason}{suffix}\n  `{signal.snippet}`"
        )
    return "\n".join(lines)


def _build_user(
    chunk: Chunk, signals: list[Signal], advisor_context: str, *, max_findings: int = 5
) -> str:
    cap = f"Return at most {max_findings} findings for this chunk.\n\n" if max_findings >= 0 else ""
    return (
        f"{advisor_context.strip()}\n\n"
        f"{_format_signals(signals)}\n\n"
        f"{cap}"
        "Review the following diff for security issues introduced by this change. "
        "Use the advisor context and signals as starting points, but emit only validated, "
        "exploitable findings with concrete source/sink/mitigation reasoning.\n\n"
        f"{chunk.rendered}\n"
    ).lstrip()


async def run_security_review_pass(
    *,
    chunk: Chunk,
    signals: list[Signal],
    llm: ReviewLLM,
    timeout_s: float,
    advisor_context: str = "",
    max_findings: int = 5,
) -> ReviewerResult:
    result = await complete_reviewer_json(
        llm=llm,
        system=load_prompt("security_review.system.md"),
        user=_build_user(chunk, signals, advisor_context, max_findings=max_findings),
        timeout_s=timeout_s,
    )
    if result.ok and max_findings >= 0:
        return ReviewerResult(ok=True, findings=tuple(result.findings[:max_findings]))
    return result
