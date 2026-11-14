"""The last stages before the model: the messages it is sent, which model answers, the image fallback, and a final
check that the question is still there."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message
from app.services import chat_attachment_service, chat_prompt_service, model_catalog_service
from app.services.chat_turn.sanitize import AssembleStage, CheckStage
from app.services.chat_turn.turn import ChatTurn
from app.services.image_fallback_stream import ImageFallback, image_question


class MessagesStage(AssembleStage):
    """The system message, then the history with this turn's excerpts and files on the newest user message."""

    name = "messages"
    requires = frozenset({"plan", "layout", "system_prompt", "turn_context", "question"})
    provides = frozenset({"chat_messages"})

    async def run(self, turn: ChatTurn) -> list[str]:
        assert turn.plan is not None and turn.layout is not None
        history = turn.plan.history
        chat_prompt_service.prepend_turn_context(
            history, turn.turn_context, turn.layout.inserts.get(turn.message.id, "")
        )
        # Always sent, even when "": an explicit empty system message tells the engine there is no preamble, whereas
        # omitting it makes some chat-template layers (e.g. Matricxon's VicunaPromptBuilder) add their own default.
        turn.chat_messages = [{"role": "system", "content": turn.system_prompt}] + history
        if turn.plan.image_again:  # the vision model needs the image and the question, not the chat (image_question)
            turn.chat_messages = image_question(turn.system_prompt, turn.question)
        return []


class ModelSwitchStage(AssembleStage):
    """Which model answers: the chat's (an image on the message when it sees images), or the default vision model for
    this reply only. The chat's stored model is corrected when the engine no longer knows it."""

    name = "model_switch"
    requires = frozenset({"sees_images", "reply_files", "chat_messages"})
    provides = frozenset({"reply_model"})

    async def run(self, turn: ChatTurn) -> list[str]:
        if turn.sees_images:
            chat_attachment_service.attach_image(turn.reply_files, turn.chat_messages)
            turn.reply_model = None
        elif turn.reply_files:
            turn.reply_model = await chat_attachment_service.apply_image_attachment(
                turn.db, turn.reply_files, turn.chat_messages
            )
        if turn.reply_model is None:
            # get_default_vision_model only returns installed models, so only the chat's model needs checking
            # (resolve_installed_model: an engine switch can leave the stored tag unknown to the new engine).
            resolved = await model_catalog_service.resolve_installed_model(turn.db, turn.user, turn.conversation.model)
            if resolved != turn.conversation.model:
                turn.conversation.model = resolved
                await turn.db.commit()
        return []


class ImageFallbackStage(AssembleStage):
    """ "Description first, image if needed": the chat's model may hand over to the vision model."""

    name = "image_fallback"
    requires = frozenset({"plan", "chat_messages", "question"})
    provides = frozenset({"fallback"})

    async def run(self, turn: ChatTurn) -> list[str]:
        assert turn.plan is not None
        if turn.plan.image_if_needed:
            vision_system = await chat_prompt_service.notes_and_skills_prompt(
                turn.db, turn.conversation, turn.user.id, True
            )
            vision_messages = image_question(vision_system, turn.question)
            turn.fallback = await ImageFallback.prepare(
                turn.db, turn.plan.image_if_needed, turn.chat_messages, vision_messages
            )
        return []


class StillAskedStage(CheckStage):
    """Preparing can take a while (a long file to search first): a question deleted meanwhile (a channel post, or the
    whole chat) gets no reply, else the engine would read the prompt for nobody."""

    name = "still_asked"

    async def run(self, turn: ChatTurn) -> list[str]:
        turn.stopped = not await self.still_asked(turn.db, turn.message.id)
        return []

    @staticmethod
    async def still_asked(db: AsyncSession, message_id: str) -> bool:
        """Read from the database, not the session's cached object: deleted alone (status "deleted") or with its chat
        (no row)?"""
        found = await db.execute(select(Message.status).where(Message.id == message_id))
        status = found.scalar_one_or_none()
        return status is not None and status != "deleted"
