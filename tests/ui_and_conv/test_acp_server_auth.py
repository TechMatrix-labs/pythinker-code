import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import acp
import pytest
from pydantic import SecretStr

from pythinker_code.acp.server import ACPServer, _ModelIDConv
from pythinker_code.auth.oauth import OAuthToken
from pythinker_code.config import Config, LLMModel, LLMProvider


@pytest.fixture
def server() -> ACPServer:
    """Create an ACPServer instance with mocked auth methods."""
    s = ACPServer()
    s._auth_methods = [
        acp.schema.AuthMethod(
            id="login",
            name="Test Login",
            description="Test description",
            field_meta={
                "terminal-auth": {
                    "type": "terminal",
                    "args": ["pythinker", "login"],
                    "env": {},
                }
            },
        )
    ]
    return s


def _make_token(
    access_token: str = "valid_token_123",
    refresh_token: str = "refresh_123",
    expires_at: float | None = None,
) -> OAuthToken:
    if expires_at is None:
        expires_at = time.time() + 3600  # 1 hour from now
    return OAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scope="",
        token_type="Bearer",
    )


def test_check_auth_raises_when_no_token(server: ACPServer) -> None:
    """Test that _check_auth raises AUTH_REQUIRED when no token exists."""
    with patch("pythinker_code.acp.server.load_tokens", return_value=None):
        with pytest.raises(acp.RequestError) as exc_info:
            server._check_auth()

        assert exc_info.value.code == -32000  # AUTH_REQUIRED error code


def test_check_auth_raises_when_token_has_no_access_token(server: ACPServer) -> None:
    """Test that _check_auth raises AUTH_REQUIRED when token has no access_token."""
    token = _make_token(access_token="")

    with patch("pythinker_code.acp.server.load_tokens", return_value=token):
        with pytest.raises(acp.RequestError) as exc_info:
            server._check_auth()

        assert exc_info.value.code == -32000


def test_check_auth_passes_when_valid_token(server: ACPServer) -> None:
    """Test that _check_auth passes when a valid token exists."""
    token = _make_token()

    with patch("pythinker_code.acp.server.load_tokens", return_value=token):
        # Should not raise
        server._check_auth()


def test_check_auth_passes_for_active_api_key_provider(server: ACPServer) -> None:
    """Configured API-key providers should not require Pythinker OAuth."""
    config = Config(
        default_model="default",
        models={
            "default": LLMModel(
                provider="configured_provider",
                model="configured-model",
                max_context_size=100_000,
            )
        },
        providers={
            "configured_provider": LLMProvider(
                type="openai_responses",
                base_url="https://example.test/v1",
                api_key=SecretStr("configured-api-key"),
            )
        },
    )

    with patch("pythinker_code.acp.server.load_tokens") as load_tokens_mock:
        server._check_auth(config)

    load_tokens_mock.assert_not_called()


def test_check_auth_raises_when_token_expired_without_refresh(server: ACPServer) -> None:
    """Test that _check_auth raises AUTH_REQUIRED when token expired and no refresh token."""
    token = _make_token(
        expires_at=time.time() - 100,  # expired 100 seconds ago
        refresh_token="",
    )

    with patch("pythinker_code.acp.server.load_tokens", return_value=token):
        with pytest.raises(acp.RequestError) as exc_info:
            server._check_auth()

        assert exc_info.value.code == -32000


def test_check_auth_passes_when_token_expired_but_has_refresh(server: ACPServer) -> None:
    """Test that _check_auth passes when token expired but refresh token is available.

    The background refresh mechanism will handle renewal.
    """
    token = _make_token(
        expires_at=time.time() - 100,  # expired
        refresh_token="refresh_123",
    )

    with patch("pythinker_code.acp.server.load_tokens", return_value=token):
        # Should not raise — background refresh will handle it
        server._check_auth()


def test_check_auth_passes_when_expires_at_is_zero(server: ACPServer) -> None:
    """Test that expires_at=0 (no expiry info from server) is treated as valid.

    OAuthToken.from_dict() sets expires_at=0.0 when the response has no
    expires_at field. The code uses ``token.expires_at and ...`` so 0.0
    (falsy) skips the expiry check entirely.
    """
    token = _make_token(expires_at=0.0)

    with patch("pythinker_code.acp.server.load_tokens", return_value=token):
        # Should not raise
        server._check_auth()


# ---------------------------------------------------------------------------
# authenticate() must agree with _check_auth()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_rejects_expired_token_without_refresh(server: ACPServer) -> None:
    """authenticate('login') must reject an expired token with no refresh token,
    the same way _check_auth() does. Otherwise the client gets a false-success
    from authenticate, then immediately fails on new_session.
    """
    token = _make_token(
        expires_at=time.time() - 100,
        refresh_token="",
    )

    with (
        patch("pythinker_code.acp.server.load_config", return_value=Config()),
        patch("pythinker_code.acp.server.load_tokens", return_value=token),
    ):
        with pytest.raises(acp.RequestError) as exc_info:
            await server.authenticate(method_id="login")

        assert exc_info.value.code == -32000


@pytest.mark.asyncio
async def test_authenticate_accepts_valid_token(server: ACPServer) -> None:
    """authenticate('login') should succeed for a valid, non-expired token."""
    token = _make_token()

    with (
        patch("pythinker_code.acp.server.load_config", return_value=Config()),
        patch("pythinker_code.acp.server.load_tokens", return_value=token),
    ):
        result = await server.authenticate(method_id="login")

    assert result is not None


@pytest.mark.asyncio
async def test_set_session_model_updates_stored_current_model(server: ACPServer) -> None:
    """Switching back to the original model must not be skipped due to stale ACP state."""
    config = Config(
        is_from_default_location=True,
        default_model="model-a",
        models={
            "model-a": LLMModel(provider="provider-a", model="a", max_context_size=100_000),
            "model-b": LLMModel(provider="provider-b", model="b", max_context_size=100_000),
        },
        providers={
            "provider-a": LLMProvider(
                type="openai_responses",
                base_url="https://a.example.test/v1",
                api_key=SecretStr("key-a"),
            ),
            "provider-b": LLMProvider(
                type="openai_responses",
                base_url="https://b.example.test/v1",
                api_key=SecretStr("key-b"),
            ),
        },
    )
    runtime = SimpleNamespace(config=config, oauth=object(), llm="llm-a")
    acp_session = SimpleNamespace(
        id="session-1", cli=SimpleNamespace(soul=SimpleNamespace(runtime=runtime))
    )
    server.sessions["session-1"] = (cast(Any, acp_session), _ModelIDConv("model-a", False))

    def make_llm(_provider, model, **_kwargs):
        return f"llm-{model.model}"

    with (
        patch("pythinker_code.acp.server.create_llm", side_effect=make_llm) as create_llm_mock,
        patch("pythinker_code.acp.server.load_config", return_value=config.model_copy(deep=True)),
        patch("pythinker_code.acp.server.save_config"),
    ):
        await server.set_session_model("model-b", "session-1")
        await server.set_session_model("model-a", "session-1")

    assert create_llm_mock.call_count == 2
    assert runtime.llm == "llm-a"
    assert server.sessions["session-1"][1] == _ModelIDConv("model-a", False)
