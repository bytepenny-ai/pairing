"""How chats use the Knowledge base (Admin settings > Inference > RAG > Knowledge in chats): the relevance cutoff
(document_retrieval.py), whether excerpts stay with their message for the prompt cache (chat_prompt_service.py), and
the check that lists only the documents a reply used (knowledge_source_check.py)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RAG_CHECK_SOURCES, RAG_KEEP_EXCERPTS, RAG_MIN_SIMILARITY, RAG_SOURCE_MIN_SIMILARITY
from app.models import SYSTEM_OWNER_ID, AppSetting

_KEY = "rag_chat"


class RagChatSettings:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _value(self) -> dict:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, _KEY))
        return dict(row.value) if row is not None else {}

    async def min_similarity(self) -> float:
        """The lowest cosine similarity a passage needs; the default until an admin saves one."""
        value = (await self._value()).get("min_similarity")
        return RAG_MIN_SIMILARITY if value is None else float(value)

    async def keep_excerpts(self) -> bool:
        """Whether a message's excerpts are saved and sent again with it in later turns."""
        value = (await self._value()).get("keep_excerpts")
        return RAG_KEEP_EXCERPTS if value is None else bool(value)

    async def check_sources(self) -> bool:
        """Whether a finished reply is compared with its excerpts, to list only the documents it used."""
        value = (await self._value()).get("check_sources")
        return RAG_CHECK_SOURCES if value is None else bool(value)

    async def source_min_similarity(self) -> float:
        """How close a reply part must be to a document's excerpt for that document to stay a source."""
        value = (await self._value()).get("source_min_similarity")
        return RAG_SOURCE_MIN_SIMILARITY if value is None else float(value)

    async def save(
        self,
        min_similarity: float,
        keep_excerpts: bool,
        check_sources: bool = RAG_CHECK_SOURCES,
        source_min_similarity: float = RAG_SOURCE_MIN_SIMILARITY,
    ) -> None:
        value = {
            "min_similarity": min_similarity,
            "keep_excerpts": keep_excerpts,
            "check_sources": check_sources,
            "source_min_similarity": source_min_similarity,
        }
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, _KEY))
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=_KEY, value=value))
        else:
            row.value = value
        await self._db.commit()
