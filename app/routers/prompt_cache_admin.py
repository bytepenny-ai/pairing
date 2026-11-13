"""Admin settings > Inference > Prompt cache (admin-only; prompt_cache_setting.py), and whether chats may change
their notes and skills after the first message (any user; the chat page asks)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.prompt_cache import MidChatChanges, PromptCacheSetting
from app.services.auth_service import get_current_user, require_admin
from app.services.prompt_cache_setting import PromptCacheSettings

router = APIRouter(prefix="/api/settings/prompt-cache", tags=["settings"])
chat_router = APIRouter(prefix="/api/prompt-cache", tags=["chat"])


@router.get("", response_model=PromptCacheSetting)
async def get_prompt_cache(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> PromptCacheSetting:
    return await PromptCacheSettings(db).get()


@router.put("", response_model=PromptCacheSetting)
async def set_prompt_cache(
    body: PromptCacheSetting, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> PromptCacheSetting:
    return await PromptCacheSettings(db).set(body)


@chat_router.get("/mid-chat-changes", response_model=MidChatChanges)
async def get_mid_chat_changes(
    db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> MidChatChanges:
    return await PromptCacheSettings(db).mid_chat_changes()
