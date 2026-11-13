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
from app.schemas.chat_file_memory import ChatFileMemorySetting
from app.services import chat_history_service, model_catalog_service
from app.services.chat_attachment_memory import AttachmentMemory
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_file_index import ChatFileIndex
from app.services.chat_file_memory_setting import ChatFileMemorySettings
from app.services.image_relevance import ImageRelevance
from app.services.inference_client import InferenceError, embed
from app.services.prompt_layout.base import PromptLayout
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
# A short reply like "OK" or "thanks" needs no image: up to this many words, without "?" or a question word.
_SMALL_TALK_WORDS = 3
_ASKS = re.compile(
    r"^\s*(what|which|who|whose|where|when|why|how|is|are|was|were|does|do|did|can|could|would|will|should|tell|"
    r"describe|explain|show|count|list|name|find|read|compare|zoom)\b|^\s*(מה|איזה|איזו|אילו|כמה|למה|מדוע|איפה|מי|האם|תאר|ספר)",
    re.IGNORECASE,
)


@dataclass
class FollowUpPlan:
    history: list[dict]
    notices: list[str] = field(default_factory=list)
    image_again: AttachmentInfo | None = None  # shown to the vision model with this question
    image_if_needed: AttachmentInfo | None = None  # shown only if the chat's model asks for it (image_fallback_stream)


class ChatFollowUp:
    def __init__(
        self, db: AsyncSession, messages: list[Message], num_ctx: int, reserved_tokens: int, sees_images: bool = False
    ) -> None:
        """`messages`: the chat's history, ending with the message being answered. `sees_images`: the chat model reads
        images itself, so earlier ones go with their message and the image follow-up options don't apply."""
        self._sees_images = sees_images
        self._db = db
        self._messages = messages
        self._num_ctx = num_ctx
        self._reserved = reserved_tokens
        self._embedding_model: str | None = None
        self._memory = AttachmentMemory(current=messages[-1])
        self._question_vectors: dict[str, np.ndarray | None] = {}
        self._setting: ChatFileMemorySetting | None = None
        self._texts: dict[object, str] = {}

    async def prepare(self) -> ChatFileMemorySetting:
        """Reads the admin's setting and the embedding model, once (plan calls it too)."""
        if self._setting is None:
            self._setting = await ChatFileMemorySettings(self._db).get()
            self._embedding_model = await model_catalog_service.get_default_embedding_model(self._db)
            whole_limit = self._num_ctx * self._setting.whole_file_percent // 100
            self._memory = AttachmentMemory(
                current=self._messages[-1],
                whole_limit=whole_limit if self._embedding_model else None,
                images_inline=self._sees_images,
            )
            self._texts = {}
        return self._setting

    def _history_text(self, message: Message) -> str:
        """A message as the model reads it, worked out once per reply (it may read files)."""
        key = message.id or id(message)
        if key not in self._texts:
            self._texts[key] = self._memory.history_text(message)
        return self._texts[key]

    async def kept_ids(self, inserts: dict[str, str]) -> set[str]:
        """The messages the history window keeps when `inserts` (a prompt layout's, app/services/prompt_layout) go
        before their messages."""
        await self.prepare()
        text_of = PromptLayout.wrap(self._history_text, inserts)
        start = chat_history_service.window_start(self._messages, self._num_ctx, self._reserved, text_of)
        return {m.id for m in self._messages[start:]}

    async def plan(
        self, question: str, attachments: list[AttachmentInfo], layout: PromptLayout | None = None
    ) -> FollowUpPlan:
        """`layout`: the reply's prompt layout, whose inserts go before their messages."""
        setting = await self.prepare()
        whole_limit = self._num_ctx * setting.whole_file_percent // 100
        text_of = layout.text_of(self._history_text) if layout else self._history_text
        images_of = self._memory.images_of if self._sees_images else None
        notes_of = layout.notes_of if layout else None  # the app's tool results before messages (tool models)
        start = chat_history_service.window_start(self._messages, self._num_ctx, self._reserved, text_of, notes_of)
        plan = FollowUpPlan(
            chat_history_service.trim_history(
                self._messages, self._num_ctx, self._reserved, text_of, images_of, notes_of
            )
        )
        forgotten = self._memory.forgotten_notice(self._messages, self._last_window_start(text_of), start)
        if forgotten:
            plan.notices.append(forgotten)
        self._prepend(plan.history, AttachmentMemory.summaries(self._messages, start), first=True)
        excerpts = await self._excerpts(question, whole_limit, setting.unrelated_below)
        insert = layout.inserts.get(self._messages[-1].id, "") if layout else ""
        self._prepend(plan.history, excerpts, first=False, insert=insert)
        if not self._sees_images and not any(a.type == "image" for a in attachments):
            if setting.image_follow_up == "again":
                plan.image_again = await self._earlier_image(question, setting)
            elif setting.image_follow_up == "fallback":
                plan.image_if_needed = await self._earlier_image(question, setting, any_question=True)
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

    async def _excerpts(self, question: str, budget_tokens: int, unrelated_below: float) -> str:
        """The parts of earlier long files that match the question; none for a short reply ("OK") or when even the
        best part is unrelated in meaning (under the admin's mark)."""
        files = self._memory.long_files(self._messages) if self._embedding_model else []
        if not files or not question.strip() or self.is_small_talk(question):
            return ""
        try:
            for path, _filename in files:
                await ChatFileIndex.ensure(path, self._embedding_model)
        except InferenceError as error:
            logger.warning("Could not search this chat's files: %s", error)
            return ""
        query = await self._question_vector(question)
        if query is None:
            return ""
        blocks = []
        for score, filename, text in ChatFileIndex.search(files, query, self._embedding_model, _MAX_EXCERPTS):
            if score < unrelated_below:
                break
            cost = TokenEstimate.of(text)
            if cost > budget_tokens:
                break
            budget_tokens -= cost
            blocks.append(f"### From {filename}\n{text}")
        if not blocks:
            return ""
        return "The parts of files attached earlier in this chat that match this question:\n\n" + "\n\n".join(blocks)

    async def _question_vector(self, question: str) -> np.ndarray | None:
        """The question's embedding, once per reply (file search and image relevance share it)."""
        if question not in self._question_vectors:
            try:
                vector = np.asarray(await embed(question, self._embedding_model), dtype=np.float32)
            except InferenceError as error:
                logger.warning("Could not embed the question: %s", error)
                vector = None
            self._question_vectors[question] = vector
        return self._question_vectors[question]

    async def _earlier_image(
        self, question: str, setting: ChatFileMemorySetting, any_question: bool = False
    ) -> AttachmentInfo | None:
        """The chat's latest image, when the question needs it. Short replies ("OK") never do. With an embedding model,
        a question close in meaning to the image's description always does and an unrelated one never does
        (image_relevance.py); in between, or without one: while the image is among the last few questions, or when the
        question names a picture."""
        if self.is_small_talk(question):
            return None
        found = self._latest_image()
        if found is None:
            return None
        image, back, description = found
        if self._embedding_model and question.strip():
            vector = await self._question_vector(question)
            score = None
            if vector is not None:
                score = await ImageRelevance(self._embedding_model).score(vector, image.path, description)
            if score is not None and score >= setting.related_above:
                return image
            if score is not None and score < setting.unrelated_below:
                return None
        recent = any_question or back < _RECENT_QUESTIONS
        return image if recent or _ABOUT_AN_IMAGE.search(question) else None

    def _latest_image(self) -> tuple[AttachmentInfo, int, str] | None:
        """(the image, how many questions back it was sent, its description: the message's words and the reply)."""
        back = 0
        for index in range(len(self._messages) - 2, -1, -1):
            message = self._messages[index]
            if message.role != "user":
                continue
            for attachment in reversed(message.attachments or []):
                path = self._memory.path_of(attachment)
                if attachment.type == "image" and path.exists():
                    reply = next((m for m in self._messages[index + 1 :] if m.role == "assistant"), None)
                    words = "" if message.content.lstrip().startswith("/") else message.content
                    description = "\n".join(t for t in (words, reply.content if reply else "") if t.strip())
                    return AttachmentInfo(path=path, filename=attachment.filename, type="image"), back, description
            back += 1
        return None

    @staticmethod
    def is_small_talk(question: str) -> bool:
        """ "OK", "thanks a lot", "great!": short, with no "?" and no question word."""
        return len(question.split()) <= _SMALL_TALK_WORDS and "?" not in question and not _ASKS.search(question)

    @staticmethod
    def _prepend(history: list[dict], text: str, first: bool, insert: str = "") -> None:
        """Puts `text` before the first (or the newest) user message; a first that isn't a user turn gets one. On the
        newest, after its prompt-layout `insert` (PromptLayout.add_after_insert)."""
        if not text or not history:
            return
        users = [m for m in history if m["role"] == "user"]
        target = users[0] if first else users[-1]
        if first and history[0]["role"] != "user":
            history.insert(0, {"role": "user", "content": text})
            return
        target["content"] = PromptLayout.add_after_insert(target["content"], insert, text)
