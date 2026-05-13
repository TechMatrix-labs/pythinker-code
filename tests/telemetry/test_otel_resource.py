"""Tests for OTel resource identity used by dashboards."""

from __future__ import annotations

from pythinker_code.telemetry.otel import _resource  # pyright: ignore[reportPrivateUsage]


def test_resource_service_name_matches_signoz_dashboard() -> None:
    resource = _resource(version="2.4.0", ui_mode="shell", device_id="dev-test")

    assert resource.attributes["service.name"] == "pythinker-cli"
    assert resource.attributes["service.version"] == "2.4.0"
    assert resource.attributes["ui.mode"] == "shell"
