from __future__ import annotations

from pydantic import SecretStr

from pythinker_code.config import LLMModel, LLMProvider
from pythinker_code.llm import augment_provider_with_env_vars


def test_augment_lm_studio_provider_honors_non_secret_env_only(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="http://localhost:1234/v1",
        api_key=SecretStr("local"),
    )
    model = LLMModel(provider="managed:lm-studio", model="qwen", max_context_size=4096)

    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.5:1234/v1")
    monkeypatch.setenv("LM_STUDIO_API_KEY", "secret")

    applied = augment_provider_with_env_vars(provider, model, provider_key="managed:lm-studio")
    assert provider.base_url == "http://10.0.0.5:1234/v1"
    assert provider.api_key.get_secret_value() == "local"
    assert applied == {"LM_STUDIO_BASE_URL": "http://10.0.0.5:1234/v1"}


def test_augment_ollama_provider_honors_env(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="http://localhost:11434/v1",
        api_key=SecretStr("local"),
    )
    model = LLMModel(provider="managed:ollama", model="llama3.1:8b", max_context_size=4096)

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.5:11434/v1")
    applied = augment_provider_with_env_vars(provider, model, provider_key="managed:ollama")
    assert provider.base_url == "http://192.168.0.5:11434/v1"
    assert "OLLAMA_BASE_URL" in applied


def test_augment_other_openai_legacy_provider_is_unaffected(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="https://api.deepseek.com/v1",
        api_key=SecretStr("real-key"),
    )
    model = LLMModel(provider="managed:deepseek", model="deepseek-v4-pro", max_context_size=4096)

    monkeypatch.setenv("LM_STUDIO_BASE_URL", "should-not-leak")
    monkeypatch.setenv("OLLAMA_BASE_URL", "should-not-leak")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    augment_provider_with_env_vars(provider, model, provider_key="managed:deepseek")
    assert provider.base_url == "https://api.deepseek.com/v1"
    assert provider.api_key.get_secret_value() == "real-key"


def test_openai_env_does_not_override_opencode_go_openai_provider(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="https://opencode.ai/zen/go/v1",
        api_key=SecretStr("opencode-key"),
    )
    model = LLMModel(
        provider="managed:opencode-go-openai",
        model="kimi-k2.6",
        max_context_size=262_000,
    )

    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    applied = augment_provider_with_env_vars(
        provider,
        model,
        provider_key="managed:opencode-go-openai",
    )
    assert applied == {}
    assert provider.base_url == "https://opencode.ai/zen/go/v1"
    assert provider.api_key.get_secret_value() == "opencode-key"


def test_openai_api_key_env_does_not_override_openai_provider_auth(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("saved-openai-key"),
    )
    model = LLMModel(provider="managed:openai", model="gpt-5", max_context_size=128_000)

    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-key")

    applied = augment_provider_with_env_vars(provider, model, provider_key="managed:openai")
    assert provider.base_url == "https://api.openai.test/v1"
    assert provider.api_key.get_secret_value() == "saved-openai-key"
    assert applied == {}


def test_augment_no_provider_key_falls_back_to_legacy_behavior(monkeypatch):
    """Existing call sites that don't pass provider_key still work."""
    provider = LLMProvider(
        type="openai_legacy",
        base_url="https://api.example.com/v1",
        api_key=SecretStr("k"),
    )
    model = LLMModel(provider="some_provider_key", model="m", max_context_size=4096)

    # No env vars set; just verify it doesn't crash and returns dict.
    applied = augment_provider_with_env_vars(provider, model)
    assert isinstance(applied, dict)
