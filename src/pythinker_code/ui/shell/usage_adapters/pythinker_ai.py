"""Pythinker AI Open Platform usage adapter (notes-only).

Verified 2026-05-06 via context7 (`/websites/platform_minimax_io`,
`/websites/z_ai`) and tavily web search: there are no public docs and
no discoverable usage/billing endpoint for `api.pythinker-ai.ai` /
`api.pythinker-ai.cn`. Earlier drafts of this adapter speculatively
probed `/user/balance` (the DeepSeek convention) — that was a guess,
not a verified shape, so it's been removed to avoid surfacing
misleading errors against an endpoint that doesn't exist.

The adapter exists so `/usage` produces a clean panel for Pythinker AI
sessions and the Phase-5 rate-limit cache can fill in live limits from
chat-completion response headers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pythinker_code.ui.shell.usage_adapters.base import UsageReport

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider


PYTHINKER_AI_PLATFORM_ID = "pythinker-ai"


class PythinkerAIAdapter:
    platform_id = PYTHINKER_AI_PLATFORM_ID
    requires_admin_key = False
    provider_label = "Pythinker AI"

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport:
        return UsageReport(
            provider_label=self.provider_label,
            summary=None,
            limits=[],
            notes=[
                "Pythinker AI doesn't publish a usage endpoint. "
                "Live rate-limit headers will appear here after sending a "
                "chat message."
            ],
            unit_hint="quota",
        )
