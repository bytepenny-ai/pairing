"""The app's tool results before a message (prompt layouts with a tool model; chat_history_service.trim_history's
`notes_of`): never in the user's words, the same on every turn, and counted in the window."""

from app.models import Message
from app.services.chat_history_service import trim_history, window_start
from app.services.prompt_layout.base import ToolNote


def _chat() -> list[Message]:
    return [
        Message(id="u1", role="user", content="hello"),
        Message(id="a1", role="assistant", content="hi"),
        Message(id="u2", role="user", content="OK"),
    ]


NOTE = ToolNote("instruction_updates", {}, 'New skill available: "Poem".')


def test_a_note_goes_before_its_message_with_the_call_on_the_reply_before():
    history = trim_history(_chat(), 4096, notes_of=lambda m: [NOTE] if m.id == "u2" else [])
    call = {"id": "app_u2_0", "function": {"name": "instruction_updates", "arguments": {}}}
    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi", "tool_calls": [call]},
        {"role": "tool", "content": NOTE.text, "tool_name": "instruction_updates", "tool_call_id": "app_u2_0"},
        {"role": "user", "content": "OK"},  # the user's words, untouched
    ]
    assert trim_history(_chat(), 4096, notes_of=lambda m: [NOTE] if m.id == "u2" else []) == history  # same each turn


def test_a_note_with_no_reply_before_gets_a_turn_of_its_own():
    history = trim_history(_chat()[:1], 4096, notes_of=lambda m: [NOTE, NOTE])
    assert history[0]["role"] == "assistant" and history[0]["content"] == ""
    assert [c["id"] for c in history[0]["tool_calls"]] == ["app_u1_0", "app_u1_1"]
    assert [m["role"] for m in history] == ["assistant", "tool", "tool", "user"]


def test_notes_count_in_the_window():
    messages = [Message(id=f"m{i}", role="user" if i % 2 == 0 else "assistant", content="x" * 400) for i in range(8)]
    big = ToolNote("instruction_updates", {}, "y" * 1800)
    plain = window_start(messages, num_ctx=1400, reserved_tokens=512)
    crowded = window_start(messages, 1400, 512, notes_of=lambda m: [big] if m.id == "m6" else [])
    assert crowded > plain
