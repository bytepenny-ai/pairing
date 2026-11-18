"""Knowledge in chats: its settings, admin route and the search cutoff."""

import numpy as np
import pytest
from pydantic import ValidationError

from app.config import RAG_KEEP_EXCERPTS, RAG_MIN_SIMILARITY
from app.models import Chunk, Document
from app.routers import rag_chat_admin
from app.schemas.rag_chat import RagChatSetting
from app.services.chunk_vector_index import ChunkVectorIndex
from app.services.document_ingest import vector_to_bytes
from app.services.rag_chat_settings import RagChatSettings


async def _add(db, name: str, vector: list[float]) -> str:
    document = Document(filename=f"x/{name}", content_hash=name, owner_id=None, embedding_model="emb", chunk_count=1)
    db.add(document)
    await db.flush()
    chunk = Chunk(document_id=document.id, text=name, embedding=vector_to_bytes(np.asarray(vector, dtype=np.float32)))
    db.add(chunk)
    await db.commit()
    return chunk.id


@pytest.mark.asyncio
async def test_defaults_until_an_admin_saves(db):
    settings = RagChatSettings(db)
    assert await settings.min_similarity() == RAG_MIN_SIMILARITY
    assert await settings.keep_excerpts() is RAG_KEEP_EXCERPTS
    await settings.save(0.4, False)
    await settings.save(0.5, False)
    assert (await settings.min_similarity(), await settings.keep_excerpts()) == (0.5, False)


@pytest.mark.asyncio
async def test_admin_route_reads_and_saves(db):
    current = await rag_chat_admin.get_rag_chat(db=db, _admin=None)
    assert (current.min_similarity, current.keep_excerpts) == (RAG_MIN_SIMILARITY, RAG_KEEP_EXCERPTS)
    body = RagChatSetting(min_similarity=0.3, keep_excerpts=False)
    saved = await rag_chat_admin.set_rag_chat(body, db=db, _admin=None)
    assert (saved.min_similarity, saved.keep_excerpts) == (0.3, False)


def test_out_of_range_similarity_is_refused():
    for value in (1.5, -0.1):
        with pytest.raises(ValidationError):
            RagChatSetting(min_similarity=value, keep_excerpts=True)


@pytest.mark.asyncio
async def test_search_leaves_out_matches_below_the_cutoff(db):
    near = await _add(db, "near", [1.0, 0.1])
    await _add(db, "far", [0.0, 1.0])
    index = ChunkVectorIndex()
    query = np.asarray([1.0, 0.0], dtype=np.float32)

    assert len(await index.search(db, query, None, "emb", 5)) == 2
    assert await index.search(db, query, None, "emb", 5, min_score=0.5) == [near]
    assert await index.search(db, query, None, "emb", 5, min_score=0.999) == []
    scored = await index.scored(db, query, None, "emb", 5)
    assert [chunk_id for chunk_id, _ in scored][0] == near and scored[0][1] == pytest.approx(0.995, abs=0.001)
