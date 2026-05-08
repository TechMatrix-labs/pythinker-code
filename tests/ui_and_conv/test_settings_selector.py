from __future__ import annotations

from pydantic import SecretStr

from pythinker_code.config import Config, LLMModel, LLMProvider
from pythinker_code.ui.shell.components.settings_list import (
    SettingItem,
    SettingsListConfig,
    _SettingsListState,  # type: ignore[reportPrivateUsage]
)
from pythinker_code.ui.shell.selectors.settings import (
    _build_settings_config,  # type: ignore[reportPrivateUsage]
    apply_settings_changes,
)


def test_settings_list_cycles_value_and_tracks_changes():
    state = _SettingsListState(
        SettingsListConfig(
            title="Settings",
            items=[
                SettingItem(
                    id="telemetry",
                    label="Telemetry",
                    current_value="false",
                    values=("true", "false"),
                )
            ],
        )
    )

    assert state.activate() is True
    assert state.values["telemetry"] == "true"
    assert state.changes() == {"telemetry": "true"}


def test_settings_list_read_only_item_does_not_change():
    state = _SettingsListState(
        SettingsListConfig(
            title="Settings",
            items=[SettingItem(id="config_file", label="Config file", current_value="/tmp/x")],
        )
    )

    assert state.activate() is False
    assert state.changes() == {}


def test_settings_list_fuzzy_search_filters_items():
    state = _SettingsListState(
        SettingsListConfig(
            title="Settings",
            items=[
                SettingItem(id="theme", label="Theme", current_value="dark"),
                SettingItem(id="default_model", label="Default model", current_value="gpt"),
            ],
        )
    )

    state.append_search("dm")
    assert [state.config.items[i].id for i in state.visible] == ["default_model"]


def test_build_settings_config_exposes_backed_settings_only():
    config = Config()
    settings = _build_settings_config(config)
    ids = {item.id for item in settings.items}

    assert "theme" in ids
    assert "tui.style" in ids
    assert "default_thinking" in ids
    assert "telemetry" in ids
    # Pi has image settings, but Pythinker does not expose no-op controls yet.
    assert "show-images" not in ids
    assert "image-width-cells" not in ids


def test_build_settings_config_model_values_include_config_models():
    config = Config(
        providers={
            "p": LLMProvider(
                type="openai_legacy",
                base_url="https://example.test",
                api_key=SecretStr("k"),
            )
        },
        models={
            "alpha": LLMModel(provider="p", model="a", max_context_size=1000),
            "beta": LLMModel(provider="p", model="b", max_context_size=1000),
        },
        default_model="beta",
    )

    settings = _build_settings_config(config)
    item = next(item for item in settings.items if item.id == "default_model")
    assert item.current_value == "beta"
    assert item.values is not None
    assert "alpha" in item.values
    assert "beta" in item.values


def test_apply_settings_changes_mutates_config():
    config = Config()

    changed = apply_settings_changes(
        config,
        {
            "theme": "light",
            "default_thinking": "high",
            "telemetry": "true",
            "loop_control.max_retries_per_step": "5",
            "config_file": "/ignored/read-only",
        },
    )

    assert changed == [
        "theme",
        "default_thinking",
        "telemetry",
        "loop_control.max_retries_per_step",
    ]
    assert config.theme == "light"
    assert config.default_thinking is True
    assert config.telemetry is True
    assert config.loop_control.max_retries_per_step == 5


def test_settings_list_visible_window_centers_selected_item():
    state = _SettingsListState(
        SettingsListConfig(
            title="Settings",
            max_visible=3,
            items=[SettingItem(id=str(i), label=f"Item {i}", current_value="x") for i in range(6)],
        )
    )

    state.move(3)
    assert state.visible_window() == (2, 5)
