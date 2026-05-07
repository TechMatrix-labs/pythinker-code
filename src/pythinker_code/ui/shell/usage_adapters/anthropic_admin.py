from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from pythinker_code.auth import ANTHROPIC_PLATFORM_ID
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.utils.aiohttp import new_client_session

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


ANTHROPIC_BASE = "https://api.anthropic.com/v1/organizations"
ADMIN_PREFIX = "sk-ant-admin-"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdminAdapter:
    platform_id = ANTHROPIC_PLATFORM_ID
    requires_admin_key = True
    provider_label = "Anthropic"

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport:
        del oauth_mgr
        admin_key = select_anthropic_admin_key(provider.api_key.get_secret_value())
        if admin_key is None:
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=[
                    "Set ANTHROPIC_ADMIN_KEY (sk-ant-admin-…) to see usage and cost data.",
                    "Regular sk-ant-api03-… keys cannot call the Admin API.",
                ],
                unit_hint="USD",
            )

        starting_at = (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cost = await _safe_get(
            f"{ANTHROPIC_BASE}/cost_report",
            {"starting_at": starting_at},
            admin_key,
        )
        usage = await _safe_get(
            f"{ANTHROPIC_BASE}/usage_report/messages",
            {
                "starting_at": starting_at,
                "bucket_width": "1h",
                "limit": 24,
                "group_by[]": "model",
            },
            admin_key,
        )

        cost_summary = parse_anthropic_cost(cost) if cost is not None else None
        usage_rows = parse_anthropic_usage(usage) if usage is not None else []

        notes: list[str] = []
        if cost is None:
            notes.append("Anthropic cost endpoint returned no usable data.")
        elif not _has_bucket_results_shape(cost) or not _has_cost_results_shape(cost):
            notes.append("Anthropic cost response had unexpected shape.")
        if usage is None:
            notes.append("Anthropic messages usage endpoint returned no usable data.")
        elif not _has_bucket_results_shape(usage):
            notes.append("Anthropic messages usage response had unexpected shape.")

        return UsageReport(
            self.provider_label,
            cost_summary,
            usage_rows,
            notes=notes,
            unit_hint="USD + tokens",
        )


def select_anthropic_admin_key(provider_api_key: str) -> str | None:
    env_key = os.getenv("ANTHROPIC_ADMIN_KEY")
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
                headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
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


def parse_anthropic_cost(payload: Mapping[str, Any]) -> UsageRow | None:
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


def parse_anthropic_usage(payload: Mapping[str, Any]) -> list[UsageRow]:
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
            totals[model] = totals.get(model, 0) + _to_int(result.get("uncached_input_tokens"))
            totals[model] += _to_int(result.get("output_tokens"))
            totals[model] += _to_int(result.get("cache_read_input_tokens"))
            cache_creation = result.get("cache_creation")
            if isinstance(cache_creation, Mapping):
                cache = cast(Mapping[str, Any], cache_creation)
                totals[model] += _to_int(cache.get("ephemeral_5m_input_tokens"))
                totals[model] += _to_int(cache.get("ephemeral_1h_input_tokens"))

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
        return int(Decimal(str(value)) * 100)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return 0
