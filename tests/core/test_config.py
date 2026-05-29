from __future__ import annotations

import pytest
from inline_snapshot import snapshot

from pythinker_code.config import (
    Config,
    get_default_config,
    load_config,
    load_config_from_string,
)
from pythinker_code.exception import ConfigError


def test_default_config():
    config = get_default_config()
    assert config == snapshot(Config())


def test_default_config_dump():
    config = get_default_config()
    assert config.model_dump() == snapshot(
        {
            "default_model": "",
            "default_thinking": False,
            "agent_execution_profile": "default",
            "default_yolo": False,
            "ask_user_question_policy": "ask_except_auto",
            "default_plan_mode": False,
            "default_editor": "",
            "theme": "dark",
            "show_thinking_stream": True,
            "prevent_idle_sleep": False,
            "models": {},
            "providers": {},
            "loop_control": {
                "max_steps_per_turn": 1000,
                "max_retries_per_step": 3,
                "max_ralph_iterations": 0,
                "reserved_context_size": 50000,
                "compaction_trigger_ratio": 0.85,
            },
            "background": {
                "max_running_tasks": 4,
                "task_retention_days": 7,
                "read_max_bytes": 30000,
                "notification_tail_lines": 20,
                "notification_tail_chars": 3000,
                "wait_poll_interval_ms": 500,
                "worker_heartbeat_interval_ms": 5000,
                "worker_stale_after_ms": 15000,
                "kill_grace_period_ms": 2000,
                "max_output_bytes": 52428800,
                "keep_alive_on_exit": False,
                "agent_task_timeout_s": 3600,
                "print_wait_ceiling_s": 3600,
            },
            "notifications": {
                "claim_stale_after_ms": 15000,
            },
            "services": {"pythinker_ai_search": None, "pythinker_ai_fetch": None},
            "mcp": {"client": {"tool_call_timeout_ms": 60000}},
            "memory": {
                "lexical_recall": True,
                "injection_bus": True,
                "injection_ceiling_tokens": 2048,
                "harvest_on_compaction": False,
                "journal_recaps": False,
                "consolidation": False,
            },
            "feedback": {
                "endpoint_url": "",
                "api_key": None,
                "custom_headers": None,
                "github_client_id": "",
                "github_repo": "TechMatrix-labs/pythinker-code",
            },
            "hooks": [],
            "merge_all_available_skills": True,
            "extra_skill_dirs": [],
            "telemetry": True,
            "skip_auto_prompt_injection": False,
            "tui": {"style": "card", "prompt_history_enabled": True},
        }
    )


def test_load_config_text_toml():
    config = load_config_from_string('default_model = ""\n')
    assert config == get_default_config()


def test_load_config_text_json():
    config = load_config_from_string('{"default_model": ""}')
    assert config == get_default_config()


def test_agent_execution_profile_autonomous_sets_autonomy_defaults():
    config = load_config_from_string('agent_execution_profile = "autonomous_coding"')

    assert config.default_yolo is True
    assert config.ask_user_question_policy == "never"


def test_agent_execution_profile_respects_explicit_values():
    config = load_config_from_string(
        "\n".join(
            [
                'agent_execution_profile = "autonomous_coding"',
                "default_yolo = false",
                'ask_user_question_policy = "always"',
            ]
        )
    )

    assert config.default_yolo is False
    assert config.ask_user_question_policy == "always"


def test_agent_execution_profile_plan_only_sets_plan_defaults():
    config = load_config_from_string('agent_execution_profile = "plan_only"')

    assert config.default_plan_mode is True
    assert config.ask_user_question_policy == "always"


def test_load_config_sets_source_file(tmp_path):
    config_file = tmp_path / "custom.toml"

    config = load_config(config_file)

    assert config.source_file == config_file.resolve()
    assert not config.is_from_default_location


def test_load_config_text_has_no_source_file():
    config = load_config_from_string('{"default_model": ""}')

    assert config.source_file is None


def test_load_config_text_invalid():
    with pytest.raises(ConfigError, match="Invalid configuration text"):
        load_config_from_string("not valid {")


def test_load_config_invalid_ralph_iterations():
    with pytest.raises(ConfigError, match="max_ralph_iterations"):
        load_config_from_string('{"loop_control": {"max_ralph_iterations": -2}}')


def test_load_config_reserved_context_size():
    config = load_config_from_string('{"loop_control": {"reserved_context_size": 30000}}')
    assert config.loop_control.reserved_context_size == 30000


def test_load_config_max_steps_per_turn():
    config = load_config_from_string("[loop_control]\nmax_steps_per_turn = 42\n")
    assert config.loop_control.max_steps_per_turn == 42


def test_load_config_corrupt_legacy_json_is_backed_up_and_replaced(tmp_path, monkeypatch):
    """Corrupt (non-JSON) legacy config: backup + use defaults, no silent data loss."""
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    legacy_config = tmp_path / "config.json"
    legacy_config.write_text(
        '{"providers":{"custom":{"apiKey":null}}',  # unclosed brace — invalid JSON
        encoding="utf-8",
    )

    config = load_config()

    # Config should be defaults (created fresh), JSON backed up, TOML written.
    assert config.model_dump(
        exclude={"is_from_default_location", "source_file"}
    ) == get_default_config().model_dump(exclude={"is_from_default_location", "source_file"})
    assert not legacy_config.exists()
    assert (tmp_path / "config.json.bak").exists()
    assert (tmp_path / "config.toml").exists()


def test_load_config_incompatible_legacy_json_is_preserved_and_rejected(tmp_path, monkeypatch):
    """Incompatible (valid JSON but schema mismatch) legacy config: preserved, error raised."""
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    legacy_config = tmp_path / "config.json"
    legacy_config.write_text(
        '{"loop_control": {"max_ralph_iterations": -2}}',  # valid JSON, invalid schema
        encoding="utf-8",
    )

    # Should raise ConfigError with details instead of silently using defaults.
    from pythinker_code.exception import ConfigError

    with pytest.raises(ConfigError, match="max_ralph_iterations"):
        load_config()

    # Legacy file and TOML must both remain intact — no silent backup/replace.
    assert legacy_config.exists()
    assert not (tmp_path / "config.toml").exists()


def test_load_config_max_steps_per_run():
    config = load_config_from_string('{"loop_control": {"max_steps_per_run": 7}}')
    assert config.loop_control.max_steps_per_turn == 7


def test_load_config_reserved_context_size_too_low():
    with pytest.raises(ConfigError, match="reserved_context_size"):
        load_config_from_string('{"loop_control": {"reserved_context_size": 500}}')


def test_load_config_compaction_trigger_ratio():
    config = load_config_from_string('{"loop_control": {"compaction_trigger_ratio": 0.8}}')
    assert config.loop_control.compaction_trigger_ratio == 0.8


def test_load_config_compaction_trigger_ratio_default():
    config = load_config_from_string("{}")
    assert config.loop_control.compaction_trigger_ratio == 0.85


def test_load_config_compaction_trigger_ratio_too_low():
    with pytest.raises(ConfigError, match="compaction_trigger_ratio"):
        load_config_from_string('{"loop_control": {"compaction_trigger_ratio": 0.3}}')


def test_load_config_compaction_trigger_ratio_too_high():
    with pytest.raises(ConfigError, match="compaction_trigger_ratio"):
        load_config_from_string('{"loop_control": {"compaction_trigger_ratio": 1.0}}')
