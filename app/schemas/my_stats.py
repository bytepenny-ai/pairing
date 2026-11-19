"""GET /api/my-stats: one user's own usage, for the My stats page (services/my_stats_service.py)."""

from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.stats import CountByKey


class MyUsageToday(BaseModel):
    """The last 24 hours against this user's limits (usage_limits.py); a limit of 0 means none."""

    replies_used: int
    tokens_used: int
    replies_limit: int
    tokens_limit: int
    exempt: bool


class MyTotals(BaseModel):
    chats: int
    messages_sent: int
    channel_messages: int
    replies: int
    failed_replies: int
    attachments: int


class MyReplySpeed(BaseModel):
    """Replies to this user's messages in the last days (reply_stats.py); averages are None without data."""

    days: int
    replies: int
    output_tokens: int
    prompt_tokens: int
    avg_first_token_ms: float | None
    avg_tokens_per_second: float | None
    avg_total_ms: float | None


class MyDay(BaseModel):
    day: date
    messages: int


class MyLibrary(BaseModel):
    documents: int
    document_bytes: int
    document_chunks: int
    folders: int
    notes: int
    skills: int
    images: int
    failed_images: int


class MyStatsOut(BaseModel):
    member_since: datetime | None
    usage_today: MyUsageToday
    totals: MyTotals
    speed: MyReplySpeed
    activity: list[MyDay]
    models: list[CountByKey]
    library: MyLibrary
