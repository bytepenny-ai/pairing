"""Admin settings > System > Reasoning: one switch that allows or blocks the chats' Reasoning option for everyone.
Off turns reasoning off in every chat and hides the chip (chat_thinking.js), e.g. on slow systems. Each chat keeps
its own saved choice, used again once the switch is back on. Read per reply, so a change applies from the next message.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting


class ReasoningSetting:
    KEY = "reasoning_enabled"
    DEFAULT = True

    async def enabled(self, db: AsyncSession) -> bool:
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, self.KEY))
        return bool(row.value.get("enabled", self.DEFAULT)) if row else self.DEFAULT

    async def set_enabled(self, db: AsyncSession, enabled: bool) -> None:
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, self.KEY))
        if row is None:
            db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=self.KEY, value={"enabled": enabled}))
        else:
            row.value = {"enabled": enabled}
        await db.commit()

    async def apply(self, db: AsyncSession, params: dict) -> dict:
        """`params` for one reply: think forced off while the switch is off; the chat's saved params are untouched."""
        return params if await self.enabled(db) else {**params, "think": False}


reasoning_setting = ReasoningSetting()
