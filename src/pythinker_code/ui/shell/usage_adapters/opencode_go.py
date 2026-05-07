"""OpenCode Go usage adapter.

OpenCode Go has no public Bearer-API-key usage endpoint as of 2026-05-06
(verified via context7 `/anomalyco/opencode` and tavily — only chat
endpoints are documented; the upstream FR `anomalyco/opencode#16017` is
still open). Live consumption is only available by scraping the
authenticated workspace dashboard, which the
`slkiser/opencode-quota` plugin demonstrated:

    GET https://opencode.ai/workspace/<workspace_id>/go
    Cookie: auth=<auth_cookie>

The page is server-rendered with SolidJS and inlines a
`{rollingUsage,weeklyUsage,monthlyUsage}: $R[N]={ usagePercent, resetInSec }`
hydration block we can regex out. We mirror the slkiser parser shape so
the same workspace_id + auth_cookie config works in both tools.

If `OPENCODE_GO_WORKSPACE_ID` and `OPENCODE_GO_AUTH_COOKIE` are set the
adapter scrapes the live dashboard. Otherwise it falls back to the
published static plan caps ($12 / 5h, $30 / week, $60 / month per
opencode.ai/docs/go/) so the panel still has useful numbers.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

import aiohttp

from pythinker_code.auth import OPENCODE_GO_PLATFORM_ID
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow
from pythinker_code.utils.aiohttp import new_client_session
from pythinker_code.utils.datetime import format_duration

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


_DASHBOARD_URL_PREFIX = "https://opencode.ai/workspace/"
_DASHBOARD_URL_SUFFIX = "/go"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Gecko/20100101 Firefox/148.0"
_SCRAPE_TIMEOUT_S = 10.0

_NUM = r"(-?\d+(?:\.\d+)?)"
_WINDOWS = (
    ("rollingUsage", "5h"),
    ("weeklyUsage", "Weekly"),
    ("monthlyUsage", "Monthly"),
)
# For each window, a pair of regexes (pct-first then reset-first) since
# SolidJS may emit fields in either order.
_WINDOW_REGEXES: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    name: (
        re.compile(
            rf"{name}:\$R\[\d+\]=\{{[^}}]*usagePercent:{_NUM}[^}}]*resetInSec:{_NUM}[^}}]*\}}"
        ),
        re.compile(
            rf"{name}:\$R\[\d+\]=\{{[^}}]*resetInSec:{_NUM}[^}}]*usagePercent:{_NUM}[^}}]*\}}"
        ),
    )
    for name, _ in _WINDOWS
}

# Plan caps published at https://opencode.ai/docs/go/ (verified 2026-05-06).
# Values in USD minor units (cents).
_PLAN_CAPS: dict[str, int] = {
    "5h": 1200,
    "Weekly": 3000,
    "Monthly": 6000,
}


class OpenCodeGoAdapter:
    platform_id = OPENCODE_GO_PLATFORM_ID
    requires_admin_key = False
    provider_label = "OpenCode Go"

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport:
        workspace_id = (os.getenv("OPENCODE_GO_WORKSPACE_ID") or "").strip()
        auth_cookie = (os.getenv("OPENCODE_GO_AUTH_COOKIE") or "").strip()

        if workspace_id and auth_cookie:
            scraped, error = await _scrape_dashboard(workspace_id, auth_cookie)
            if scraped:
                return _report_from_windows(scraped, live=True)
            return _report_from_caps(error_note=error)

        if workspace_id or auth_cookie:
            missing = "OPENCODE_GO_AUTH_COOKIE" if workspace_id else "OPENCODE_GO_WORKSPACE_ID"
            return _report_from_caps(
                error_note=(
                    f"Live OpenCode Go usage needs both env vars; missing {missing}. "
                    "Static plan caps shown above."
                )
            )

        return _report_from_caps(
            error_note=(
                "Set OPENCODE_GO_WORKSPACE_ID and OPENCODE_GO_AUTH_COOKIE to scrape "
                "live usage from your workspace dashboard. Both come from your "
                "browser session at opencode.ai (workspace id from the URL, "
                "auth cookie from devtools → Application → Cookies). Static plan "
                "caps shown above in the meantime."
            )
        )


async def _scrape_dashboard(
    workspace_id: str, auth_cookie: str
) -> tuple[dict[str, tuple[float, float]] | None, str | None]:
    """Fetch the OpenCode Go dashboard and parse out window usage.

    Returns (windows, None) on success, where windows maps the window label
    (`5h`/`Weekly`/`Monthly`) to (`usage_percent`, `reset_in_sec`).
    Returns (None, error_message) on any failure. Never raises.
    """
    url = f"{_DASHBOARD_URL_PREFIX}{quote(workspace_id, safe='')}{_DASHBOARD_URL_SUFFIX}"
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html",
        "Cookie": f"auth={auth_cookie}",
    }
    try:
        async with (
            new_client_session() as session,
            session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=_SCRAPE_TIMEOUT_S),
                raise_for_status=True,
            ) as resp,
        ):
            html = await resp.text()
    except aiohttp.ClientResponseError as e:
        if e.status in (401, 403):
            return None, (
                "OpenCode Go dashboard returned "
                f"HTTP {e.status} — refresh your auth cookie from opencode.ai."
            )
        return None, f"OpenCode Go dashboard returned HTTP {e.status}"
    except (TimeoutError, aiohttp.ClientError) as e:
        return None, f"OpenCode Go dashboard fetch failed: {e}"

    windows: dict[str, tuple[float, float]] = {}
    for field, label in _WINDOWS:
        pct_first, reset_first = _WINDOW_REGEXES[field]
        if match := pct_first.search(html):
            usage_percent, reset_in_sec = float(match.group(1)), float(match.group(2))
        elif match := reset_first.search(html):
            reset_in_sec, usage_percent = float(match.group(1)), float(match.group(2))
        else:
            continue
        windows[label] = (usage_percent, reset_in_sec)

    if not windows:
        return None, (
            "OpenCode Go dashboard scrape returned no recognizable windows — the "
            "dashboard markup may have changed."
        )
    return windows, None


def _report_from_windows(windows: dict[str, tuple[float, float]], *, live: bool) -> UsageReport:
    rows: list[UsageRow] = []
    for label in ("5h", "Weekly", "Monthly"):
        if label not in windows:
            continue
        usage_percent, reset_in_sec = windows[label]
        percent_left = max(0, min(100, int(round(100 - usage_percent))))
        rows.append(
            UsageRow(
                label=f"{label} window",
                used=percent_left,
                limit=100,
                unit="%",
                reset_hint=_reset_hint(reset_in_sec),
            )
        )
    notes: list[str] = []
    if live:
        notes.append(
            "Live OpenCode Go usage scraped from the workspace dashboard. "
            f"Plan caps: 5h ${_PLAN_CAPS['5h'] / 100:.0f}, "
            f"weekly ${_PLAN_CAPS['Weekly'] / 100:.0f}, "
            f"monthly ${_PLAN_CAPS['Monthly'] / 100:.0f}."
        )
    summary = rows[0] if rows else None
    return UsageReport(
        provider_label=OpenCodeGoAdapter.provider_label,
        summary=summary,
        limits=rows[1:],
        notes=notes,
        unit_hint="quota",
    )


def _report_from_caps(*, error_note: str | None) -> UsageReport:
    rows = [
        UsageRow(label=f"{label} cap", used=0, limit=cents, unit="USD")
        for label, cents in _PLAN_CAPS.items()
    ]
    notes: list[str] = []
    if error_note:
        notes.append(error_note)
    notes.append(
        "Live consumption isn't exposed via API key (anomalyco/opencode#16017). "
        "The web console at opencode.ai is the authoritative source."
    )
    return UsageReport(
        provider_label=OpenCodeGoAdapter.provider_label,
        summary=rows[0],
        limits=rows[1:],
        notes=notes,
        unit_hint="quota",
    )


def _reset_hint(reset_in_sec: float) -> str | None:
    seconds = int(reset_in_sec)
    if seconds <= 0:
        return None
    reset_at = datetime.now(UTC) + timedelta(seconds=seconds)
    return f"resets in {format_duration(seconds)} ({reset_at.strftime('%Y-%m-%d %H:%M UTC')})"
