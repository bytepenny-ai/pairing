"""The time-based part of My stats: messages per day and reply speed over the last days, for one user.

Reads only timestamps and each reply's stats (reply_stats.py) inside the window, so the work stays bounded.
Days follow the user's own time zone.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Message, User
from app.models._base import utcnow
from app.schemas.my_stats import MyDay, MyReplySpeed

DAYS = 30


class MyActivity:
    def __init__(self, db: AsyncSession, user: User, days: int = DAYS) -> None:
        self.db = db
        self.user = user
        self.days = days
        self.since = utcnow() - timedelta(days=days)

    async def per_day(self) -> list[MyDay]:
        """Messages this user sent on each of the last days, oldest first, days without any included."""
        rows = await self.db.execute(
            select(Message.created_at).where(
                Message.role == "user", Message.sender_id == self.user.id, Message.created_at > self.since
            )
        )
        zone = self._zone()
        counts: dict[date, int] = {}
        for (created,) in rows:
            day = self._aware(created).astimezone(zone).date()
            counts[day] = counts.get(day, 0) + 1
        today = datetime.now(zone).date()
        return [
            MyDay(day=day, messages=counts.get(day, 0))
            for day in (today - timedelta(days=n) for n in range(self.days - 1, -1, -1))
        ]

    async def speed(self) -> MyReplySpeed:
        asked = aliased(Message)
        rows = await self.db.execute(
            select(Message.stats)
            .join(asked, Message.reply_to_message_id == asked.id)
            .where(Message.role == "assistant", asked.sender_id == self.user.id, Message.created_at > self.since)
        )
        stats = [s for (s,) in rows if isinstance(s, dict)]
        return MyReplySpeed(
            days=self.days,
            replies=len(stats),
            output_tokens=sum(int(s.get("output_tokens") or 0) for s in stats),
            prompt_tokens=sum(int(s.get("prompt_tokens") or 0) for s in stats),
            avg_first_token_ms=self._mean(stats, "first_token_ms"),
            avg_tokens_per_second=self._mean(stats, "tokens_per_second"),
            avg_total_ms=self._mean(stats, "total_ms"),
        )

    @staticmethod
    def _mean(stats: list[dict], key: str) -> float | None:
        values = [float(s[key]) for s in stats if isinstance(s.get(key), (int, float))]
        return round(mean(values), 1) if values else None

    def _zone(self) -> ZoneInfo | timezone:
        try:
            return ZoneInfo(self.user.timezone or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            return UTC

    @staticmethod
    def _aware(moment: datetime) -> datetime:
        """SQLite gives naive datetimes; they are UTC."""
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
