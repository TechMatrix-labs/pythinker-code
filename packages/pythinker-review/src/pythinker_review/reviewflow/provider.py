"""Provider prompts for stateful Reviewflow workflow commands."""

from __future__ import annotations

import json
from pathlib import Path

from pythinker_review.llm.protocol import ReviewLLM
from pythinker_review.reviewers.common import complete_typed_json
from pythinker_review.reviewflow.models import (
    FeatureRecord,
    FeatureReviewOutput,
    FindingRecord,
    FixPlanOutput,
    RevalidateOutput,
    ReviewflowConfig,
)
from pythinker_review.reviewflow.utils import read_text_bounded

REVIEW_SYSTEM = (
    "You are Pythinker Review running a pure-Python Reviewflow review.\n"
    "Return strict JSON only. Review is read-only. Report only concrete, actionable findings "
    "with evidence inside the supplied feature files. Prefer no findings over speculation.\n"
)

REVALIDATE_SYSTEM = (
    "You are revalidating one saved code-review finding.\n"
    "Return strict JSON only. Decide whether the finding is still open, fixed, false-positive, "
    "or uncertain.\n"
)

FIX_SYSTEM = """You are planning a surgical patch for one accepted finding.
Return strict JSON only with a concise summary and a unified diff rooted at the repository root.
Do not include markdown fences. Keep the diff minimal and scoped to the finding.
"""


def feature_review_user_prompt(
    *, root: Path, feature: FeatureRecord, config: ReviewflowConfig, mode: str
) -> str:
    files = (
        feature.owned_files[: config.review.max_owned_files]
        + feature.context_files[: config.review.max_context_files]
    )
    file_blocks: list[str] = []
    for ref in files:
        path = root / ref.path
        file_blocks.append(
            f"## {ref.path}\nReason: {ref.reason}\n```\n{read_text_bounded(path)}\n```"
        )
    tests = "\n".join(f"- {test.path} ({test.command or 'no command'})" for test in feature.tests)
    return f"""
Review mode: {mode}
Feature JSON:
{feature.model_dump_json(by_alias=True, indent=2)}

Relevant tests:
{tests or "- none detected"}

Files:
{chr(10).join(file_blocks) or "No readable files."}

Return JSON matching this shape:
{{
  "findings": [
    {{
      "title": "short title",
      "category": "bug|security|performance|concurrency|api-contract|data-loss|test-gap|docs-gap|build-release|maintainability",
      "severity": "critical|high|medium|low",
      "confidence": "high|medium|low",
      "evidence": [{{"path": "relative/path", "startLine": 1, "endLine": 1, "symbol": null, "quote": "exact snippet"}}],

      "reasoning": "why this is a real issue",
      "reproduction": "optional concrete trigger or null",
      "recommendation": "minimum safe fix",
      "whyTestsDoNotAlreadyCoverThis": "optional test analysis",
      "suggestedRegressionTest": "optional test to add",
      "minimumFixScope": "smallest file/function scope"
    }}
  ]
}}
""".strip()


async def review_feature(
    *,
    llm: ReviewLLM,
    root: Path,
    feature: FeatureRecord,
    config: ReviewflowConfig,
    mode: str,
    timeout_s: float,
) -> FeatureReviewOutput:
    result = await complete_typed_json(
        llm=llm,
        system=REVIEW_SYSTEM,
        user=feature_review_user_prompt(root=root, feature=feature, config=config, mode=mode),
        timeout_s=timeout_s,
        output_type=FeatureReviewOutput,
    )
    if not result.ok or result.output is None:
        raise RuntimeError(result.failure_message or result.failure_reason or "review failed")
    return result.output


async def revalidate_finding(
    *, llm: ReviewLLM, root: Path, finding: FindingRecord, timeout_s: float
) -> RevalidateOutput:
    evidence_blocks: list[str] = []
    for evidence in finding.evidence:
        evidence_blocks.append(
            f"## {evidence.path}\n```\n{read_text_bounded(root / evidence.path, limit_chars=12_000)}\n```"
        )
    user = f"""
Saved finding:
{finding.model_dump_json(by_alias=True, indent=2)}

Current evidence files:
{chr(10).join(evidence_blocks) or "No readable evidence files."}

Return JSON: {{"outcome":"open|fixed|false-positive|wont-fix|uncertain","reasoning":"...","commands":["optional validation command"]}}
""".strip()
    result = await complete_typed_json(
        llm=llm,
        system=REVALIDATE_SYSTEM,
        user=user,
        timeout_s=timeout_s,
        output_type=RevalidateOutput,
    )
    if not result.ok or result.output is None:
        raise RuntimeError(result.failure_message or result.failure_reason or "revalidation failed")
    return result.output


async def plan_fix(
    *,
    llm: ReviewLLM,
    root: Path,
    finding: FindingRecord,
    feature: FeatureRecord,
    config: ReviewflowConfig,
    timeout_s: float,
) -> FixPlanOutput:
    file_refs = feature.owned_files[: config.review.max_owned_files]
    file_blocks = [
        f"## {ref.path}\n```\n{read_text_bounded(root / ref.path, limit_chars=20_000)}\n```"
        for ref in file_refs
    ]
    user = f"""
Finding to fix:
{finding.model_dump_json(by_alias=True, indent=2)}

Feature:
{feature.model_dump_json(by_alias=True, indent=2)}

Current files:
{chr(10).join(file_blocks) or "No readable feature files."}

Configured validation commands:
{json.dumps(validation_commands_for_feature(feature, config))}

Return JSON: {{"summary":"what changed", "unifiedDiff":"diff --git ... or null", "commands":["optional extra validation"]}}
""".strip()
    result = await complete_typed_json(
        llm=llm,
        system=FIX_SYSTEM,
        user=user,
        timeout_s=timeout_s,
        output_type=FixPlanOutput,
    )
    if not result.ok or result.output is None:
        raise RuntimeError(result.failure_message or result.failure_reason or "fix planning failed")
    return result.output


def validation_commands_for_feature(feature: FeatureRecord, config: ReviewflowConfig) -> list[str]:
    commands: list[str] = []
    if config.commands.format:
        commands.append(config.commands.format)
    for test in feature.tests:
        if test.command and test.command not in commands:
            commands.append(test.command)
    for command in (config.commands.typecheck, config.commands.lint, config.commands.test):
        if command and command not in commands:
            commands.append(command)
    return commands


__all__ = [
    "plan_fix",
    "review_feature",
    "revalidate_finding",
    "validation_commands_for_feature",
]
