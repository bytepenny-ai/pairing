"""Lists under "Sources" only the documents a reply used (Admin settings > Inference > RAG > Knowledge in chats).

Search sends the closest passages, and the model may ignore them. After the reply, its parts are embedded with the
embedding model that embedded the excerpts, and a document stays a source if one part is close enough to one of its
excerpts (RagChatSettings.source_min_similarity). Off, or if anything fails: every searched document stays."""

import logging
import re

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RAG_CHUNK_SIZE, RAG_SOURCE_CHECK_PARTS
from app.models import Chunk
from app.services import model_catalog_service
from app.services.inference_client import InferenceError, embed
from app.services.rag_chat_settings import RagChatSettings

logger = logging.getLogger("llama_chat")

_BREAKS = re.compile(r"(?<=[.!?。])\s+|\n+")  # sentence ends and line breaks


class KnowledgeSourceCheck:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def used(self, reply: str, sources: list[dict]) -> list[dict]:
        """`sources` ({name, id, score, chunks}) as saved and shown, without chunks: those the reply used if the
        check is on."""
        shown = [{key: value for key, value in source.items() if key != "chunks"} for source in sources]
        settings = RagChatSettings(self._db)
        if not shown or not reply.strip() or not await settings.check_sources():
            return shown
        try:
            keep = await self._close_documents(reply, sources, await settings.source_min_similarity())
        except InferenceError as exc:
            logger.warning("Source check failed, listing every searched document: %s", exc)
            return shown
        return shown if keep is None else [source for source in shown if source["id"] in keep]

    async def _close_documents(self, reply: str, sources: list[dict], minimum: float) -> set[str] | None:
        """Ids of the documents with an excerpt at least `minimum` close to a reply part; None if it can't tell."""
        chunk_ids = [chunk_id for source in sources for chunk_id in source.get("chunks", [])]
        model = await model_catalog_service.get_default_embedding_model(self._db)
        if not chunk_ids or model is None:
            return None
        rows = (await self._db.execute(select(Chunk.document_id, Chunk.embedding).where(Chunk.id.in_(chunk_ids)))).all()
        if not rows:
            return None
        excerpts = self._unit(np.stack([np.frombuffer(row.embedding, dtype=np.float32) for row in rows]))
        parts = [np.asarray(await embed(part, model), dtype=np.float32) for part in self.parts(reply)]
        if any(part.shape[0] != excerpts.shape[1] for part in parts):
            return None  # the embedding model changed since these were stored
        best = (self._unit(np.stack(parts)) @ excerpts.T).max(axis=0)  # each excerpt's closest reply part
        return {row.document_id for row, score in zip(rows, best, strict=True) if score >= minimum}

    @staticmethod
    def parts(reply: str) -> list[str]:
        """The reply in pieces about one excerpt long, at most RAG_SOURCE_CHECK_PARTS, spread over a long reply."""
        pieces: list[str] = []
        for sentence in filter(None, (s.strip() for s in _BREAKS.split(reply))):
            if pieces and len(pieces[-1]) + len(sentence) < RAG_CHUNK_SIZE:
                pieces[-1] += " " + sentence
            else:
                pieces.append(sentence[: RAG_CHUNK_SIZE * 2])
        if len(pieces) <= RAG_SOURCE_CHECK_PARTS:
            return pieces
        step = len(pieces) / RAG_SOURCE_CHECK_PARTS
        return [pieces[int(index * step)] for index in range(RAG_SOURCE_CHECK_PARTS)]

    @staticmethod
    def _unit(vectors: np.ndarray) -> np.ndarray:
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
