"""image_fallback_stream.py: "Description first, image if needed" (Admin settings > System > Chat > Files in a chat)."""

import pytest
from sqlalchemy import select

from app.models import Message, MessageAttachment
from app.routers import chat_file_memory_admin
from app.schemas import ConversationCreate
from app.schemas.chat_file_memory import ChatFileMemorySetting
from app.services import (
    chat_attachment_memory,
    conversation_service,
    image_fallback_stream,
    model_catalog_service,
    reply_generation_service,
)
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_follow_up import ChatFollowUp
from app.services.image_fallback_stream import NEED_IMAGE, SWITCH_NOTE, ImageFallback, image_question


@pytest.fixture
def engine(monkeypatch):
    calls: list[tuple[str, list[dict], dict]] = []
    stopped: list[str] = []
    replies = {"text": ["It is a ", "robin."], "vision": ["A blue ", "jay."]}

    async def fake_chat_stream(model, messages, params):
        calls.append((model, messages, params))
        for chunk in replies[model]:
            yield chunk

    async def fake_stop(model, request_id=None):
        stopped.append(model)

    monkeypatch.setattr(image_fallback_stream, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(image_fallback_stream, "stop_model", fake_stop)
    return replies, calls, stopped


async def _reply(fallback: ImageFallback) -> str:
    return "".join([c async for c in fallback.stream("text", [{"role": "user", "content": "q"}], {"request_id": "m"})])


@pytest.mark.asyncio
async def test_an_answer_from_the_description_streams_as_usual(engine):
    _replies, calls, stopped = engine
    fallback = ImageFallback("vision", [{"role": "user", "content": "q", "images": ["b64"]}])
    assert await _reply(fallback) == "It is a robin."
    assert [c[0] for c in calls] == ["text"] and not stopped and fallback.model == "text"


@pytest.mark.asyncio
@pytest.mark.parametrize("first", [[NEED_IMAGE], ["  NEED", "_IMA", "GE\n"]])
async def test_need_image_hands_over_to_the_vision_model(engine, first):
    replies, calls, stopped = engine
    replies["text"] = first
    fallback = ImageFallback("vision", [{"role": "user", "content": "q", "images": ["b64"]}])
    assert await _reply(fallback) == SWITCH_NOTE + "A blue jay."
    assert stopped == ["text"] and fallback.model == "vision"
    model, messages, params = calls[1]
    assert model == "vision" and messages[-1]["images"] == ["b64"] and params["model_role"] == "vision"


@pytest.mark.asyncio
async def test_a_short_reply_that_looks_like_the_start_of_the_word_is_kept(engine):
    replies, _calls, _stopped = engine
    replies["text"] = ["NE"]
    assert await _reply(ImageFallback("vision", [])) == "NE"


@pytest.mark.asyncio
async def test_prepare_asks_the_chat_model_and_keeps_the_image_for_the_vision_model(db, monkeypatch, tmp_path):
    async def vision_model(_db):
        return "vision"

    monkeypatch.setattr(model_catalog_service, "get_default_vision_model", vision_model)
    image = tmp_path / "bird.png"
    image.write_bytes(b"png")
    messages = [
        {"role": "system", "content": "NOTES"},
        {"role": "user", "content": "/describe"},
        {"role": "assistant", "content": "A long description."},
        {"role": "user", "content": "what bird is it?"},
    ]
    attachment = AttachmentInfo(path=image, filename="bird.png", type="image")
    fallback = await ImageFallback.prepare(db, attachment, messages, image_question("", "what bird is it?"))
    assert fallback is not None and fallback.vision_model == "vision"
    assert NEED_IMAGE in messages[-1]["content"] and messages[-1]["content"].endswith("what bird is it?")
    assert "images" not in messages[-1]
    # The vision model gets the image and the question only: a prompt with an image is never reused from the cache.
    vision = fallback._vision_messages
    assert [m["role"] for m in vision] == ["system", "user"] and vision[-1]["content"] == "what bird is it?"
    assert vision[-1]["images"]


@pytest.mark.asyncio
async def test_without_a_vision_model_there_is_no_fallback(db, monkeypatch, tmp_path):
    async def none(_db):
        return None

    monkeypatch.setattr(model_catalog_service, "get_default_vision_model", none)
    image = tmp_path / "bird.png"
    image.write_bytes(b"png")
    messages = [{"role": "user", "content": "q"}]
    attachment = AttachmentInfo(path=image, filename="b.png", type="image")
    assert await ImageFallback.prepare(db, attachment, messages, image_question("", "q")) is None
    assert messages == [{"role": "user", "content": "q"}]


@pytest.mark.asyncio
async def test_the_plan_offers_the_image_for_any_later_question(db, monkeypatch, tmp_path):
    async def none(_db):
        return None

    monkeypatch.setattr(model_catalog_service, "get_default_embedding_model", none)
    monkeypatch.setattr(chat_attachment_memory, "ATTACHMENTS_DIR", tmp_path)
    (tmp_path / "c1").mkdir()
    (tmp_path / "c1" / "x_bird.png").write_bytes(b"png")
    first = Message(role="user", content="/describe")
    first.attachments = [MessageAttachment(path="c1/x_bird.png", filename="bird.png", type="image")]
    messages = [first, Message(role="assistant", content="A bird.")]
    for turn in range(5):
        messages += [Message(role="user", content=f"q{turn}"), Message(role="assistant", content="ok")]
    messages.append(Message(role="user", content="?"))
    await chat_file_memory_admin.set_chat_file_memory(
        ChatFileMemorySetting(image_follow_up="fallback"), db=db, _admin=None
    )
    plan = await ChatFollowUp(db, messages, 4096, 512).plan("what kind of bird?", [])
    assert plan.image_if_needed is not None and plan.image_again is None
    # "OK" gets no NEED_IMAGE instruction: a small model asked for the image on it.
    assert (await ChatFollowUp(db, messages, 4096, 512).plan("OK", [])).image_if_needed is None


def test_the_first_on_off_setting_still_reads():
    assert ChatFileMemorySetting(image_follow_up=True).image_follow_up == "again"
    assert ChatFileMemorySetting(image_follow_up=False).image_follow_up == "off"


@pytest.mark.asyncio
async def test_the_saved_reply_is_the_vision_models_answer(db, user, engine, monkeypatch):
    replies, _calls, _stopped = engine

    async def installed():
        return ["text"]

    monkeypatch.setattr(conversation_service, "installed_chat_models", installed)
    replies["text"] = [NEED_IMAGE]
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="text"), user)
    fallback = ImageFallback("vision", [{"role": "user", "content": "q", "images": ["b64"]}])
    events = [
        e
        async for e in reply_generation_service.stream_reply(
            db, conversation, [{"role": "user", "content": "q"}], [], fallback=fallback
        )
    ]
    assert events[-1].get("done")
    saved = (await db.execute(select(Message).where(Message.role == "assistant"))).scalars().one()
    await db.refresh(saved)
    assert saved.content == SWITCH_NOTE + "A blue jay." and NEED_IMAGE not in saved.content
