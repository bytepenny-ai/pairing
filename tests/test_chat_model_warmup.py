"""chat_model_warmup.py: after the vision model answers, the chat model reads the chat in the background, so the next
text message ("OK") reuses that prompt instead of re-reading the image's long description."""

import asyncio

import pytest

from app.routers import chat_file_memory_admin
from app.schemas import ConversationCreate
from app.schemas.chat_file_memory import ChatFileMemorySetting
from app.services import (
    chat_attachment_memory,
    chat_model_warmup,
    chat_service,
    conversation_service,
    model_catalog_service,
    reply_generation_service,
)
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_model_warmup import ChatModelWarmUp


@pytest.fixture
def engines(monkeypatch, tmp_path):
    replies: list[tuple[str, list[dict], dict]] = []
    warmed: list[tuple[str, list[dict], dict]] = []

    async def reply_stream(model, messages, params):
        replies.append((model, messages, params))
        yield "A long description of a bird over a wave." if model == "vision" else "Anything else?"

    async def warm_stream(model, messages, params):
        warmed.append((model, messages, params))
        yield "x"

    async def installed():
        return ["chat-model"]

    async def vision(_db):
        return "vision"

    monkeypatch.setattr(reply_generation_service, "chat_stream", reply_stream)
    monkeypatch.setattr(chat_model_warmup, "chat_stream", warm_stream)
    monkeypatch.setattr(model_catalog_service, "installed_chat_models", installed)
    monkeypatch.setattr(conversation_service, "installed_chat_models", installed)
    monkeypatch.setattr(model_catalog_service, "get_default_vision_model", vision)
    monkeypatch.setattr(chat_service, "ATTACHMENTS_DIR", tmp_path)
    monkeypatch.setattr(chat_attachment_memory, "ATTACHMENTS_DIR", tmp_path)
    return replies, warmed


async def _send(db, conversation, user, content, attachments=None) -> None:
    async for _event in chat_service.build_reply_stream(db, conversation, user, content, attachments=attachments):
        pass


@pytest.mark.asyncio
async def test_the_chat_model_reads_the_image_reply_before_the_next_message(db, user, tmp_path, engines):
    replies, warmed = engines
    image = tmp_path / "bird.png"
    image.write_bytes(b"png")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="chat-model"), user)

    await _send(db, conversation, user, "/describe", [AttachmentInfo(path=image, filename="bird.png", type="image")])
    await asyncio.gather(*ChatModelWarmUp._running)
    await db.refresh(conversation)
    await _send(db, conversation, user, "OK")

    model, warm_messages, warm_params = warmed[0]
    assert model == "chat-model" and warm_params["num_predict"] == 1
    assert warm_params["conversation_id"] == conversation.id  # the engine files the read prompt under this chat
    next_model, next_messages, _params = replies[1]
    assert next_model == "chat-model"
    assert warm_messages[:-1] == next_messages[:-1]  # everything before the new message: reused from the cache
    assert "A long description" in warm_messages[-2]["content"]


@pytest.mark.asyncio
async def test_a_text_reply_needs_no_warm_up(db, user, engines):
    _replies, warmed = engines
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="chat-model"), user)
    await _send(db, conversation, user, "hello")
    await asyncio.gather(*ChatModelWarmUp._running)
    assert warmed == []


@pytest.mark.asyncio
async def test_an_earlier_image_shown_again_comes_with_the_question_only(db, user, tmp_path, engines):
    replies, _warmed = engines
    image = tmp_path / "bird.png"
    image.write_bytes(b"png")
    await chat_file_memory_admin.set_chat_file_memory(
        ChatFileMemorySetting(image_follow_up="again"), db=db, _admin=None
    )
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="chat-model"), user)
    await _send(db, conversation, user, "/describe", [AttachmentInfo(path=image, filename="bird.png", type="image")])
    await asyncio.gather(*ChatModelWarmUp._running)
    await db.refresh(conversation)
    await _send(db, conversation, user, "what kind of bird is that?")

    model, messages, _params = replies[1]
    assert model == "vision" and [m["role"] for m in messages] == ["system", "user"]
    assert messages[-1]["content"] == "what kind of bird is that?" and messages[-1]["images"]


@pytest.mark.asyncio
async def test_a_chat_model_that_sees_images_answers_them_and_keeps_them_in_the_history(
    db, user, tmp_path, engines, monkeypatch
):
    """Matricxon's gemma 4 with its image file: no switch to the vision model, no warm-up, and the image goes with its
    message on later turns, so the follow-up's prompt starts exactly like the image turn's (cache match)."""
    replies, warmed = engines

    async def sees_images():
        return ["chat-model", "vision"]

    monkeypatch.setattr(model_catalog_service, "installed_vision_models", sees_images)
    image = tmp_path / "bird.png"
    image.write_bytes(b"png")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="chat-model"), user)
    await _send(db, conversation, user, "/describe", [AttachmentInfo(path=image, filename="bird.png", type="image")])
    await asyncio.gather(*ChatModelWarmUp._running)
    await db.refresh(conversation)
    await _send(db, conversation, user, "OK")

    (first_model, first, _), (next_model, follow_up, _) = replies
    assert first_model == next_model == "chat-model" and warmed == []
    assert first[-1]["images"] and follow_up[1]["images"] == first[-1]["images"]
    assert follow_up[1]["content"] == first[-1]["content"]  # no "an image was attached" note
    assert follow_up[0] == first[0]  # same system prompt in both turns
