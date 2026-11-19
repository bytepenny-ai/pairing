"""GET /api/my-stats: the signed-in user's own usage (services/my_stats_service.py). Every user, not admin-only."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.my_stats import MyStatsOut
from app.services.auth_service import get_current_user
from app.services.my_stats_service import MyStats

router = APIRouter(prefix="/api/my-stats", tags=["stats"])


@router.get("", response_model=MyStatsOut)
async def get_my_stats(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> MyStatsOut:
    return await MyStats(db, user).summary()
