"""The stages that add what the question needs, each may embed it (one shared vector: question_vectors.py): the
notes and skills (prompt layout), earlier files, and the knowledge base."""

from app.services import chat_prompt_service, reply_broadcast_service
from app.services.chat_turn.sanitize import EnrichStage
from app.services.chat_turn.turn import ChatTurn
from app.services.prompt_layout.layouts import PromptLayouts
from app.services.rag_chat_settings import RagChatSettings


class LayoutStage(EnrichStage):
    """How the notes and skills go into the prompt (Admin settings > Inference > Prompt cache): may add an update or a
    skill's text to this message."""

    name = "layout"
    requires = frozenset({"follow_up", "has_image", "sees_images"})
    provides = frozenset({"layout"})

    async def run(self, turn: ChatTurn) -> list[str]:
        assert turn.follow_up is not None
        turn.layout = await PromptLayouts(turn.db).for_message(
            turn.conversation,
            turn.user.id,
            turn.message.id,
            turn.content,
            turn.follow_up.kept_ids,
            turn.has_image,
            turn.sees_images,
        )
        return []


class FollowUpStage(EnrichStage):
    """The trimmed history, earlier files searched for the question, and an earlier image to show again."""

    name = "follow_up"
    requires = frozenset({"follow_up", "question", "layout"})
    provides = frozenset({"plan", "reply_files"})

    async def run(self, turn: ChatTurn) -> list[str]:
        assert turn.follow_up is not None
        turn.plan = await turn.follow_up.plan(turn.question, turn.attachments, turn.layout)
        if turn.plan.compacting:  # the reply's waiting label says "Compacting cache..." (reply_broadcast_service)
            reply_broadcast_service.expect_compacting(turn.conversation.id)
        # An earlier image the question is about, shown to the vision model again (admin setting, off by default).
        image_again = turn.plan.image_again
        turn.reply_files = [*turn.attachments, image_again] if image_again else turn.attachments
        return turn.plan.notices


class SystemPromptStage(EnrichStage):
    """Notes, knowledge-base excerpts and attached files (chat_prompt_service.build_system_prompt). Excerpts and files
    get only the room the history leaves; what was cut comes back as notices."""

    name = "system_prompt"
    requires = frozenset({"params", "reserved_tokens", "plan", "reply_files", "layout", "question", "sees_images"})
    provides = frozenset({"system_prompt", "turn_context", "source_filenames", "params"})

    async def run(self, turn: ChatTurn) -> list[str]:
        assert turn.plan is not None and turn.layout is not None
        (
            turn.system_prompt,
            turn.turn_context,
            turn.source_filenames,
            notices,
            knowledge_excerpts,
        ) = await chat_prompt_service.build_system_prompt(
            turn.db,
            turn.conversation,
            turn.user,
            turn.question,
            turn.params,
            turn.reply_files,
            turn.plan.history,
            turn.reserved_tokens,
            turn.sees_images,
            turn.layout.system_prompt,
        )
        turn.params = {**turn.params, **turn.layout.reply_params()}
        if knowledge_excerpts and await RagChatSettings(turn.db).keep_excerpts():
            # Sent again with this message in later turns (chat_attachment_memory.history_text): the cache matches.
            turn.message.knowledge_excerpts = knowledge_excerpts
            await turn.db.commit()
        return notices
