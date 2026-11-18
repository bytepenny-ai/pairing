"""A reply's Knowledge base sources ({name, id}, older replies: names) and the excerpts' wording
(document_retrieval.build_augmented_system_prompt)."""

from datetime import UTC, datetime

import pytest

from app.models import Conversation, Message
from app.schemas.chat import MessageOut
from app.services.chat_export import ChatExport
from app.services.document_retrieval import build_augmented_system_prompt


def _out(sources: list | None) -> MessageOut:
    return MessageOut(id="m", role="assistant", content="x", sources=sources, created_at=datetime.now(UTC))


def test_sources_carry_the_document_id_and_older_names_still_load() -> None:
    new = _out([{"name": "handbook.pdf", "id": "d1"}]).sources
    old = _out(["notes.md"]).sources
    assert new is not None and (new[0].name, new[0].id) == ("handbook.pdf", "d1")
    assert old is not None and (old[0].name, old[0].id) == ("notes.md", None)
    assert _out(None).sources is None
    scored = _out([{"name": "handbook.pdf", "id": "d1", "score": 0.35}]).sources
    assert scored is not None and scored[0].score == 0.35 and new[0].score is None


@pytest.mark.asyncio
async def test_export_lists_source_names_in_both_shapes(db, user) -> None:
    conversation = Conversation(owner_id=user.id, title="Q", model="qwen", params={})
    db.add(conversation)
    await db.commit()
    for sources in ([{"name": "handbook.pdf", "id": "d1"}], ["notes.md"]):
        db.add(Message(conversation_id=conversation.id, role="assistant", content="A", sources=sources))
    await db.commit()
    await db.refresh(conversation, ["messages"])
    text = ChatExport(conversation).markdown()
    assert "Sources: handbook.pdf" in text and "Sources: notes.md" in text


def test_excerpts_never_narrow_the_answer() -> None:
    prompt = build_augmented_system_prompt("Base.", [{"text": "Passage one."}, {"text": "Passage two."}])
    assert prompt.startswith("Base.") and "Passage one.\n\n---\n\nPassage two." in prompt
    assert "Answer the message as you would without them" in prompt and "Never narrow" in prompt
    assert build_augmented_system_prompt("Base.", []) == "Base."
