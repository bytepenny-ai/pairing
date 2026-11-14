"""Picks the admin's prompt layout (Admin settings > Inference > Prompt cache), runs it for a reply and saves what it
needs next time in the chat (`conversation.params["prompt_layout"]`). A layout that fails for any reason falls
back to "ordered" for that reply: a layout may cost a re-read, never a reply.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, User
from app.schemas.prompt_cache import PromptCacheSetting
from app.services import conversation_skills, mcp_settings_service, model_catalog_service, tool_loop_service
from app.services.chat_commands import ChatCommand
from app.services.chat_skill_command import SkillCommand
from app.services.prompt_cache_setting import PromptCacheSettings
from app.services.prompt_layout.append import AppendLayout
from app.services.prompt_layout.base import KeptIds, LayoutContext, PromptLayout, PromptStrategy
from app.services.prompt_layout.index import IndexLayout
from app.services.prompt_layout.ordered import BlockLayout, OrderedLayout
from app.services.prompt_layout.sections import PromptSection, PromptSections
from app.services.prompt_layout.skill_chat_tool import TOOL_INDEX_PARAM_KEY, SkillTool
from app.services.prompt_layout.skill_relevance import SkillRelevance

logger = logging.getLogger(__name__)

STATE_KEY = "prompt_layout"


async def _not_asked(_inserts: dict[str, str]) -> set[str]:
    """A read-only layout never checks the window (it changes nothing)."""
    return set()


class PromptLayouts:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def for_message(
        self,
        conversation: Conversation,
        user_id: str,
        message_id: str,
        content: str,
        kept: KeptIds,
        has_image: bool,
        sees_images: bool,
    ) -> PromptLayout:
        """The layout for answering a new message (`content` as the user wrote it): the vision model's own when it
        answers an image (the chat's model can't see it), else the chat's layout for the reply (`for_reply`)."""
        if has_image and not sees_images:
            return await self.for_image_reply(conversation, user_id)
        asked = SkillCommand.parse(content)[0]
        return await self.for_reply(
            conversation, user_id, message_id, ChatCommand.expand(content), kept, has_image, asked
        )

    async def for_reply(
        self,
        conversation: Conversation,
        user_id: str,
        message_id: str,
        question: str,
        kept: KeptIds,
        has_image: bool = False,
        asked_skill: str | None = None,
    ) -> PromptLayout:
        """The layout for answering `message_id`; may add an update or a skill to it, and saves the chat's state.
        `asked_skill`: the skill the message asks for with /use_skill."""
        return await self._run(conversation, user_id, message_id, question, kept, has_image, asked_skill)

    async def current(self, conversation: Conversation, user_id: str) -> PromptLayout:
        """The layout as saved, changing nothing: what the next reply's prompt starts with (the warm-up)."""
        return await self._run(conversation, user_id, None, "", _not_asked)

    async def for_image_reply(self, conversation: Conversation, user_id: str) -> PromptLayout:
        """A reply by the vision model: its own prompt and cache, so the notes and skills it is given, as they are."""
        sections = await PromptSections.load(self._db, conversation, user_id, has_image=True)
        return PromptLayout(sections.ordered_prompt())

    async def _run(
        self,
        conversation: Conversation,
        user_id: str,
        message_id: str | None,
        question: str,
        kept: KeptIds,
        has_image: bool = False,
        asked_skill: str | None = None,
    ) -> PromptLayout:
        sections = await PromptSections.load(self._db, conversation, user_id)
        saved = (conversation.params or {}).get(STATE_KEY)
        saved = saved if isinstance(saved, dict) else {}
        try:
            setting = await PromptCacheSettings(self._db).get()
            strategy = await self._strategy(setting)
            ctx = LayoutContext(sections, dict(saved), question, message_id, kept, has_image, asked_skill=asked_skill)
            if setting.mode == "index" and asked_skill:
                ctx.asked_section = await self._asked_section(conversation, user_id, sections, asked_skill)
            if setting.mode in ("index", "append"):  # they tell a tool model things as tool results
                await self._add_tools(ctx, conversation, skills=setting.mode == "index")
            layout, state = await strategy.layout(ctx)
        except Exception:
            logger.exception("The prompt layout failed for chat %s; using the plain order", conversation.id[:8])
            return PromptLayout(sections.ordered_prompt())
        if message_id is not None and state != saved:
            conversation.params = {**(conversation.params or {}), STATE_KEY: state}
            await self._db.commit()
        return layout

    async def _asked_section(
        self, conversation: Conversation, user_id: str, sections: PromptSections, asked: str
    ) -> PromptSection | None:
        """The skill /use_skill names when it isn't one of the chat's: one this user may use in this chat (the shared
        library, and their own outside a channel; conversation_skills.available), so a name can't reach any other."""
        if SkillTool.match(asked, [s.title for s in sections.of_kind("skill")]):
            return None  # one of the chat's: IndexNotes.asked finds it there
        user = await self._db.get(User, user_id)
        usable = {s.name: s for s in await conversation_skills.available(self._db, user, conversation)} if user else {}
        name = SkillTool.match(asked, usable)
        if name is None:
            return None
        skill = usable[name]
        return PromptSection(f"skill:{skill.id}", "skill", skill.name, skill.content.strip(), skill.description.strip())

    async def _add_tools(self, ctx: LayoutContext, conversation: Conversation, skills: bool) -> None:
        """Whether the model can call tools, and (`skills`) which skills earlier replies read with use_skill."""
        ctx.tools = await tool_loop_service.model_can_use_tools(conversation.model)
        if ctx.tools and await mcp_settings_service.get_enabled(self._db):  # the tool index (options 2 and 3)
            params = conversation.params or {}
            ctx.tools_on = bool(params.get("use_tools"))
            chat = {"use_tools": True, "conversation_id": conversation.id, TOOL_INDEX_PARAM_KEY: True}
            tools = await tool_loop_service.chat_mcp_tools(self._db, chat) if ctx.tools_on else []
            ctx.tool_specs = [t.definition() for t in tools]
        if skills and ctx.tools and not ctx.read_only:
            rows = await self._db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id, Message.tool_events.is_not(None))
                .order_by(Message.created_at)
            )
            ctx.skill_uses = SkillTool.uses(rows.scalars().all())

    async def _strategy(self, setting: PromptCacheSetting) -> PromptStrategy:
        if setting.mode == "append":
            return AppendLayout(setting)
        if setting.mode == "index":
            relevance = SkillRelevance(await model_catalog_service.get_default_embedding_model(self._db))
            return IndexLayout(setting, relevance)
        if setting.mode == "blocks":
            return BlockLayout(setting)
        return OrderedLayout(setting)
