"""Admin settings > Inference > Prompt cache: how notes and skills are laid out for the engine's prompt cache
(app/services/prompt_layout). Stored in the database, so every pAIring server of a ring uses it."""

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting
from app.schemas.prompt_cache import MidChatChanges, PromptCacheSetting

KEY = "prompt_cache"


class PromptCacheSettings:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self) -> PromptCacheSetting:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        if row is None:
            return PromptCacheSetting()
        try:
            return PromptCacheSetting(**row.value)
        except (TypeError, ValidationError):  # a value saved by another version: the defaults, never a failed reply
            return PromptCacheSetting()

    async def mid_chat_changes(self) -> MidChatChanges:
        return (await self.get()).mid_chat_changes

    async def set(self, setting: PromptCacheSetting) -> PromptCacheSetting:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=KEY, value=setting.model_dump()))
        else:
            row.value = setting.model_dump()
        await self._db.commit()
        return setting
