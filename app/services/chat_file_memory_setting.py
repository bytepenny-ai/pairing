"""Admin settings > System > Chat > "Files in a chat": how long a file may be to stay whole in a chat's memory, and
whether questions about an earlier image show it to the vision model again (chat_follow_up.py). Stored in the
database, so every pAIring server of a ring uses it."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting
from app.schemas.chat_file_memory import ChatFileMemorySetting

KEY = "chat_file_memory"


class ChatFileMemorySettings:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self) -> ChatFileMemorySetting:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        return ChatFileMemorySetting(**row.value) if row else ChatFileMemorySetting()

    async def set(self, setting: ChatFileMemorySetting) -> ChatFileMemorySetting:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=KEY, value=setting.model_dump()))
        else:
            row.value = setting.model_dump()
        await self._db.commit()
        return setting
