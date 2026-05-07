from __future__ import annotations

import asyncio

from pythinker_code.ui.shell.usage_adapters.pythinker_ai import PythinkerAIAdapter


class _StubOAuth:
    def resolve_api_key(self, api_key, oauth):  # pyright: ignore[reportUnusedParameter]
        return ""


class _StubProvider:
    pass


def test_pythinker_ai_metadata() -> None:
    assert PythinkerAIAdapter.platform_id == "pythinker-ai"
    assert PythinkerAIAdapter.requires_admin_key is False
    assert PythinkerAIAdapter.provider_label == "Pythinker AI"


def test_pythinker_ai_returns_notes_only_report() -> None:
    adapter = PythinkerAIAdapter()
    report = asyncio.run(adapter.fetch(_StubProvider(), _StubOAuth()))  # type: ignore[arg-type]
    assert report.summary is None
    assert report.limits == []
    assert any("doesn't publish" in n.lower() or "no" in n.lower() for n in report.notes)
