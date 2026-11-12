"""image_relevance.py and the meaning rule of chat_follow_up.py: a question close to an earlier image's description
uses the image, an unrelated one never does, in between the recency rule decides; long files' parts are left out for
short replies and unrelated questions (Admin settings > System > Chat > Files in a chat)."""

import numpy as np
import pytest
from pydantic import ValidationError

from app.models import Message, MessageAttachment
from app.routers import chat_file_memory_admin
from app.schemas.chat_file_memory import ChatFileMemorySetting
from app.services import chat_attachment_memory, chat_follow_up, image_relevance, model_catalog_service
from app.services.chat_attachment_memory import AttachmentMemory
from app.services.chat_file_index import ChatFileIndex
from app.services.chat_follow_up import ChatFollowUp
from app.services.image_relevance import ImageRelevance


@pytest.fixture
def chat(monkeypatch, tmp_path):
    """A chat whose image was sent five questions ago (past the recency rule), scored as `score["value"]`."""
    score: dict = {"value": None}

    async def embedding_model(_db):
        return "emb"

    async def fake_embed(text, _model):
        return [1.0, float(len(text))]

    async def fake_score(_self, _vector, _image, _description):
        return score["value"]

    monkeypatch.setattr(model_catalog_service, "get_default_embedding_model", embedding_model)
    monkeypatch.setattr(chat_follow_up, "embed", fake_embed)
    monkeypatch.setattr(ImageRelevance, "score", fake_score)
    monkeypatch.setattr(chat_attachment_memory, "ATTACHMENTS_DIR", tmp_path)
    (tmp_path / "c1").mkdir()
    (tmp_path / "c1" / "x_sea.png").write_bytes(b"png")
    first = Message(role="user", content="/describe")
    first.attachments = [MessageAttachment(path="c1/x_sea.png", filename="sea.png", type="image")]
    messages = [first, Message(role="assistant", content="A bird over a wave.")]
    for turn in range(5):
        messages += [Message(role="user", content=f"q{turn}"), Message(role="assistant", content="ok")]
    messages.append(Message(role="user", content="?"))
    return messages, score


async def _image(db, messages, question):
    await chat_file_memory_admin.set_chat_file_memory(
        ChatFileMemorySetting(image_follow_up="again"), db=db, _admin=None
    )
    return (await ChatFollowUp(db, messages, 4096, 512).plan(question, [])).image_again


@pytest.mark.asyncio
async def test_a_question_close_to_the_description_uses_the_image_however_old(db, chat):
    messages, score = chat
    score["value"] = 0.5
    assert await _image(db, messages, "how tall are those waves?") is not None


@pytest.mark.asyncio
async def test_an_unrelated_question_never_does_even_naming_a_picture(db, chat):
    messages, score = chat
    score["value"] = 0.02
    assert await _image(db, messages, "what is the capital of France, not the picture") is None


@pytest.mark.asyncio
async def test_in_between_the_recency_rule_decides(db, chat):
    messages, score = chat
    score["value"] = 0.2
    assert await _image(db, messages, "is it a male or female") is None  # five questions back, no picture word
    assert await _image(db, messages, "is the bird in the photo male") is not None


@pytest.mark.asyncio
async def test_without_a_score_the_recency_rule_decides(db, chat):
    messages, score = chat
    score["value"] = None
    assert await _image(db, messages, "is it a male or female") is None


@pytest.mark.asyncio
async def test_the_description_is_embedded_once_and_kept_next_to_the_image(monkeypatch, tmp_path):
    calls: list[str] = []

    async def fake_embed(text, _model):
        calls.append(text)
        return [1.0, 0.0]

    monkeypatch.setattr(image_relevance, "embed", fake_embed)
    image = tmp_path / "sea.png"
    image.write_bytes(b"png")
    relevance = ImageRelevance("emb")
    assert await relevance.score(np.array([1.0, 0.0], dtype=np.float32), image, "A bird.") == pytest.approx(1.0)
    assert await relevance.score(np.array([0.0, 1.0], dtype=np.float32), image, "A bird.") == pytest.approx(0.0)
    assert calls == ["A bird."] and ImageRelevance.about_path(image) in AttachmentMemory.sidecars(image)


def _long_file_chat(tmp_path) -> list[Message]:
    path = tmp_path / "c1" / "x_report.txt"
    path.write_text("x")
    AttachmentMemory.remember(path, "y" * 4000)  # over the limit of a 2048 context: searched, not whole
    first = Message(role="user", content="/summarize")
    first.attachments = [MessageAttachment(path="c1/x_report.txt", filename="report.txt", type="text")]
    return [first, Message(role="assistant", content="A report."), Message(role="user", content="?")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "best", "given"),
    [("what does it say on costs?", 0.6, True), ("OK", 0.6, False), ("tell me a joke about dogs", 0.03, False)],
)
async def test_a_long_files_parts_come_only_with_a_related_question(
    db, chat, monkeypatch, tmp_path, question, best, given
):
    async def found(*_args):
        return None

    monkeypatch.setattr(ChatFileIndex, "ensure", found)
    monkeypatch.setattr(ChatFileIndex, "search", lambda *_args: [(best, "report.txt", "Costs rose by 4%.")])
    plan = await ChatFollowUp(db, _long_file_chat(tmp_path), 2048, 512).plan(question, [])
    assert ("Costs rose by 4%." in plan.history[-1]["content"]) is given


def test_the_marks_must_be_in_order():
    with pytest.raises(ValidationError):
        ChatFileMemorySetting(related_above=0.2, unrelated_below=0.3)
