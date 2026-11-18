"""Knowledge excerpts kept with their message: later turns send that message exactly as before (prompt cache)."""

import pytest

from app.models import Message
from app.schemas import ConversationCreate
from app.services import (
    chat_prompt_service,
    chat_service,
    conversation_service,
    model_catalog_service,
    reply_generation_service,
)
from app.services.rag_chat_settings import RagChatSettings

_CHUNKS = [
    {"text": "Refunds within 30 days.", "filename": "policy.txt", "document_id": "a", "score": 0.41},
    {"text": "A refund needs the order number.", "filename": "policy.txt", "document_id": "a", "score": 0.52},
]


@pytest.fixture
def sent(monkeypatch) -> list[list[dict]]:
    """The messages each reply sent to the model."""
    calls: list[list[dict]] = []

    async def fake_installed_chat_models():
        return ["fake-model"]

    async def fake_chat_stream(_model, messages, _params):
        calls.append([dict(m) for m in messages])
        yield "ok"

    async def fake_retrieve(_db, _content, _user_id, top_k=4):
        return [dict(c) for c in _CHUNKS]

    monkeypatch.setattr(model_catalog_service, "installed_chat_models", fake_installed_chat_models)
    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat_prompt_service, "retrieve_context", fake_retrieve)
    return calls


async def _two_turns(db, user) -> list[dict]:
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    async for _ in chat_service.build_reply_stream(db, conversation, user, "refund rules?"):
        pass
    # The session caches conversation.messages (expire_on_commit=False): reload them, as a new request would.
    await db.refresh(conversation, attribute_names=["messages"])
    return [e async for e in chat_service.build_reply_stream(db, conversation, user, "and the order number?")]


def _first_question(messages: list[dict]) -> str:
    return next(m["content"] for m in messages if m["role"] == "user")


@pytest.mark.asyncio
async def test_kept_excerpts_make_the_earlier_message_match_exactly(db, user, sent):
    await RagChatSettings(db).save(0.25, True)
    events = await _two_turns(db, user)

    first, second = sent
    assert "Refunds within 30 days." in _first_question(first)
    assert _first_question(second) == _first_question(first)  # same text: the engine's cache matches
    # The same passages are already in the chat: not added again, but still listed as sources.
    assert "Refunds within 30 days." not in second[-1]["content"]
    assert next(e for e in events if e.get("done"))["sources"] == [{"name": "policy.txt", "id": "a", "score": 0.52}]


@pytest.mark.asyncio
async def test_no_cache_is_the_default_and_sends_excerpts_with_their_turn_only(db, user, sent):
    await _two_turns(db, user)

    first, second = sent
    assert "Refunds within 30 days." in _first_question(first)
    assert "Refunds within 30 days." not in _first_question(second)
    assert "Refunds within 30 days." in second[-1]["content"]
    assert all(m.knowledge_excerpts is None for m in (await db.execute(Message.__table__.select())).all())
