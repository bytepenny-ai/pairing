"""Admin settings > Models > Default models > "Replies to an image include": the chat's notes and skills cost a
slow CPU minutes per image reply (a 3,300-character skill was 85% of one SmolVLM2 prompt), so an admin can leave
them out of replies to an image. Stored in the database, so every pAIring server of a ring uses it."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting
from app.schemas.vision_reply import VisionReplySetting

KEY = "vision_reply_context"


class VisionReplyContextSetting:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self) -> VisionReplySetting:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        return VisionReplySetting(**row.value) if row else VisionReplySetting()

    async def set(self, setting: VisionReplySetting) -> VisionReplySetting:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=KEY, value=setting.model_dump()))
        else:
            row.value = setting.model_dump()
        await self._db.commit()
        return setting

    async def includes(self, has_image: bool) -> tuple[bool, bool]:
        """(notes, skills) for this reply; a reply without an image always gets both."""
        if not has_image:
            return True, True
        include = (await self.get()).include
        return include in ("all", "notes"), include == "all"
