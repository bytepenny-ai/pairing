"""How fast a model reads a prompt on this setup, for the "this file is long" warning (chat_attachment_check.py).

Each reply's stats keep the prompt tokens the engine actually read (not those reused from its cache), how long that
took, the model and the engine host (reply_stats.py). The speed is the median of a model's latest replies that read
enough to measure (small reads are mostly fixed overhead), per host: on a Matricxon cluster or several llama.cpp
hosts, nodes can differ a lot. A chat that already ran somewhere uses that host's speed (a chat stays on the node
holding its cache); a new chat assumes the slowest host, so the real wait is never longer than the warning. The
replies are in the shared database, so every pAIring server of a ring sees the same speeds.
"""

import statistics

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message

_SAMPLES = 20  # latest replies per model and host
_MIN_TOKENS = 100  # a read this short is mostly overhead, not reading speed
_SCAN = 500  # latest replies looked at


class ReadSpeed:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def tokens_per_second(self, model: str, conversation_id: str | None = None) -> float | None:
        """Prompt tokens per second for `model`, or None with no samples yet."""
        rows = (
            await self._db.execute(
                select(Message.conversation_id, Message.stats)
                .where(Message.role == "assistant", Message.stats.isnot(None))
                .order_by(Message.created_at.desc())
                .limit(_SCAN)
            )
        ).all()
        by_host: dict[str, list[float]] = {}
        chat_host = None
        for row_conversation, stats in rows:
            if not isinstance(stats, dict) or stats.get("model") != model:
                continue
            host = stats.get("host") or ""
            if chat_host is None and conversation_id and row_conversation == conversation_id:
                chat_host = host
            tokens, ms = stats.get("read_tokens") or 0, stats.get("read_ms") or 0
            if tokens >= _MIN_TOKENS and ms > 0 and len(by_host.setdefault(host, [])) < _SAMPLES:
                by_host[host].append(tokens / (ms / 1000))
        medians = {host: statistics.median(speeds) for host, speeds in by_host.items() if speeds}
        if not medians:
            return None
        if chat_host is not None and chat_host in medians:
            return medians[chat_host]
        return min(medians.values())

    @staticmethod
    def wait_words(seconds: float) -> str:
        """'about a minute', 'about 20 minutes', 'over an hour'."""
        minutes = round(seconds / 60)
        if minutes <= 1:
            return "about a minute"
        if minutes >= 60:
            return "over an hour"
        return f"about {minutes} minutes"
