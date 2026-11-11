"""Admin settings > Models > Forecasting models > Limits: the largest file the Forecast page reads and how long
one forecast may run. Stored in the database, so every pAIring server of a ring uses the same values; read per
request, so a change applies at once."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting
from app.schemas.forecast import ForecastLimits

KEY = "forecast_limits"


class ForecastLimitsSetting:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self) -> ForecastLimits:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        return ForecastLimits(**row.value) if row else ForecastLimits()

    async def set(self, limits: ForecastLimits) -> ForecastLimits:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=KEY, value=limits.model_dump()))
        else:
            row.value = limits.model_dump()
        await self._db.commit()
        return limits
