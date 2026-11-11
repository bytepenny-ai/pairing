"""What a reply needs from the chat's earlier attachments (chat_service.build_reply_stream): the trimmed history with
earlier files in it (chat_attachment_memory.py), summaries of files that left the window, the parts of long files
that match the question (chat_file_index.py), and an earlier image shown to the vision model again when the question
is about it and the admin allows it (Admin settings > System > Chat > Files in a chat).
"""

import logging
import re
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message
from app.services import chat_history_service, model_catalog_service
from app.services.chat_attachment_memory import AttachmentMemory
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_file_index import ChatFileIndex
from app.services.chat_file_memory_setting import ChatFileMemorySettings
from app.services.inference_client import InferenceError, embed
from app.services.turn_context_fit import TokenEstimate

logger = logging.getLogger(__name__)

_MAX_EXCERPTS = 8
# An image among this many of the latest earlier questions is shown again for any question (setting on).
_RECENT_QUESTIONS = 3
# A question about a picture: "in the image", "what colour is…", "בתמונה".
_ABOUT_AN_IMAGE = re.compile(
    r"\b(image|picture|photo|pic|screenshot|diagram|drawing|logo|colou?rs?|shown)\b|תמונה|בתמונה|צילום|צבע",
    re.IGNORECASE,
)


@dataclass
class FollowUpPlan:
    history: list[dict]
    notices: list[str] = field(default_factory=list)
    image_again: AttachmentInfo | None = None  # shown to the vision model with this question
    image_if_needed: AttachmentInfo | None = None  # shown only if the chat's model asks for it (image_fallback_stream)


class ChatFollowUp:
    def __init__(self, db: AsyncSession, messages: list[Message], num_ctx: int, reserved_tokens: int) -> None:
        """`messages`: the chat's history, ending with the message being answered."""
        self._db = db
        self._messages = messages
        self._num_ctx = num_ctx
        self._reserved = reserved_tokens
        self._embedding_model: str | None = None
        self._memory = AttachmentMemory(current=messages[-1])

    async def plan(self, question: str, attachments: list[AttachmentInfo]) -> FollowUpPlan:
        setting = await ChatFileMemorySettings(self._db).get()
        self._embedding_model = await model_catalog_service.get_default_embedding_model(self._db)
        whole_limit = self._num_ctx * setting.whole_file_percent // 100
        self._memory = AttachmentMemory(
            current=self._messages[-1], whole_limit=whole_limit if self._embedding_model else None
        )
        text_of = self._memory.history_text
        start = chat_history_service.window_start(self._messages, self._num_ctx, self._reserved, text_of)
        plan = FollowUpPlan(chat_history_service.trim_history(self._messages, self._num_ctx, self._reserved, text_of))
        forgotten = self._memory.forgotten_notice(self._messages, self._last_window_start(text_of), start)
        if forgotten:
            plan.notices.append(forgotten)
        self._prepend(plan.history, AttachmentMemory.summaries(self._messages, start), first=True)
        self._prepend(plan.history, await self._excerpts(question, whole_limit), first=False)
        if not any(a.type == "image" for a in attachments):
            if setting.image_follow_up == "again":
                plan.image_again = self._earlier_image(question)
            elif setting.image_follow_up == "fallback":
                plan.image_if_needed = self._earlier_image(question, any_question=True)
        return plan

    def schedule_indexing(self, attachments: list[AttachmentInfo]) -> None:
        """After the reply: makes this message's long files searchable for the questions that follow."""
        if self._embedding_model is None:
            return
        for attachment in attachments:
            if attachment.type == "text" and self._memory.is_long(attachment.path):
                ChatFileIndex.schedule(attachment.path, self._embedding_model)

    def _last_window_start(self, text_of: chat_history_service.TextOf) -> int:
        """Where the last reply's history started (the messages up to the previous question)."""
        earlier = self._messages[:-1]
        while earlier and earlier[-1].role != "user":
            earlier = earlier[:-1]
        return chat_history_service.window_start(earlier, self._num_ctx, self._reserved, text_of) if earlier else 0

    async def _excerpts(self, question: str, budget_tokens: int) -> str:
        files = self._memory.long_files(self._messages) if self._embedding_model else []
        if not files or not question.strip():
            return ""
        try:
            for path, _filename in files:
                await ChatFileIndex.ensure(path, self._embedding_model)
            query = np.asarray(await embed(question, self._embedding_model), dtype=np.float32)
        except InferenceError as error:
            logger.warning("Could not search this chat's files: %s", error)
            return ""
        blocks = []
        for filename, text in ChatFileIndex.search(files, query, self._embedding_model, _MAX_EXCERPTS):
            cost = TokenEstimate.of(text)
            if cost > budget_tokens:
                break
            budget_tokens -= cost
            blocks.append(f"### From {filename}\n{text}")
        if not blocks:
            return ""
        return "The parts of files attached earlier in this chat that match this question:\n\n" + "\n\n".join(blocks)

    def _earlier_image(self, question: str, any_question: bool = False) -> AttachmentInfo | None:
        """The chat's latest image: always while it is among the last few questions ("what kind of bird is that?"),
        later only when the question names a picture."""
        asked = [m for m in self._messages[:-1] if m.role == "user"]
        for back, message in enumerate(reversed(asked)):
            for attachment in reversed(message.attachments or []):
                path = self._memory.path_of(attachment)
                if attachment.type == "image" and path.exists():
                    recent = any_question or back < _RECENT_QUESTIONS
                    found = AttachmentInfo(path=path, filename=attachment.filename, type="image")
                    return found if recent or _ABOUT_AN_IMAGE.search(question) else None
        return None

    @staticmethod
    def _prepend(history: list[dict], text: str, first: bool) -> None:
        """Puts `text` before the first (or the newest) user message; a first that isn't a user turn gets one."""
        if not text or not history:
            return
        users = [m for m in history if m["role"] == "user"]
        target = users[0] if first else users[-1]
        if first and history[0]["role"] != "user":
            history.insert(0, {"role": "user", "content": text})
            return
        target["content"] = f"{text}\n\n---\n\n{target['content']}"
