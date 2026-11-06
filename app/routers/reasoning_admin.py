"""Admin settings > System > Reasoning: allow or block the chats' Reasoning option for everyone. Any signed-in user
may read it (the chat page hides the chip when off); only admins change it."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.settings import ReasoningSwitch
from app.services.auth_service import get_current_user, require_admin
from app.services.reasoning_setting import reasoning_setting

router = APIRouter(prefix="/api/settings/reasoning", tags=["settings"])


@router.get("", response_model=ReasoningSwitch)
async def get_setting(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> ReasoningSwitch:
    return ReasoningSwitch(enabled=await reasoning_setting.enabled(db))


@router.put("", response_model=ReasoningSwitch)
async def set_setting(
    body: ReasoningSwitch, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ReasoningSwitch:
    await reasoning_setting.set_enabled(db, body.enabled)
    return body
