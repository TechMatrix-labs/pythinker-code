from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from pythinker_code.auth import OPENROUTER_PLATFORM_ID
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.utils.aiohttp import new_client_session

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"


class OpenRouterAdapter:
    platform_id = OPENROUTER_PLATFORM_ID
    requires_admin_key = False
    provider_label = "OpenRouter"

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport:
        api_key = oauth_mgr.resolve_api_key(provider.api_key, provider.oauth)
        try:
            async with (
                new_client_session() as session,
                session.get(
                    OPENROUTER_KEY_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                    raise_for_status=True,
                ) as resp,
            ):
                payload = await resp.json()
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                message = "OpenRouter returned 401 — check your API key."
            else:
                message = f"OpenRouter usage fetch failed: HTTP {e.status}"
            return UsageReport(self.provider_label, None, [], notes=[message])
        except (TimeoutError, aiohttp.ClientError) as e:
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=[f"OpenRouter usage fetch failed: {e}"],
            )

        if not isinstance(payload, Mapping):
            return UsageReport(self.provider_label, None, [], notes=["Unexpected response shape."])
        return parse_openrouter_payload(cast(Mapping[str, Any], payload))


def parse_openrouter_payload(payload: Mapping[str, Any]) -> UsageReport:
    data_raw = payload.get("data")
    if not isinstance(data_raw, Mapping):
        return UsageReport(
            provider_label=OpenRouterAdapter.provider_label,
            summary=None,
            limits=[],
            notes=["Unexpected response shape."],
            unit_hint="USD",
        )

    data = cast(Mapping[str, Any], data_raw)
    limit_reset = data.get("limit_reset")
    summary = UsageRow(
        label="Credit balance",
        used=_to_cents(data.get("usage")),
        limit=_to_cents(data.get("limit")),
        unit="USD",
        reset_hint=f"resets {limit_reset}" if limit_reset else None,
    )
    limits = [
        UsageRow("Today", _to_cents(data.get("usage_daily")), 0, unit="USD"),
        UsageRow("This week", _to_cents(data.get("usage_weekly")), 0, unit="USD"),
        UsageRow("This month", _to_cents(data.get("usage_monthly")), 0, unit="USD"),
    ]
    notes = (
        ["Free tier key; OpenRouter may apply free-model limits."]
        if data.get("is_free_tier")
        else []
    )

    return UsageReport(
        provider_label=OpenRouterAdapter.provider_label,
        summary=summary,
        limits=limits,
        notes=notes,
        unit_hint="USD",
    )


def _to_cents(value: Any) -> int:
    try:
        return int(round(float(value) * 100))
    except (OverflowError, TypeError, ValueError):
        return 0
