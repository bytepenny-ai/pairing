"""When a chat outgrows the context window its oldest messages are trimmed and the engine compacts its cache, which
takes longer: the reply's waiting label says "Compacting cache..." (from pAIring's own trim, at once, or from
Matricxon's read progress), instead of "Thinking..."."""

import pytest

from app.models import Message
from app.schemas import ConversationCreate
from app.services import (
    chat_follow_up,
    chat_service,
    context_window_setting,
    conversation_service,
    model_catalog_service,
    reply_broadcast_service,
    reply_generation_service,
    reply_side_events,
)
from app.services.reply_side_events import ReplySideEvents


def test_only_an_expected_reply_starts_compacting():
    reply_broadcast_service.expect_compacting("c-a")
    reply_broadcast_service.start_topic("c-a", "m1")
    _state, queue = reply_broadcast_service.subscribe("c-a")
    try:
        reply_broadcast_service.publish_compacting("c-a", known=True)
        assert queue.get_nowait() == {"compacting": True, "message_id": "m1"}
        reply_broadcast_service.start_topic("c-a", "m2")  # the next reply: not expected
        reply_broadcast_service.publish_compacting("c-a", known=True)
        assert queue.empty()
        reply_broadcast_service.publish_compacting("c-a")  # the engine says so
        assert queue.get_nowait() == {"compacting": True, "message_id": "m2"}
    finally:
        reply_broadcast_service.unsubscribe("c-a", queue)


@pytest.mark.asyncio
async def test_matricxon_saying_it_compacts_reaches_the_chat_once(db, monkeypatch):
    told: list[str] = []
    monkeypatch.setattr(
        reply_side_events.reply_broadcast_service,
        "publish_compacting",
        lambda conversation, known=False: None if known else told.append(conversation),
    )
    events = ReplySideEvents(db, Message(role="assistant", content=""), "c1")
    for read in (0, 300):
        chunk = {"read_progress": {"cached": 0, "read": read, "total": 1000, "compacting": True}}
        assert await events.handle(chunk) is False
    assert told == ["c1"]


@pytest.mark.asyncio
async def test_the_turn_that_trims_the_chat_says_compacting(db, user, monkeypatch):
    async def fake_chat_stream(_model, _messages, _params):
        yield "ok " * 200

    async def installed():
        return ["fake-model"]

    async def small_window(_db):
        return 2048

    monkeypatch.setattr(model_catalog_service, "installed_chat_models", installed)
    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(context_window_setting, "get_num_ctx", small_window)
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    compacting_turns = []
    for turn in range(12):
        events = [e async for e in chat_service.build_reply_stream(db, conversation, user, f"q{turn} " + "x" * 900)]
        if any(e.get("compacting") for e in events):
            compacting_turns.append(turn)
        await db.refresh(conversation)
    assert compacting_turns and compacting_turns[0] > 0  # not before the chat outgrew the window
    assert len(compacting_turns) < 12  # trimming moves in steps: most turns keep the same start


def test_the_channel_poll_carries_a_waiting_replys_label_state():
    reply_broadcast_service.expect_compacting("c-poll")
    reply_broadcast_service.start_topic("c-poll", "m1")
    reply_broadcast_service.publish_read_progress("c-poll", 0.35)
    assert reply_broadcast_service.waiting_reply("c-poll") == {
        "message_id": "m1",
        "reasoning": [],
        "read_progress": 0.35,
        "compacting": True,
    }
    reply_broadcast_service.publish_chunk("c-poll", "Hello")  # words arrived: the normal text shows
    assert reply_broadcast_service.waiting_reply("c-poll") is None
    assert reply_broadcast_service.waiting_reply("no-such-chat") is None


@pytest.mark.asyncio
async def test_a_compacting_turn_gives_no_file_left_the_window_notice(db, monkeypatch):
    monkeypatch.setattr(
        chat_follow_up.AttachmentMemory, "forgotten_notice", staticmethod(lambda *_args: "a file left the window")
    )
    compacting = 0
    for turns in range(1, 16):
        messages = []
        for turn in range(turns):
            messages += [Message(role="user", content=f"q{turn} " + "x" * 900), Message(role="assistant", content="ok")]
        messages.append(Message(role="user", content="last " + "x" * 900))
        plan = await chat_follow_up.ChatFollowUp(db, messages, 2048, 512).plan("last", [])
        compacting += plan.compacting
        assert ("a file left the window" in plan.notices) is not plan.compacting, turns
    assert compacting > 0
