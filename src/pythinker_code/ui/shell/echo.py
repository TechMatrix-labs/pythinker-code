from __future__ import annotations

from pythinker_core.message import Message
from rich.console import RenderableType
from rich.text import Text

from pythinker_code.ui.shell.components import render_user_message
from pythinker_code.ui.shell.prompt import PROMPT_SYMBOL_AGENT_INPUT
from pythinker_code.ui.tui_config import is_card_style
from pythinker_code.utils.message import message_stringify


def render_user_echo(message: Message) -> RenderableType:
    """Render a user message as transcript output.

    Legacy style keeps the compact sparkle-prefixed echo. Card style renders
    the text in a tinted full-width block without the prompt sparkle, as if
    the submitted buffer became a message.
    """
    text = message_stringify(message)
    if is_card_style():
        return render_user_message(text)
    return Text(f"{PROMPT_SYMBOL_AGENT_INPUT} {text}")


def render_user_echo_text(text: str) -> RenderableType:
    """Render the local prompt text exactly as the user saw it in the buffer."""
    if is_card_style():
        return render_user_message(text)
    return Text(f"{PROMPT_SYMBOL_AGENT_INPUT} {text}")
