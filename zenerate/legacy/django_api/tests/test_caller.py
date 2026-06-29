"""Unit tests for CallerInterface and DSL quirk parsing."""
import pytest
from unittest.mock import MagicMock, patch

from apps.testing.caller import (
    TextCaller,
    strip_quirks,
    extract_quirk_tags,
    get_caller,
)


# ── DSL parsing ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("[stutter] I w-want a refund", "I w-want a refund"),
    ("[pause:3s] Hello", "Hello"),
    ("[background_noise] Can you hear me?", "Can you hear me?"),
    ("[hard_input:\"XR-99\"] the id is", "XR-99 the id is"),
    ("[phone:\"415-555-0192\"] is my number", "415-555-0192 is my number"),
    ("[email:\"a@b.com\"] is my email", "a@b.com is my email"),
    ("No quirks at all", "No quirks at all"),
])
def test_strip_quirks(raw, expected):
    assert strip_quirks(raw) == expected


@pytest.mark.parametrize("raw, expected_tags", [
    ("[stutter] text", ["stutter"]),
    ("[interrupt] Wait [background_noise] no", ["interrupt", "background_noise"]),
    ("[email:\"foo@bar.com\"] my email", ["email"]),
    ("plain text", []),
])
def test_extract_quirk_tags(raw, expected_tags):
    assert extract_quirk_tags(raw) == expected_tags


# ── TextCaller ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.system_prompt = "You are a helpful assistant."
    return agent


@patch("apps.testing.caller.AgentChat")
def test_text_caller_strips_quirks_before_sending(MockAgentChat, mock_agent):
    mock_chat = MockAgentChat.return_value
    mock_chat.send.return_value = {
        "response": "Hello", "conversation_id": "abc", "ts_ms": 100
    }

    caller = TextCaller(mock_agent)
    result = caller.send("[stutter] I w-want a refund", "conv-1")

    sent_text = mock_chat.send.call_args[0][0]
    assert "[stutter]" not in sent_text
    assert "I w-want a refund" in sent_text
    assert result["quirks"] == ["stutter"]


@patch("apps.testing.caller.AgentChat")
def test_text_caller_preserves_hard_input_value(MockAgentChat, mock_agent):
    mock_chat = MockAgentChat.return_value
    mock_chat.send.return_value = {
        "response": "ok", "conversation_id": "abc", "ts_ms": 50
    }

    caller = TextCaller(mock_agent)
    caller.send('[hard_input:"XR-99-2847-ZZ"] the code is', "conv-1")

    sent_text = mock_chat.send.call_args[0][0]
    assert "[hard_input" not in sent_text     # DSL tag removed
    assert "XR-99-2847-ZZ" in sent_text       # value substituted into text
    assert "the code is" in sent_text


@patch("apps.testing.caller.AgentChat")
def test_get_caller_returns_text_caller_by_default(MockAgentChat, mock_agent):
    caller = get_caller("text", mock_agent)
    assert isinstance(caller, TextCaller)


def test_get_caller_audio_raises_not_implemented(mock_agent):
    from apps.testing.caller import AudioCaller
    caller = get_caller("audio", mock_agent)
    assert isinstance(caller, AudioCaller)
    with pytest.raises(NotImplementedError):
        caller.send("hello", "conv-1")
