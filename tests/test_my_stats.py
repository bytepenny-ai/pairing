"""my_stats_service.py / my_stats_activity.py: a user's own stats count only what belongs to that user."""

from datetime import timedelta

import pytest

from app.models import Conversation, Document, ImageGenerationJob, Message, Note, User
from app.models._base import utcnow
from app.routers import pages
from app.services.auth_service import hash_password
from app.services.my_stats_activity import MyActivity
from app.services.my_stats_service import MyStats
from tests.test_settings_pages import _request


async def _chat(db, user: User, model: str = "qwen", replies: list[dict | None] | None = None, ago=timedelta()) -> None:
    chat = Conversation(owner_id=user.id, title="t", model=model)
    db.add(chat)
    await db.flush()
    for stats in replies or [None]:
        asked = Message(conversation_id=chat.id, role="user", content="q", sender_id=user.id, created_at=utcnow() - ago)
        db.add(asked)
        await db.flush()
        status = "error" if stats == {"error": True} else "complete"
        db.add(
            Message(
                conversation_id=chat.id,
                role="assistant",
                content="a",
                reply_to_message_id=asked.id,
                status=status,
                stats=None if status == "error" else stats,
                created_at=utcnow() - ago,
            )
        )
    await db.commit()


async def _other(db) -> User:
    other = User(username="bob", password_hash=hash_password("bob-pw"), role="user")
    db.add(other)
    await db.commit()
    return other


@pytest.mark.asyncio
async def test_counts_only_the_users_own_things(db, user):
    other = await _other(db)
    await _chat(
        db,
        user,
        replies=[
            {
                "first_token_ms": 1000,
                "total_ms": 4000,
                "output_tokens": 50,
                "prompt_tokens": 200,
                "tokens_per_second": 10.0,
            },
            {"error": True},
        ],
    )
    await _chat(db, user, model="gemma")
    await _chat(db, other, replies=[None, None, None])
    db.add_all(
        [
            Document(owner_id=user.id, filename="a.pdf", content_hash="h", chunk_count=4, size_bytes=2048),
            Document(owner_id=other.id, filename="b.pdf", content_hash="h2", chunk_count=9, size_bytes=9999),
            Note(owner_id=user.id, title="n"),
            ImageGenerationJob(
                owner_id=user.id,
                status="complete",
                prompt="p",
                checkpoint="c",
                width=64,
                height=64,
                steps=1,
                cfg=1.0,
                seed=1,
            ),
        ]
    )
    await db.commit()

    stats = await MyStats(db, user).summary()

    assert (stats.totals.chats, stats.totals.messages_sent, stats.totals.replies) == (2, 3, 3)
    assert stats.totals.failed_replies == 1
    assert {m.key: m.count for m in stats.models} == {"qwen": 1, "gemma": 1}
    assert (stats.library.documents, stats.library.document_bytes, stats.library.document_chunks) == (1, 2048, 4)
    assert (stats.library.notes, stats.library.images) == (1, 1)
    assert stats.speed.output_tokens == 50 and stats.speed.avg_first_token_ms == 1000.0
    assert stats.usage_today.replies_used == 3


@pytest.mark.asyncio
async def test_activity_has_every_day_and_skips_old_messages(db, user):
    await _chat(db, user, replies=[None, None])
    await _chat(db, user, ago=timedelta(days=40))
    days = await MyActivity(db, user).per_day()
    assert len(days) == 30
    assert sum(d.messages for d in days) == 2
    assert days[-1].messages == 2


@pytest.mark.asyncio
async def test_speed_without_data_has_no_averages(db, user):
    speed = await MyActivity(db, user).speed()
    assert speed.replies == 0 and speed.avg_tokens_per_second is None


@pytest.mark.asyncio
async def test_every_user_gets_the_page_and_the_sidebar_link(db, user):
    page = (await pages.my_stats_page(_request(user.id), db=db)).body.decode()
    assert "My stats" in page
    chat = (await pages.chat_page(_request(user.id), db=db)).body.decode()
    assert 'href="/my-stats"' in chat
    assert 'href="/stats"' not in chat  # the server-wide Stats stays admin-only
