"""The first stages of a reply: the chat command removed, the params set, the history the model may see, and the
context window it must fit in."""

from app.services import (
    channel_history_setting,
    chat_history_service,
    context_window_setting,
    conversation_service,
    model_catalog_service,
)
from app.services.chat_commands import ChatCommand
from app.services.chat_follow_up import ChatFollowUp
from app.services.chat_turn.sanitize import AdjustStage, CleanStage
from app.services.chat_turn.turn import ChatTurn
from app.services.reasoning_setting import reasoning_setting


class ParamsStage(AdjustStage):
    name = "params"
    provides = frozenset({"params", "reserved_tokens"})

    async def run(self, turn: ChatTurn) -> list[str]:
        # num_ctx is one system-wide value (Settings > System > Context window).
        params = {**turn.conversation.params, "num_ctx": await context_window_setting.get_num_ctx(turn.db)}
        # Reasoning may be blocked for everyone (Admin settings > System > Reasoning).
        turn.params = await reasoning_setting.apply(turn.db, params)
        # Room for a full reply (num_predict); else a long chat cuts the reply short.
        turn.reserved_tokens = max(512, turn.params.get("num_predict", 0))
        return []


class HistoryStage(AdjustStage):
    """The chat's visible messages (admin-deleted ones left out)."""

    name = "history"
    provides = frozenset({"past"})

    async def run(self, turn: ChatTurn) -> list[str]:
        turn.past = conversation_service.visible_messages(turn.conversation)
        return []


class ChannelHistoryStage(HistoryStage):
    """A channel may keep only the posts addressed to the AI (Admin settings > channel history)."""

    async def run(self, turn: ChatTurn) -> list[str]:
        await super().run(turn)
        if not await channel_history_setting.get_include_plain_messages(turn.db):
            turn.past = chat_history_service.only_addressed_to_ai(turn.past)
        return []


class ModelCheckStage(AdjustStage):
    """Whether the chat's model reads images itself (Matricxon's gemma 4): then it answers them too, with no switch to
    the vision model, and earlier images stay with their messages so its prompt cache keeps matching."""

    name = "model_check"
    provides = frozenset({"sees_images"})

    async def run(self, turn: ChatTurn) -> list[str]:
        turn.sees_images = await model_catalog_service.sees_images(turn.conversation.model)
        return []


class WindowStage(AdjustStage):
    """The history window and earlier files (chat_follow_up.py). The current message is added explicitly: with
    expire_on_commit=False (app/database.py) the loaded `conversation.messages` doesn't have it."""

    name = "window"
    requires = frozenset({"params", "reserved_tokens", "past", "sees_images"})
    provides = frozenset({"follow_up"})

    async def run(self, turn: ChatTurn) -> list[str]:
        turn.follow_up = ChatFollowUp(
            turn.db,
            [*chat_history_service.without_failed_replies(turn.past), turn.message],
            turn.params["num_ctx"],
            turn.reserved_tokens,
            turn.sees_images,
        )
        return []


class CommandStage(CleanStage):
    """The question without its chat command (/summarize, /use_skill…), and whether it comes with an image."""

    name = "command"
    provides = frozenset({"question", "has_image"})

    async def run(self, turn: ChatTurn) -> list[str]:
        turn.question = ChatCommand.expand(turn.content)
        turn.has_image = any(a.type == "image" for a in turn.attachments)
        return []
