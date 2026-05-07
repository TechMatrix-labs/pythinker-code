from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from pythinker_code.auth import OPENAI_API_PLATFORM_ID
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.utils.aiohttp import new_client_session

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


OPENAI_BASE = "https://api.openai.com/v1"
ADMIN_PREFIX = "sk-admin-"


class OpenAIAdminAdapter:
    platform_id = OPENAI_API_PLATFORM_ID
    requires_admin_key = True
    provider_label = "OpenAI API"

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport:
        del oauth_mgr
        admin_key = select_admin_key(provider.api_key.get_secret_value())
        if admin_key is None:
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=[
                    "Set OPENAI_ADMIN_KEY (sk-admin-…) to see usage and cost data.",
                    "The OpenAI Admin API does not accept regular sk-proj-… keys.",
                ],
                unit_hint="USD",
            )

        start_time = int(time.time()) - 24 * 60 * 60
        costs = await _safe_get(
            f"{OPENAI_BASE}/organization/costs",
            {"start_time": start_time, "limit": 1},
            admin_key,
        )
        completions = await _safe_get(
            f"{OPENAI_BASE}/organization/usage/completions",
            {
                "start_time": start_time,
                "bucket_width": "1d",
                "limit": 7,
                "group_by": "model",
            },
            admin_key,
        )

        cost_summary = parse_openai_costs(costs) if costs is not None else None
        completion_rows = parse_openai_completions(completions) if completions is not None else []

        notes: list[str] = []
        if costs is None:
            notes.append("OpenAI costs endpoint returned no usable data.")
        elif not _has_bucket_results_shape(costs) or not _has_cost_results_shape(costs):
            notes.append("OpenAI cost response had unexpected shape.")
        if completions is None:
            notes.append("OpenAI completions usage endpoint returned no usable data.")
        elif not _has_bucket_results_shape(completions):
            notes.append("OpenAI completions usage response had unexpected shape.")

        return UsageReport(
            self.provider_label,
            cost_summary,
            completion_rows,
            notes=notes,
            unit_hint="USD + tokens",
        )


def select_admin_key(provider_api_key: str) -> str | None:
    env_key = os.getenv("OPENAI_ADMIN_KEY")
    if env_key:
        return env_key
    if provider_api_key.startswith(ADMIN_PREFIX):
        return provider_api_key
    return None


async def _safe_get(
    url: str,
    params: Mapping[str, str | int],
    api_key: str,
) -> Mapping[str, Any] | None:
    try:
        async with (
            new_client_session() as session,
            session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=aiohttp.ClientTimeout(total=5),
                raise_for_status=True,
            ) as resp,
        ):
            payload = await resp.json()
    except (TimeoutError, aiohttp.ClientError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return cast(Mapping[str, Any], payload)


def parse_openai_costs(payload: Mapping[str, Any]) -> UsageRow | None:
    data = _as_sequence(payload.get("data"))
    if data is None:
        return None

    total_cents = 0
    for bucket_raw in data:
        if not isinstance(bucket_raw, Mapping):
            return None
        bucket = cast(Mapping[str, Any], bucket_raw)
        results = _as_sequence(bucket.get("results"))
        if results is None:
            return None
        for result_raw in results:
            if not isinstance(result_raw, Mapping):
                return None
            result = cast(Mapping[str, Any], result_raw)
            amount = result.get("amount")
            if not isinstance(amount, Mapping):
                return None
            cents = _to_cents(cast(Mapping[str, Any], amount).get("value"))
            if cents is None:
                return None
            total_cents += cents

    return UsageRow("Cost (last 24h)", total_cents, 0, unit="USD")


def parse_openai_completions(payload: Mapping[str, Any]) -> list[UsageRow]:
    data = _as_sequence(payload.get("data"))
    if data is None:
        return []

    totals: dict[str, int] = {}
    for bucket_raw in data:
        if not isinstance(bucket_raw, Mapping):
            continue
        bucket = cast(Mapping[str, Any], bucket_raw)
        results = _as_sequence(bucket.get("results"))
        if results is None:
            continue
        for result_raw in results:
            if not isinstance(result_raw, Mapping):
                continue
            result = cast(Mapping[str, Any], result_raw)
            model = result.get("model")
            if not isinstance(model, str) or not model:
                continue
            totals[model] = totals.get(model, 0) + _to_int(result.get("input_tokens"))
            totals[model] += _to_int(result.get("output_tokens"))

    return [
        UsageRow(model, used, 0, unit="tokens")
        for model, used in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def _as_sequence(value: Any) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return cast(Sequence[Any], value)
    return None


def _has_bucket_results_shape(payload: Mapping[str, Any]) -> bool:
    data = _as_sequence(payload.get("data"))
    if data is None:
        return False
    for bucket_raw in data:
        if not isinstance(bucket_raw, Mapping):
            return False
        bucket = cast(Mapping[str, Any], bucket_raw)
        if _as_sequence(bucket.get("results")) is None:
            return False
    return True


def _has_cost_results_shape(payload: Mapping[str, Any]) -> bool:
    data = _as_sequence(payload.get("data"))
    if data is None:
        return False
    for bucket_raw in data:
        bucket = cast(Mapping[str, Any], bucket_raw)
        results = cast(Sequence[Any], bucket.get("results"))
        for result_raw in results:
            if not isinstance(result_raw, Mapping):
                return False
            result = cast(Mapping[str, Any], result_raw)
            amount = result.get("amount")
            if not isinstance(amount, Mapping):
                return False
            if _to_cents(cast(Mapping[str, Any], amount).get("value")) is None:
                return False
    return True


def _to_cents(value: Any) -> int | None:
    try:
        return int(round(float(value) * 100))
    except (OverflowError, TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return 0
