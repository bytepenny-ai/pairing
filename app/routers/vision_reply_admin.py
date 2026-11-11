"""Admin settings > Models > Default models: what a reply to an image includes (admin-only)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.vision_reply import VisionReplySetting
from app.services.auth_service import require_admin
from app.services.vision_reply_setting import VisionReplyContextSetting

router = APIRouter(prefix="/api/settings/vision-reply-context", tags=["settings"])


@router.get("", response_model=VisionReplySetting)
async def get_vision_reply_context(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> VisionReplySetting:
    return await VisionReplyContextSetting(db).get()


@router.put("", response_model=VisionReplySetting)
async def set_vision_reply_context(
    body: VisionReplySetting, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> VisionReplySetting:
    return await VisionReplyContextSetting(db).set(body)
