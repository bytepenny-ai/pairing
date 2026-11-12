"""A reply stream's non-text chunks (split from reply_generation_service): MCP tool calls ({"tool": event}),
engine token counts ({"usage": ...}, into `stats`), prompt read progress ({"read_progress": ...}, moves the
reply's deadline: reply_deadline.py) and reasoning ({"reasoning": text}). Reasoning text isn't
kept, only its stages (reasoning_stages.py); the cross-instance delete check runs on these chunks too, as a
long reasoning phase has no reply text."""

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message
from app.services import reply_broadcast_service, reply_cross_instance_service, tool_event_service
from app.services.reasoning_stages import ReasoningStages
from app.services.reply_deadline import ReplyDeadline
from app.services.reply_stats import ReplyStats


class ReplySideEvents:
    CHECK_SECONDS = 0.4  # like reply_generation_service._FLUSH_INTERVAL_SECONDS for text

    def __init__(
        self,
        db: AsyncSession,
        message: Message,
        conversation_id: str,
        model: str | None = None,
        deadline: ReplyDeadline | None = None,
    ) -> None:
        self._db = db
        self._deadline = deadline
        self._message = message
        self._conversation_id = conversation_id
        self._stages = ReasoningStages()
        self._last_check = time.monotonic()
        self.stats = ReplyStats(model=model)
        self._read_shown = 0.0  # the read progress last shown, published again from 1% more

    def text(self) -> None:
        """Call on every text chunk."""
        self.stats.text()
        if self._deadline is not None:
            self._deadline.text()

    @staticmethod
    def read_fraction(progress: dict) -> float | None:
        """How much of the prompt's new part is read, 0 to 1: Matricxon sends {cached, read, total} (read excludes the
        cache), llama.cpp {cache, processed, total} (processed includes it)."""
        total = progress.get("total") or 0
        if "processed" in progress:
            cached, read = progress.get("cache") or 0, (progress.get("processed") or 0) - (progress.get("cache") or 0)
        else:
            cached, read = progress.get("cached") or 0, progress.get("read") or 0
        new = total - cached
        return min(max(read / new, 0.0), 1.0) if new > 0 else None

    async def handle(self, chunk: dict) -> bool:
        """True when the reply must stop: deleted, possibly through another instance."""
        if "tool" in chunk:
            await tool_event_service.record(self._db, self._message, chunk["tool"], self._conversation_id)
            return False
        if "usage" in chunk:
            self.stats.usage(chunk["usage"])
            return False
        if "read_progress" in chunk:  # the engine is still reading the prompt: not stuck
            if self._deadline is not None:
                self._deadline.progress()
            fraction = self.read_fraction(chunk["read_progress"])
            if fraction is not None and fraction - self._read_shown >= 0.01:
                self._read_shown = fraction
                reply_broadcast_service.publish_read_progress(self._conversation_id, fraction)
            return False
        text = chunk.get("reasoning")
        if isinstance(text, str) and self._stages.feed(text):
            reply_broadcast_service.publish_reasoning(self._conversation_id, list(self._stages.labels))
        now = time.monotonic()
        if now - self._last_check < self.CHECK_SECONDS:
            return False
        self._last_check = now
        return await reply_cross_instance_service.deleted_elsewhere(self._db, self._message)
