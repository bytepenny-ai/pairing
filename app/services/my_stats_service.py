"""My stats: one user's own usage (GET /api/my-stats, my_stats.html). Every user may see it, so it counts only
what belongs to that user: their chats, the messages they sent and the replies to them, their documents, notes,
skills and images. Counts are SQL func.count queries, like stats_service.py; the per-day and speed parts are in
my_stats_activity.py.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Conversation,
    Document,
    DocumentFolder,
    ImageGenerationJob,
    Message,
    MessageAttachment,
    Note,
    Skill,
    User,
)
from app.schemas.my_stats import MyLibrary, MyStatsOut, MyTotals, MyUsageToday
from app.schemas.stats import CountByKey
from app.services.my_stats_activity import MyActivity
from app.services.usage_limits import UsageLimitService


class MyStats:
    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user

    async def summary(self) -> MyStatsOut:
        activity = MyActivity(self.db, self.user)
        return MyStatsOut(
            member_since=self.user.created_at,
            usage_today=await self._usage_today(),
            totals=await self._totals(),
            speed=await activity.speed(),
            activity=await activity.per_day(),
            models=await self._models(),
            library=await self._library(),
        )

    async def _count(self, query) -> int:
        return int((await self.db.execute(query)).scalar_one() or 0)

    async def _usage_today(self) -> MyUsageToday:
        usage = await UsageLimitService(self.db).for_user(self.user)
        return MyUsageToday(
            replies_used=usage.replies_used,
            tokens_used=usage.tokens_used,
            replies_limit=usage.effective.replies_per_day,
            tokens_limit=usage.effective.tokens_per_day,
            exempt=usage.exempt,
        )

    async def _totals(self) -> MyTotals:
        uid = self.user.id
        sent = Message.role == "user", Message.sender_id == uid
        asked = aliased(Message)
        replies = (
            select(func.count(Message.id))
            .join(asked, Message.reply_to_message_id == asked.id)
            .where(Message.role == "assistant", asked.sender_id == uid)
        )
        return MyTotals(
            chats=await self._count(select(func.count(Conversation.id)).where(Conversation.owner_id == uid)),
            messages_sent=await self._count(select(func.count(Message.id)).where(*sent)),
            channel_messages=await self._count(
                select(func.count(Message.id))
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(*sent, Conversation.channel_id.isnot(None))
            ),
            replies=await self._count(replies),
            failed_replies=await self._count(replies.where(Message.status == "error")),
            attachments=await self._count(
                select(func.count(MessageAttachment.id))
                .join(Message, MessageAttachment.message_id == Message.id)
                .where(*sent)
            ),
        )

    async def _models(self) -> list[CountByKey]:
        """The models of this user's own chats, most used first."""
        rows = await self.db.execute(
            select(Conversation.model, func.count(Conversation.id))
            .where(Conversation.owner_id == self.user.id, Conversation.model.isnot(None))
            .group_by(Conversation.model)
            .order_by(func.count(Conversation.id).desc())
        )
        return [CountByKey(key=model, count=count) for model, count in rows]

    async def _library(self) -> MyLibrary:
        uid = self.user.id
        docs = (
            await self.db.execute(
                select(
                    func.count(Document.id),
                    func.coalesce(func.sum(Document.size_bytes), 0),
                    func.coalesce(func.sum(Document.chunk_count), 0),
                ).where(Document.owner_id == uid)
            )
        ).one()
        images = select(func.count(ImageGenerationJob.id)).where(ImageGenerationJob.owner_id == uid)
        return MyLibrary(
            documents=int(docs[0]),
            document_bytes=int(docs[1]),
            document_chunks=int(docs[2]),
            folders=await self._count(select(func.count(DocumentFolder.id)).where(DocumentFolder.owner_id == uid)),
            notes=await self._count(select(func.count(Note.id)).where(Note.owner_id == uid)),
            skills=await self._count(select(func.count(Skill.id)).where(Skill.owner_id == uid)),
            images=await self._count(images.where(ImageGenerationJob.status == "complete")),
            failed_images=await self._count(images.where(ImageGenerationJob.status == "error")),
        )
