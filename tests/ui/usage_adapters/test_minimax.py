from __future__ import annotations

from pythinker_code.ui.shell.usage_adapters.minimax import (
    MINIMAX_TOKEN_PLAN_URL,
    MiniMaxAdapter,
    parse_minimax_payload,
)


def test_minimax_metadata() -> None:
    assert MiniMaxAdapter.platform_id == "minimax"
    assert MiniMaxAdapter.requires_admin_key is False


def test_minimax_uses_documented_api_endpoint() -> None:
    # Per https://platform.minimax.io/docs/token-plan/faq (verified
    # 2026-05-06), the API-key-authenticated endpoint lives at minimax.io,
    # NOT the cookie-only portal at
    # minimaxi.com/v1/api/openplatform/coding_plan/remains.
    assert MINIMAX_TOKEN_PLAN_URL == "https://www.minimax.io/v1/token_plan/remains"


def test_parse_minimax_payload_real_shape() -> None:
    """Live response shape sourced from `slkiser/opencode-quota`'s
    minimax-coding-plan provider, which has exercised this endpoint
    against real Token-Plan accounts.

    The `*_usage_count` field names are misleading — MiniMax actually
    returns *remaining* counts there, not used. We compute used as
    min(total, remaining) for the UsageRow (which the renderer treats
    as the displayed remaining value)."""
    payload = {
        "base_resp": {"status_code": 0, "status_msg": ""},
        "model_remains": [
            {
                "model_name": "MiniMax-M2.7",
                "current_interval_total_count": 1500,
                "current_interval_usage_count": 1473,
                "remains_time": 12345,
                "current_weekly_total_count": 15000,
                "current_weekly_usage_count": 14500,
                "weekly_remains_time": 432000,
            },
        ],
    }
    report = parse_minimax_payload(payload)
    assert report.summary is not None
    assert report.summary.label == "MiniMax-M2.7 5h"
    assert report.summary.unit == "requests"
    assert report.summary.used == 1473
    assert report.summary.limit == 1500
    assert "resets in" in (report.summary.reset_hint or "")

    assert len(report.limits) == 1
    weekly = report.limits[0]
    assert weekly.label == "MiniMax-M2.7 weekly"
    assert weekly.used == 14500
    assert weekly.limit == 15000


def test_parse_minimax_payload_multiple_models() -> None:
    payload = {
        "base_resp": {"status_code": 0},
        "model_remains": [
            {
                "model_name": "MiniMax-M2.7",
                "current_interval_total_count": 1500,
                "current_interval_usage_count": 100,
                "remains_time": 1,
                "current_weekly_total_count": 15000,
                "current_weekly_usage_count": 1000,
                "weekly_remains_time": 1,
            },
            {
                "model_name": "MiniMax-M2.7-highspeed",
                "current_interval_total_count": 4500,
                "current_interval_usage_count": 4000,
                "remains_time": 1,
                "current_weekly_total_count": 45000,
                "current_weekly_usage_count": 40000,
                "weekly_remains_time": 1,
            },
        ],
    }
    report = parse_minimax_payload(payload)
    # Summary = first model's 5h row; remaining 3 rows go in limits.
    assert report.summary is not None
    assert report.summary.label == "MiniMax-M2.7 5h"
    labels = [r.label for r in report.limits]
    assert "MiniMax-M2.7 weekly" in labels
    assert "MiniMax-M2.7-highspeed 5h" in labels
    assert "MiniMax-M2.7-highspeed weekly" in labels


def test_parse_minimax_payload_clamps_remaining_above_total() -> None:
    payload = {
        "model_remains": [
            {
                "model_name": "MiniMax-M2.7",
                "current_interval_total_count": 100,
                # Bogus value — MiniMax sometimes returns numbers larger than
                # the total during edge cases. Clamp to total.
                "current_interval_usage_count": 99999,
                "remains_time": 0,
                "current_weekly_total_count": 1000,
                "current_weekly_usage_count": 1000,
                "weekly_remains_time": 0,
            }
        ]
    }
    report = parse_minimax_payload(payload)
    assert report.summary is not None
    assert report.summary.used == 100  # clamped


def test_parse_minimax_payload_error_status_surfaces_message() -> None:
    payload = {"base_resp": {"status_code": 1004, "status_msg": "auth failed"}}
    report = parse_minimax_payload(payload)
    assert report.summary is None
    assert any("1004" in n and "auth failed" in n for n in report.notes)


def test_parse_minimax_payload_unknown_shape_surfaces_keys() -> None:
    payload = {"foo": 1, "bar": 2}
    report = parse_minimax_payload(payload)
    assert report.summary is None
    assert any("foo" in n and "bar" in n for n in report.notes)
