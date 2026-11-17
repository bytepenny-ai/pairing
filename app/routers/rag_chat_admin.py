"""Admin settings > Inference > RAG: Knowledge in chats (rag_chat_settings.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.rag_chat import RagChatSetting
from app.services.auth_service import require_admin
from app.services.rag_chat_settings import RagChatSettings

router = APIRouter(prefix="/api/settings", tags=["rag"])


async def _current(settings: RagChatSettings) -> RagChatSetting:
    return RagChatSetting(
        min_similarity=await settings.min_similarity(),
        keep_excerpts=await settings.keep_excerpts(),
        check_sources=await settings.check_sources(),
        source_min_similarity=await settings.source_min_similarity(),
    )


@router.get("/rag-chat", response_model=RagChatSetting)
async def get_rag_chat(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> RagChatSetting:
    return await _current(RagChatSettings(db))


@router.put("/rag-chat", response_model=RagChatSetting)
async def set_rag_chat(
    body: RagChatSetting, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> RagChatSetting:
    settings = RagChatSettings(db)
    await settings.save(body.min_similarity, body.keep_excerpts, body.check_sources, body.source_min_similarity)
    return await _current(settings)
