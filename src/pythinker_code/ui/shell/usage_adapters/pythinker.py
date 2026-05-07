from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from pythinker_code.auth import PYTHINKER_CODE_PLATFORM_ID
from pythinker_code.auth.platforms import get_platform_by_id
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.utils.aiohttp import new_client_session
from pythinker_code.utils.datetime import format_duration

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


class PythinkerAdapter:
    platform_id = PYTHINKER_CODE_PLATFORM_ID
    requires_admin_key = False
    provider_label = "Pythinker"

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport:
        platform = get_platform_by_id(self.platform_id)
        if platform is None:
            return UsageReport(
                provider_label=self.provider_label,
                summary=None,
                limits=[],
                notes=["Usage is available on Pythinker platform only."],
            )

        url = f"{platform.base_url.rstrip('/')}/usages"
        api_key = oauth_mgr.resolve_api_key(provider.api_key, provider.oauth)
        try:
            async with (
                new_client_session() as session,
                session.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                    raise_for_status=True,
                ) as resp,
            ):
                payload = await resp.json()
        except aiohttp.ClientResponseError as e:
            message = "Failed to fetch usage."
            if e.status == 401:
                message = "Authorization failed. Please check your API key."
            elif e.status == 404:
                message = "Usage endpoint not available. Try Pythinker for Coding."
            return UsageReport(self.provider_label, None, [], notes=[message])
        except TimeoutError:
            return UsageReport(
                self.provider_label,
                None,
                [],
                notes=["Failed to fetch usage: request timed out."],
            )
        except aiohttp.ClientError as e:
            return UsageReport(self.provider_label, None, [], notes=[f"Failed to fetch usage: {e}"])

        return parse_pythinker_payload(payload)


def parse_pythinker_payload(payload: Mapping[str, Any]) -> UsageReport:
    summary: UsageRow | None = None
    limits: list[UsageRow] = []

    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        usage_map: Mapping[str, Any] = cast(Mapping[str, Any], usage)
        summary = _to_usage_row(usage_map, default_label="Weekly limit")

    raw_limits_obj = payload.get("limits")
    if isinstance(raw_limits_obj, Sequence):
        limits_seq: Sequence[Any] = cast(Sequence[Any], raw_limits_obj)
        for idx, item in enumerate(limits_seq):
            if not isinstance(item, Mapping):
                continue
            item_map: Mapping[str, Any] = cast(Mapping[str, Any], item)
            detail_raw = item_map.get("detail")
            detail: Mapping[str, Any] = (
                cast(Mapping[str, Any], detail_raw) if isinstance(detail_raw, Mapping) else item_map
            )
            window_raw = item_map.get("window")
            window: Mapping[str, Any] = (
                cast(Mapping[str, Any], window_raw) if isinstance(window_raw, Mapping) else {}
            )
            label = _limit_label(item_map, detail, window, idx)
            row = _to_usage_row(detail, default_label=label)
            if row:
                limits.append(row)

    return UsageReport(
        provider_label=PythinkerAdapter.provider_label,
        summary=summary,
        limits=limits,
    )


def _to_usage_row(data: Mapping[str, Any], *, default_label: str) -> UsageRow | None:
    limit = _to_int(data.get("limit"))
    used = _to_int(data.get("used"))
    if used is None:
        remaining = _to_int(data.get("remaining"))
        if remaining is not None and limit is not None:
            used = limit - remaining
    if used is None and limit is None:
        return None
    return UsageRow(
        label=str(data.get("name") or data.get("title") or default_label),
        used=used or 0,
        limit=limit or 0,
        reset_hint=_reset_hint(data),
    )


def _limit_label(
    item: Mapping[str, Any],
    detail: Mapping[str, Any],
    window: Mapping[str, Any],
    idx: int,
) -> str:
    for key in ("name", "title", "scope"):
        if val := (item.get(key) or detail.get(key)):
            return str(val)

    duration = _to_int(window.get("duration") or item.get("duration") or detail.get("duration"))
    time_unit = window.get("timeUnit") or item.get("timeUnit") or detail.get("timeUnit") or ""
    if duration:
        if "MINUTE" in time_unit:
            if duration >= 60 and duration % 60 == 0:
                return f"{duration // 60}h limit"
            return f"{duration}m limit"
        if "HOUR" in time_unit:
            return f"{duration}h limit"
        if "DAY" in time_unit:
            return f"{duration}d limit"
        return f"{duration}s limit"

    return f"Limit #{idx + 1}"


def _reset_hint(data: Mapping[str, Any]) -> str | None:
    for key in ("reset_at", "resetAt", "reset_time", "resetTime"):
        if val := data.get(key):
            return _format_reset_time(str(val))

    for key in ("reset_in", "resetIn", "ttl", "window"):
        seconds = _to_int(data.get(key))
        if seconds:
            return f"resets in {format_duration(seconds)}"

    return None


def _format_reset_time(val: str) -> str:
    from datetime import UTC, datetime

    try:
        if "." in val and val.endswith("Z"):
            base, frac = val[:-1].split(".")
            frac = frac[:6]
            val = f"{base}.{frac}Z"
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        delta = dt - now

        if delta.total_seconds() <= 0:
            return "reset"
        return f"resets in {format_duration(int(delta.total_seconds()))}"
    except (ValueError, TypeError):
        return f"resets at {val}"


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return None


to_int = _to_int
