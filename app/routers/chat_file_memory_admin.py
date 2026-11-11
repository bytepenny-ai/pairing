"""Admin settings > System > Chat > "Files in a chat" (admin-only; chat_file_memory_setting.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.chat_file_memory import ChatFileMemorySetting
from app.services.auth_service import require_admin
from app.services.chat_file_memory_setting import ChatFileMemorySettings

router = APIRouter(prefix="/api/settings/chat-file-memory", tags=["settings"])


@router.get("", response_model=ChatFileMemorySetting)
async def get_chat_file_memory(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ChatFileMemorySetting:
    return await ChatFileMemorySettings(db).get()


@router.put("", response_model=ChatFileMemorySetting)
async def set_chat_file_memory(
    body: ChatFileMemorySetting, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ChatFileMemorySetting:
    return await ChatFileMemorySettings(db).set(body)
