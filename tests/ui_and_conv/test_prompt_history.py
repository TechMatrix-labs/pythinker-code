from __future__ import annotations

import json
import stat

from PIL import Image

from pythinker_code.ui.shell import prompt as shell_prompt
from pythinker_code.ui.shell.placeholders import AttachmentCache, PromptPlaceholderManager


def _make_prompt_session(
    tmp_path, manager: PromptPlaceholderManager
) -> shell_prompt.CustomPromptSession:
    prompt_session = object.__new__(shell_prompt.CustomPromptSession)
    prompt_session._history_file = tmp_path / "history.jsonl"
    prompt_session._last_history_content = None
    prompt_session._history_enabled = True
    prompt_session._placeholder_manager = manager
    prompt_session._attachment_cache = manager.attachment_cache
    return prompt_session


def _read_history_lines(path) -> list[dict[str, str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_append_history_entry_expands_text_placeholders_but_preserves_images(tmp_path) -> None:
    manager = PromptPlaceholderManager(attachment_cache=AttachmentCache(root=tmp_path / "cache"))
    pasted_text = "\n".join([f"line{i}" for i in range(1, 16)])
    text_token = manager.maybe_placeholderize_pasted_text(pasted_text)
    image = Image.new("RGB", (4, 4), color=(10, 20, 30))
    image_token = manager.create_image_placeholder(image)

    assert image_token == "[Image #1]"

    prompt_session = _make_prompt_session(tmp_path, manager)
    prompt_session._append_history_entry(f"before {text_token} {image_token} after")

    # Display token `[Image #N]` is rewritten to canonical `[image:<id>,WxH]` so history
    # remains resolvable across sessions via the attachment cache.
    lines = _read_history_lines(prompt_session._history_file)
    assert len(lines) == 1
    content = lines[0]["content"]
    assert content.startswith(f"before {pasted_text} [image:")
    assert content.endswith(",4x4] after")


def test_append_history_entry_deduplicates_consecutive_tokens_with_same_expanded_text(
    tmp_path,
) -> None:
    manager = PromptPlaceholderManager()
    prompt_session = _make_prompt_session(tmp_path, manager)
    token_one = manager.maybe_placeholderize_pasted_text("alpha\nbeta\ngamma")
    token_two = manager.maybe_placeholderize_pasted_text("alpha\nbeta\ngamma")

    prompt_session._append_history_entry(token_one)
    prompt_session._append_history_entry(token_two)

    assert _read_history_lines(prompt_session._history_file) == [{"content": "alpha\nbeta\ngamma"}]


def test_append_history_entry_writes_sanitized_surrogate_text(tmp_path) -> None:
    manager = PromptPlaceholderManager()
    prompt_session = _make_prompt_session(tmp_path, manager)
    token = manager.maybe_placeholderize_pasted_text("A" * 1000 + "\ud83d")

    prompt_session._append_history_entry(token)

    lines = _read_history_lines(prompt_session._history_file)
    assert len(lines) == 1
    assert "\ud83d" not in lines[0]["content"]
    assert "\ufffd" in lines[0]["content"]
    assert lines[0]["content"].startswith("A" * 1000)


def test_append_history_entry_redacts_common_secret_patterns(tmp_path) -> None:
    manager = PromptPlaceholderManager()
    prompt_session = _make_prompt_session(tmp_path, manager)

    prompt_session._append_history_entry(
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz "
        "api_key=sk-abcdefghijklmnop "
        '{"api_key": "quotedsecretvalue123"} '
        'token="quotedtokenvalue123"'
    )

    content = _read_history_lines(prompt_session._history_file)[0]["content"]
    assert "abcdefghijklmnopqrstuvwxyz" not in content
    assert "sk-abcdefghijklmnop" not in content
    assert "quotedsecretvalue123" not in content
    assert "quotedtokenvalue123" not in content
    assert content.count("[REDACTED]") == 4


def test_append_history_entry_redacts_oauth_and_vendor_tokens(tmp_path) -> None:
    manager = PromptPlaceholderManager()
    prompt_session = _make_prompt_session(tmp_path, manager)

    prompt_session._append_history_entry(
        "Authorization: Basic dXNlcjpwYXNzd29yZA== "
        "https://example.test/cb?access_token=access-token-secret&refresh_token=refresh-secret "
        "id_token=header.payload.signature "
        "ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz1234567890 "
        "AIzaSyabcdefghijklmnopqrstuvwxyz1234567"
    )

    content = _read_history_lines(prompt_session._history_file)[0]["content"]
    for secret in (
        "dXNlcjpwYXNzd29yZA==",
        "access-token-secret",
        "refresh-secret",
        "header.payload.signature",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz1234567890",
        "AIzaSyabcdefghijklmnopqrstuvwxyz1234567",
    ):
        assert secret not in content
    assert content.count("[REDACTED]") == 7


def test_append_history_entry_can_be_disabled(tmp_path) -> None:
    manager = PromptPlaceholderManager()
    prompt_session = _make_prompt_session(tmp_path, manager)
    prompt_session._history_enabled = False

    prompt_session._append_history_entry("do not persist")

    assert not prompt_session._history_file.exists()


def test_append_history_entry_restricts_file_permissions(tmp_path) -> None:
    manager = PromptPlaceholderManager()
    prompt_session = _make_prompt_session(tmp_path, manager)

    prompt_session._append_history_entry("hello")

    mode = stat.S_IMODE(prompt_session._history_file.stat().st_mode)
    assert mode == 0o600
