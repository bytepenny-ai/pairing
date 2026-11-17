"""Sources a reply used (services/knowledge_source_check.py) and their admin settings (routers/rag_chat_admin.py)."""

import numpy as np
import pytest

from app.config import RAG_SOURCE_CHECK_PARTS
from app.models import Chunk, Document
from app.routers import rag_chat_admin
from app.schemas.rag_chat import RagChatSetting
from app.services import knowledge_source_check, model_catalog_service
from app.services.inference_client import InferenceError
from app.services.knowledge_source_check import KnowledgeSourceCheck
from app.services.rag_chat_settings import RagChatSettings

# Two directions in a 3-d space: a reply about "security" is close to doc A only.
_VECTORS = {"security": [1.0, 0.0, 0.0], "weather": [0.0, 1.0, 0.0]}


async def _source(db, name: str, vector: list[float]) -> dict:
    document = Document(filename=f"global/{name}", content_hash="h", chunk_count=1)
    db.add(document)
    await db.flush()
    chunk = Chunk(document_id=document.id, text=name, embedding=np.asarray(vector, dtype=np.float32).tobytes())
    db.add(chunk)
    await db.commit()
    return {"name": name, "id": document.id, "chunks": [chunk.id]}


@pytest.fixture
def fake_embed(monkeypatch):
    async def embed(text: str, model: str) -> list[float]:
        return next((v for word, v in _VECTORS.items() if word in text), [0.0, 0.0, 1.0])

    async def default_model(db) -> str:
        return "embed"

    monkeypatch.setattr(knowledge_source_check, "embed", embed)
    monkeypatch.setattr(model_catalog_service, "get_default_embedding_model", default_model)


@pytest.mark.asyncio
async def test_only_documents_the_reply_is_close_to_stay(db, fake_embed) -> None:
    a = await _source(db, "a.pdf", _VECTORS["security"])
    b = await _source(db, "b.pdf", _VECTORS["weather"])
    used = await KnowledgeSourceCheck(db).used("Some intro.\nAbout security here.", [a, b])
    assert used == [{"name": "a.pdf", "id": a["id"]}]
    assert await KnowledgeSourceCheck(db).used("Nothing related.", [a, b]) == []


@pytest.mark.asyncio
async def test_off_or_failing_lists_every_searched_document(db, fake_embed, monkeypatch) -> None:
    a = await _source(db, "a.pdf", _VECTORS["security"])
    b = await _source(db, "b.pdf", _VECTORS["weather"])
    every = [{"name": "a.pdf", "id": a["id"]}, {"name": "b.pdf", "id": b["id"]}]
    await RagChatSettings(db).save(0.39, False, check_sources=False)
    assert await KnowledgeSourceCheck(db).used("About security.", [a, b]) == every

    await RagChatSettings(db).save(0.39, False, check_sources=True)

    async def broken(text: str, model: str) -> list[float]:
        raise InferenceError("engine busy")

    monkeypatch.setattr(knowledge_source_check, "embed", broken)
    assert await KnowledgeSourceCheck(db).used("About security.", [a, b]) == every


def test_a_long_reply_is_checked_in_a_few_parts_spread_over_it() -> None:
    reply = " ".join(f"Sentence number {i} is here and is quite long, to fill the parts quickly." for i in range(300))
    parts = KnowledgeSourceCheck.parts(reply)
    assert len(parts) == RAG_SOURCE_CHECK_PARTS
    assert "number 0 " in parts[0] and "number 0 " not in parts[-1]  # the end is checked too
    assert KnowledgeSourceCheck.parts("One. Two.") == ["One. Two."]


@pytest.mark.asyncio
async def test_admin_saves_the_check_and_its_cutoff(db, admin_user) -> None:
    default = await rag_chat_admin.get_rag_chat(db, admin_user)
    assert default.check_sources is True and default.source_min_similarity == 0.45
    body = RagChatSetting(min_similarity=0.4, keep_excerpts=False, check_sources=False, source_min_similarity=0.5)
    saved = await rag_chat_admin.set_rag_chat(body, db, admin_user)
    assert (saved.check_sources, saved.source_min_similarity, saved.min_similarity) == (False, 0.5, 0.4)
