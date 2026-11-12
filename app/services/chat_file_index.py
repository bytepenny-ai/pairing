"""A search index for one long chat attachment, so follow-up questions get just the parts of it that match.

A file longer than the admin's "keep whole" share of the context window (Admin settings > System > Chat > Files in a
chat) is split like a knowledge-base document (document_extract.chunk_text), each part embedded with the default
embedding model, and saved next to the file ("<file>.search.npz"; deleted with it). It belongs to that chat only:
nothing goes into the knowledge base. Built in the background after the first reply (schedule), or on the next
question if that is sooner (ensure).
"""

import asyncio
import logging
import os
from pathlib import Path

import numpy as np

from app.services.document_extract import chunk_text, extract_text
from app.services.inference_client import InferenceError, embed

logger = logging.getLogger(__name__)

_INDEX_SUFFIX = ".search.npz"


class ChatFileIndex:
    # Builds running in this process, so a question arriving mid-build waits for it instead of starting another.
    _building: dict[Path, asyncio.Task] = {}

    @staticmethod
    def index_path(path: Path) -> Path:
        return path.with_name(path.name + _INDEX_SUFFIX)

    @classmethod
    def schedule(cls, path: Path, embedding_model: str) -> None:
        """Starts building in the background (no-op when built or building)."""
        if path in cls._building or cls._load(path, embedding_model) is not None:
            return
        task = asyncio.create_task(cls._build(path, embedding_model))
        cls._building[path] = task
        task.add_done_callback(lambda _task: cls._building.pop(path, None))

    @classmethod
    async def ensure(cls, path: Path, embedding_model: str) -> None:
        """Waits for a running build, or builds now when there is none."""
        if cls._load(path, embedding_model) is not None:
            return
        running = cls._building.get(path)
        if running is not None:
            await asyncio.shield(running)
            return
        await cls._build(path, embedding_model)

    @classmethod
    def search(
        cls, files: list[tuple[Path, str]], query_vector: np.ndarray, embedding_model: str, top_k: int
    ) -> list[tuple[float, str, str]]:
        """The `top_k` parts most like the question, best first, as (similarity, filename, text). `files`: (path,
        filename)."""
        scored: list[tuple[float, str, str]] = []
        query = query_vector / (np.linalg.norm(query_vector) or 1.0)
        for path, filename in files:
            loaded = cls._load(path, embedding_model)
            if loaded is None or len(loaded[0]) == 0 or loaded[1].shape[1] != query.shape[0]:
                continue
            texts, vectors = loaded
            norms = np.linalg.norm(vectors, axis=1)
            scores = vectors @ query / np.where(norms == 0, 1.0, norms)
            scored += [(float(scores[i]), filename, str(texts[i])) for i in np.argsort(-scores)[:top_k]]
        scored.sort(key=lambda item: -item[0])
        return scored[:top_k]

    @classmethod
    async def _build(cls, path: Path, embedding_model: str) -> None:
        try:
            text = await asyncio.to_thread(lambda: extract_text(path.read_bytes(), path.suffix.lower()))
        except Exception as error:  # a missing or unreadable file leaves no index; the chat goes on without it
            logger.warning("Could not read %s to search it: %s", path.name, error)
            return
        kept_texts: list[str] = []
        vectors: list[list[float]] = []
        for piece in chunk_text(text):
            try:
                vectors.append(await embed(piece, embedding_model))
            except InferenceError:
                continue
            kept_texts.append(piece)
        if not vectors:
            logger.warning("No part of %s could be embedded with %s", path.name, embedding_model)
            return
        target = cls.index_path(path)
        temporary = target.with_name(target.name + ".tmp.npz")
        try:
            np.savez(
                temporary,
                texts=np.array(kept_texts),
                vectors=np.asarray(vectors, dtype=np.float32),
                model=np.array(embedding_model),
            )
            os.replace(temporary, target)
        except OSError as error:
            logger.warning("Could not save the search index of %s: %s", path.name, error)

    @classmethod
    def _load(cls, path: Path, embedding_model: str) -> tuple[np.ndarray, np.ndarray] | None:
        """(texts, vectors), or None when missing, unreadable or made with another embedding model."""
        try:
            with np.load(cls.index_path(path), allow_pickle=False) as data:
                if str(data["model"]) != embedding_model:
                    return None
                return data["texts"], data["vectors"]
        except (OSError, KeyError, ValueError):
            return None
