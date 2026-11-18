"""build_reply_stream's "retrieval" event: sent when knowledge excerpts go into the prompt (chat_vector_space.js)."""

import pytest

from app.schemas import ConversationCreate
from app.services import (
    chat_prompt_service,
    chat_service,
    conversation_service,
    model_catalog_service,
    reply_generation_service,
)


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch):
    async def fake_installed_chat_models():
        return ["fake-model"]

    async def fake_chat_stream(_model, _messages, _params):
        yield "ok"

    monkeypatch.setattr(model_catalog_service, "installed_chat_models", fake_installed_chat_models)
    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)


async def _events(db, user) -> list[dict]:
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    return [event async for event in chat_service.build_reply_stream(db, conversation, user, "refund rules?")]


@pytest.mark.asyncio
async def test_retrieval_event_counts_the_source_documents_before_the_reply(db, user, monkeypatch):
    async def fake_retrieve(_db, _content, _user_id, top_k=4):
        return [
            {"text": "Refunds within 30 days.", "filename": "policy.txt", "document_id": "a", "score": 0.52},
            {"text": "A refund needs the order.", "filename": "policy.txt", "document_id": "a", "score": 0.61},
            {"text": "Gift cards are final.", "filename": "cards.txt", "document_id": "b", "score": 0.44},
        ]

    monkeypatch.setattr(chat_prompt_service, "retrieve_context", fake_retrieve)
    events = await _events(db, user)

    keys = [next(iter(event)) for event in events]
    retrieval = next(e for e in events if "retrieval" in e)
    assert retrieval == {"retrieval": 2, "retrieval_best": 0.61}  # the best score, as shown under Sources
    assert keys.index("retrieval") < keys.index("chunk")


@pytest.mark.asyncio
async def test_no_retrieval_event_without_knowledge_excerpts(db, user, monkeypatch):
    async def fake_retrieve(_db, _content, _user_id, top_k=4):
        return []

    monkeypatch.setattr(chat_prompt_service, "retrieve_context", fake_retrieve)
    events = await _events(db, user)

    assert not any("retrieval" in event for event in events)
