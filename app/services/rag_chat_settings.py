"""How chats use the Knowledge base (Admin settings > Inference > RAG > Knowledge in chats): the relevance cutoff
(document_retrieval.py) and whether excerpts stay with their message for the prompt cache (chat_prompt_service.py)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RAG_KEEP_EXCERPTS, RAG_MIN_SIMILARITY
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

    async def save(self, min_similarity: float, keep_excerpts: bool) -> None:
        value = {"min_similarity": min_similarity, "keep_excerpts": keep_excerpts}
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, _KEY))
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=_KEY, value=value))
        else:
            row.value = value
        await self._db.commit()
