"""MiniMax Token-Plan usage adapter.

Endpoint sourced from the official docs (verified 2026-05-06 via
context7 + tavily against `platform.minimax.io/docs/token-plan/faq`):

    GET https://www.minimax.io/v1/token_plan/remains
    Authorization: Bearer <API Key>
    Content-Type: application/json

The published response shape isn't fully documented; community integrations
(openclaw.ai, openclaw docs / providers / minimax) cite the inner fields
`usage_percent` / `usagePercent`, `model_remains`, `start_time`, `end_time`,
which we parse defensively. The unrelated portal endpoint
`https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains` requires
browser cookies (issue #88) — we don't use it.

For pay-as-you-go MiniMax keys (non-`sk-cp-*`) there's no Token-Plan to
query, so we short-circuit and let the Phase-5 rate-limit cache fill in
live limits from chat-completion headers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from pythinker_code.auth import MINIMAX_PLATFORM_ID
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.utils.aiohttp import new_client_session

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


# Documented at https://platform.minimax.io/docs/token-plan/faq (verified
# 2026-05-06): the API-key-authenticated Token-Plan usage endpoint.
MINIMAX_TOKEN_PLAN_URL = "https://www.minimax.io/v1/token_plan/remains"
_TOKEN_PLAN_KEY_PREFIX = "sk-cp-"


class MiniMaxAdapter:
    platform_id = MINIMAX_PLATFORM_ID
    requires_admin_key = False
    provider_label = "MiniMax"

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport:
        api_key = oauth_mgr.resolve_api_key(provider.api_key, provider.oauth)

        # Pay-as-you-go MiniMax API keys (non-`sk-cp-…`) don't have a
        # token-plan to query at all; short-circuit instead of probing.
        if not api_key.startswith(_TOKEN_PLAN_KEY_PREFIX):
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=[
                    "Pay-as-you-go MiniMax keys don't expose a usage endpoint. "
                    "Live rate-limit headers will appear here after sending a "
                    "chat message."
                ],
                unit_hint="quota",
            )

        try:
            async with (
                new_client_session() as session,
                session.get(
                    MINIMAX_TOKEN_PLAN_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                    raise_for_status=True,
                ) as resp,
            ):
                payload = await resp.json(content_type=None)
        except aiohttp.ClientResponseError as e:
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=[f"MiniMax token-plan probe failed: HTTP {e.status}"],
                unit_hint="quota",
            )
        except (TimeoutError, aiohttp.ClientError) as e:
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=[f"MiniMax token-plan probe failed: {e}"],
                unit_hint="quota",
            )

        if not isinstance(payload, Mapping):
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=["Unexpected MiniMax response shape."],
                unit_hint="quota",
            )

        return parse_minimax_payload(cast(Mapping[str, Any], payload))


def parse_minimax_payload(payload: Mapping[str, Any]) -> UsageReport:
    """Parse the `/v1/token_plan/remains` response.

    Field names verified 2026-05-06 against the live API via the
    `slkiser/opencode-quota` repo (`src/providers/minimax-coding-plan.ts`).
    `model_remains` is an array of per-model entries with this shape:

        {
          "model_name": "MiniMax-M2.7",
          "current_interval_total_count": 1500,
          "current_interval_usage_count": 1473,   # CAUTION: actually REMAINING
          "remains_time": 12345,                  # seconds to 5h reset
          "current_weekly_total_count": 15000,
          "current_weekly_usage_count": 14500,    # CAUTION: actually REMAINING
          "weekly_remains_time": 432000           # seconds to weekly reset
        }

    The `*_usage_count` field names are misleading — MiniMax's API returns
    *remaining* counts there, not used. (Documented footgun in the slkiser
    integration.) `usage = total - usage_count` gives the actual usage.
    """
    notes: list[str] = []

    # MiniMax's universal envelope: 0 = success, anything else is an error.
    base_resp = payload.get("base_resp")
    if isinstance(base_resp, Mapping):
        base = cast(Mapping[str, Any], base_resp)
        status_code = base.get("status_code")
        if status_code not in (None, 0):
            msg = base.get("status_msg") or "unknown error"
            return UsageReport(
                MiniMaxAdapter.provider_label,
                None,
                [],
                notes=[f"MiniMax responded {status_code}: {msg}"],
                unit_hint="quota",
            )

    summary: UsageRow | None = None
    limits: list[UsageRow] = []

    model_remains = payload.get("model_remains")
    if isinstance(model_remains, list):
        for entry in cast(list[Any], model_remains):
            if not isinstance(entry, Mapping):
                continue
            entry_map = cast(Mapping[str, Any], entry)
            for row in _rows_from_minimax_model_entry(entry_map):
                # First row produced (the highest-priority model's 5h window)
                # becomes the panel summary; the rest go into limits.
                if summary is None:
                    summary = row
                else:
                    limits.append(row)

    if summary is None and not limits:
        outer = ", ".join(sorted(payload.keys())) or "<empty>"
        notes.append(
            f"MiniMax returned no recognizable token-plan fields "
            f"(keys: {outer}). Live rate-limit headers will fill this "
            f"panel after sending a chat message."
        )

    return UsageReport(
        provider_label=MiniMaxAdapter.provider_label,
        summary=summary,
        limits=limits,
        notes=notes,
        unit_hint="quota",
    )


def _rows_from_minimax_model_entry(entry: Mapping[str, Any]) -> list[UsageRow]:
    """Yield the 5h-window and weekly-window UsageRows for one model entry.

    Returns an empty list if no recognized window fields are present.
    """
    model_name = str(entry.get("model_name") or entry.get("model") or "model")
    rows: list[UsageRow] = []

    interval_total = _to_int(entry.get("current_interval_total_count"))
    interval_remaining = _to_int(entry.get("current_interval_usage_count"))
    interval_remains_seconds = _to_int(entry.get("remains_time"))
    if interval_total is not None and interval_remaining is not None:
        rows.append(
            UsageRow(
                label=f"{model_name} 5h",
                used=min(interval_total, max(0, interval_remaining)),
                limit=interval_total,
                unit="requests",
                reset_hint=_seconds_to_reset_hint(interval_remains_seconds),
            )
        )

    weekly_total = _to_int(entry.get("current_weekly_total_count"))
    weekly_remaining = _to_int(entry.get("current_weekly_usage_count"))
    weekly_remains_seconds = _to_int(entry.get("weekly_remains_time"))
    if weekly_total is not None and weekly_remaining is not None:
        rows.append(
            UsageRow(
                label=f"{model_name} weekly",
                used=min(weekly_total, max(0, weekly_remaining)),
                limit=weekly_total,
                unit="requests",
                reset_hint=_seconds_to_reset_hint(weekly_remains_seconds),
            )
        )

    return rows


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _seconds_to_reset_hint(seconds: int | None) -> str | None:
    from pythinker_code.utils.datetime import format_duration

    if seconds is None or seconds <= 0:
        return None
    return f"resets in {format_duration(seconds)}"
