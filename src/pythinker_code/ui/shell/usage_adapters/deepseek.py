from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from pythinker_code.auth import DEEPSEEK_PLATFORM_ID
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.utils.aiohttp import new_client_session

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
SUPPORTED_CURRENCIES = {"USD", "CNY"}


class DeepSeekAdapter:
    platform_id = DEEPSEEK_PLATFORM_ID
    requires_admin_key = False
    provider_label = "DeepSeek"

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
                    DEEPSEEK_BALANCE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                    raise_for_status=True,
                ) as resp,
            ):
                payload = await resp.json()
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                message = "DeepSeek returned 401 — check your API key."
            else:
                message = f"DeepSeek balance fetch failed: HTTP {e.status}"
            return UsageReport(self.provider_label, None, [], notes=[message], unit_hint="balance")
        except (TimeoutError, aiohttp.ClientError) as e:
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=[f"DeepSeek balance fetch failed: {e}"],
                unit_hint="balance",
            )

        if not isinstance(payload, Mapping):
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=["Unexpected response shape."],
                unit_hint="balance",
            )
        return parse_deepseek_payload(cast(Mapping[str, Any], payload))


def parse_deepseek_payload(payload: Mapping[str, Any]) -> UsageReport:
    summary: UsageRow | None = None
    limits: list[UsageRow] = []
    notes: list[str] = []

    if payload.get("is_available") is False:
        notes.append("DeepSeek balance is currently unavailable for API calls.")

    balance_infos_raw = payload.get("balance_infos")
    if not isinstance(balance_infos_raw, Sequence) or isinstance(balance_infos_raw, str | bytes):
        return UsageReport(
            provider_label=DeepSeekAdapter.provider_label,
            summary=None,
            limits=[],
            notes=[*notes, "Unexpected response shape: balance_infos missing."],
            unit_hint="balance",
        )

    balance_infos: Sequence[Any] = cast(Sequence[Any], balance_infos_raw)
    for info_raw in balance_infos:
        if not isinstance(info_raw, Mapping):
            continue
        info: Mapping[str, Any] = cast(Mapping[str, Any], info_raw)
        currency = str(info.get("currency") or "")
        if currency not in SUPPORTED_CURRENCIES:
            continue

        total = UsageRow(
            f"Total balance ({currency})",
            _to_minor_units(info.get("total_balance")),
            0,
            unit=currency,
        )
        if summary is None:
            summary = total
        else:
            limits.append(total)
        limits.append(
            UsageRow(
                f"Granted ({currency})",
                _to_minor_units(info.get("granted_balance")),
                0,
                unit=currency,
            )
        )
        limits.append(
            UsageRow(
                f"Topped up ({currency})",
                _to_minor_units(info.get("topped_up_balance")),
                0,
                unit=currency,
            )
        )

    return UsageReport(
        provider_label=DeepSeekAdapter.provider_label,
        summary=summary,
        limits=limits,
        notes=notes,
        unit_hint="balance",
    )


def _to_minor_units(value: Any) -> int:
    try:
        return int(Decimal(str(value)) * 100)
    except (InvalidOperation, ValueError):
        return 0
