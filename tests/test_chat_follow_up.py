"""chat_follow_up.py, chat_file_index.py and Admin settings > System > Chat > "Files in a chat": long files are searched
per question, files that left the window keep the reply about them, and an earlier image can be shown again."""

import numpy as np
import pytest
from pydantic import ValidationError

from app.models import Message, MessageAttachment
from app.routers import chat_file_memory_admin
from app.schemas.chat_file_memory import ChatFileMemorySetting
from app.services import (
    chat_attachment_memory,
    chat_attachment_service,
    chat_file_index,
    chat_follow_up,
    image_relevance,
    model_catalog_service,
)
from app.services.chat_attachment_memory import AttachmentMemory
from app.services.chat_attachment_service import AttachmentInfo, delete_attachment_files
from app.services.chat_file_index import ChatFileIndex
from app.services.chat_follow_up import ChatFollowUp
from app.services.inference_client import InferenceError

WORDS = ["launch", "weather", "apple", "budget"]


async def _fake_embed(text: str, _model: str) -> list[float]:
    return [float(text.lower().count(word)) + 0.01 for word in WORDS]


@pytest.fixture
def engine(monkeypatch, tmp_path):
    async def embedding_model(_db):
        return "emb"

    monkeypatch.setattr(model_catalog_service, "get_default_embedding_model", embedding_model)
    monkeypatch.setattr(chat_file_index, "embed", _fake_embed)
    monkeypatch.setattr(chat_follow_up, "embed", _fake_embed)

    async def no_embedding(
        _text, _model
    ):  # image relevance unknown: the recency rule decides (test_image_relevance.py)
        raise InferenceError("not in these tests")

    monkeypatch.setattr(image_relevance, "embed", no_embedding)
    monkeypatch.setattr(chat_attachment_memory, "ATTACHMENTS_DIR", tmp_path)


def _file_message(tmp_path, name: str, kind: str, body: bytes, content: str) -> Message:
    path = tmp_path / "c1" / f"x_{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    message = Message(role="user", content=content)
    message.attachments = [MessageAttachment(path=f"c1/x_{name}", filename=name, type=kind)]
    return message


def _long_text() -> bytes:
    filler = "Nothing much happens in this paragraph at all. " * 40
    return f"{filler}The launch code is 12345.\n{filler}The weather was cold.\n{filler}".encode()


@pytest.mark.asyncio
async def test_the_setting_round_trips_and_has_safe_defaults(db):
    default = await chat_file_memory_admin.get_chat_file_memory(db=db, _admin=None)
    assert default == ChatFileMemorySetting(whole_file_percent=25, image_follow_up="off")
    saved = ChatFileMemorySetting(whole_file_percent=40, image_follow_up="fallback")
    await chat_file_memory_admin.set_chat_file_memory(saved, db=db, _admin=None)
    assert await chat_file_memory_admin.get_chat_file_memory(db=db, _admin=None) == saved
    with pytest.raises(ValidationError):
        ChatFileMemorySetting(whole_file_percent=95)


@pytest.mark.asyncio
async def test_a_long_file_is_searched_and_the_matching_part_comes_with_the_question(db, engine, tmp_path):
    first = _file_message(tmp_path, "report.txt", "text", _long_text(), "/summarize")
    messages = [first, Message(role="assistant", content="A long report."), Message(role="user", content="launch?")]
    follow_up = ChatFollowUp(db, messages, num_ctx=2048, reserved_tokens=512)

    plan = await follow_up.plan("what is the launch code?", [])

    assert "12345" not in plan.history[0]["content"]  # not repeated whole every turn
    assert 'a long file named "report.txt"' in plan.history[0]["content"]
    newest = plan.history[-1]["content"]
    assert "### From report.txt" in newest and "12345" in newest and newest.endswith("launch?")
    assert ChatFileIndex.index_path(tmp_path / "c1" / "x_report.txt").exists()


@pytest.mark.asyncio
async def test_a_short_file_stays_whole_and_is_not_indexed(db, engine, tmp_path):
    first = _file_message(tmp_path, "note.txt", "text", b"The launch code is 12345.", "/summarize")
    messages = [first, Message(role="assistant", content="A note."), Message(role="user", content="code?")]
    plan = await ChatFollowUp(db, messages, num_ctx=2048, reserved_tokens=512).plan("code?", [])
    assert "12345" in plan.history[0]["content"]
    assert not ChatFileIndex.index_path(tmp_path / "c1" / "x_note.txt").exists()


@pytest.mark.asyncio
async def test_a_file_that_left_the_window_keeps_the_reply_about_it(db, engine, tmp_path):
    first = _file_message(tmp_path, "cat.png", "image", b"png", "/describe")
    messages = [first, Message(role="assistant", content="A grey cat on a red sofa.")]
    for turn in range(8):
        messages += [Message(role="user", content=f"q{turn} " + "x" * 400), Message(role="assistant", content="ok")]
    messages.append(Message(role="user", content="what was on the sofa?"))

    plan = await ChatFollowUp(db, messages, num_ctx=512, reserved_tokens=0).plan("what was on the sofa?", [])

    opening = plan.history[0]
    assert opening["role"] == "user" and "A grey cat on a red sofa." in opening["content"]
    assert '"cat.png"' in opening["content"]


@pytest.mark.asyncio
async def test_an_earlier_image_is_shown_again_only_when_allowed_and_asked_about(db, engine, tmp_path):
    first = _file_message(tmp_path, "car.png", "image", b"png", "/describe")
    messages = [first, Message(role="assistant", content="A car."), Message(role="user", content="?")]

    off = await ChatFollowUp(db, messages, 4096, 512).plan("what colour is the car in the picture?", [])
    assert off.image_again is None

    await chat_file_memory_admin.set_chat_file_memory(ChatFileMemorySetting(image_follow_up=True), db=db, _admin=None)
    on = await ChatFollowUp(db, messages, 4096, 512).plan("what colour is the car in the picture?", [])
    assert on.image_again is not None and on.image_again.filename == "car.png"
    # A follow-up right after the image needs no picture words: "what kind of a bird is that?"
    plain = await ChatFollowUp(db, messages, 4096, 512).plan("what kind of a bird is that?", [])
    assert plain.image_again is not None
    # A short reply needs no image (it would re-read the whole chat and the image); a short question still does.
    for reply in ("OK", "thanks a lot", "great!", "תודה"):
        assert (await ChatFollowUp(db, messages, 4096, 512).plan(reply, [])).image_again is None, reply
    for short_question in ("count the birds", "why?", "מה זה"):
        assert (await ChatFollowUp(db, messages, 4096, 512).plan(short_question, [])).image_again, short_question

    later = [*messages[:-1]]
    for turn in range(3):
        later += [Message(role="user", content=f"q{turn}"), Message(role="assistant", content="ok")]
    later.append(Message(role="user", content="?"))
    assert (await ChatFollowUp(db, later, 4096, 512).plan("tell me a joke", [])).image_again is None
    assert (await ChatFollowUp(db, later, 4096, 512).plan("and the picture?", [])).image_again is not None


@pytest.mark.asyncio
async def test_without_an_embedding_model_every_file_stays_whole(db, monkeypatch, tmp_path):
    async def none(_db):
        return None

    monkeypatch.setattr(model_catalog_service, "get_default_embedding_model", none)
    monkeypatch.setattr(chat_attachment_memory, "ATTACHMENTS_DIR", tmp_path)
    first = _file_message(tmp_path, "report.txt", "text", _long_text(), "/summarize")
    messages = [first, Message(role="assistant", content="ok"), Message(role="user", content="launch?")]
    plan = await ChatFollowUp(db, messages, num_ctx=8192, reserved_tokens=512).plan("launch?", [])
    assert "12345" in plan.history[0]["content"]


@pytest.mark.asyncio
async def test_the_long_file_of_this_message_is_indexed_after_the_reply(db, engine, tmp_path):
    current = _file_message(tmp_path, "big.txt", "text", _long_text(), "/summarize")
    path = tmp_path / "c1" / "x_big.txt"
    AttachmentMemory.remember(path, "x" * 4000)  # what was sent: over the limit of a 2048 context
    follow_up = ChatFollowUp(db, [current], num_ctx=2048, reserved_tokens=512)
    await follow_up.plan("/summarize", [])
    follow_up.schedule_indexing([AttachmentInfo(path=path, filename="big.txt", type="text")])
    await ChatFileIndex.ensure(path, "emb")
    assert ChatFileIndex.search([(path, "big.txt")], await _as_vector("launch"), "emb", 1)[0][2].count("12345") == 1


async def _as_vector(text: str):
    return np.asarray(await _fake_embed(text, "emb"), dtype=np.float32)


@pytest.mark.asyncio
async def test_deleting_a_message_removes_its_saved_text_and_index(db, engine, tmp_path, monkeypatch):
    monkeypatch.setattr(chat_attachment_service, "ATTACHMENTS_DIR", tmp_path)
    path = tmp_path / "c1" / "x_a.txt"
    path.parent.mkdir(parents=True)
    for file in (path, *AttachmentMemory.sidecars(path)):
        file.write_text("x")
    attachment = MessageAttachment(path="c1/x_a.txt", filename="a.txt", type="text")

    class _Db:
        async def refresh(self, _message, attribute_names):
            pass

        async def delete(self, _row):
            pass

    await delete_attachment_files(_Db(), Message(role="user", content="", attachments=[attachment]))
    assert not any(file.exists() for file in (path, *AttachmentMemory.sidecars(path)))
