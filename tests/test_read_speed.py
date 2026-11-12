"""Long-file warning and reply timeout: reply_stats.py keeps what the engine read and where, read_speed.py turns that
into a per-host median, chat_attachment_check.py warns with it, and reply_deadline.py lets a slow read finish."""

import asyncio

import pytest

from app.models import Message
from app.schemas import ConversationCreate
from app.services import conversation_service, model_catalog_service, reply_side_events
from app.services.chat_attachment_check import AttachmentCheck
from app.services.read_speed import ReadSpeed
from app.services.reply_deadline import ReplyDeadline
from app.services.reply_side_events import ReplySideEvents
from app.services.reply_stats import ReplyStats


def test_stats_keep_only_the_tokens_read_not_the_cached_ones():
    matricxon = ReplyStats.from_matricxon(
        {"prompt_eval_count": 900, "prompt_cached_count": 700, "prompt_eval_duration": 40_000_000_000}
    )
    assert matricxon["read_tokens"] == 200 and matricxon["read_ms"] == 40_000
    assert ReplyStats.from_matricxon({"prompt_eval_count": 900})["read_tokens"] is None  # older Matricxon
    llamacpp = ReplyStats.from_llamacpp({"prompt_n": 120, "prompt_ms": 3000.0})
    assert llamacpp["read_tokens"] == 120 and llamacpp["read_ms"] == 3000.0

    times = iter([0.0, 1.0, 2.0])
    stats = ReplyStats(clock=lambda: next(times), model="m")
    stats.text()
    stats.usage({**matricxon, "output_tokens": 5, "host": "http://node-a"})
    result = stats.result()
    assert (result["read_tokens"], result["model"], result["host"]) == (200, "m", "http://node-a")


async def _reply(db, conversation, model: str, host: str, tokens: int, ms: int) -> None:
    stats = {"model": model, "host": host, "read_tokens": tokens, "read_ms": ms}
    db.add(Message(conversation_id=conversation.id, role="assistant", content="x", stats=stats))
    await db.commit()


@pytest.fixture
async def chats(db, user, monkeypatch):
    async def installed():
        return ["m"]

    monkeypatch.setattr(conversation_service, "installed_chat_models", installed)
    monkeypatch.setattr(model_catalog_service, "installed_chat_models", installed)
    one = await conversation_service.create_conversation(db, ConversationCreate(model="m"), user)
    two = await conversation_service.create_conversation(db, ConversationCreate(model="m"), user)
    return one, two


@pytest.mark.asyncio
async def test_the_speed_is_the_chats_own_host_else_the_slowest(db, chats):
    one, two = chats
    for ms in (10_000, 10_000, 20_000):  # fast node: 500 tokens in 10-20 s
        await _reply(db, one, "m", "fast", 500, ms)
    await _reply(db, one, "m", "slow", 500, 100_000)  # slow node: 5 tok/s
    await _reply(db, one, "m", "slow", 50, 1)  # too short to measure
    await _reply(db, one, "other", "fast", 500, 1)  # another model

    speed = ReadSpeed(db)
    assert await speed.tokens_per_second("m", one.id) == pytest.approx(5.0)  # its latest reply ran on "slow"
    await _reply(db, two, "m", "fast", 500, 10_000)
    assert await speed.tokens_per_second("m", two.id) == pytest.approx(50.0)
    assert await speed.tokens_per_second("m") == pytest.approx(5.0)  # a new chat: the slowest node
    assert await speed.tokens_per_second("unknown") is None


@pytest.mark.asyncio
async def test_a_long_file_warns_how_long_the_reply_may_take(db, chats):
    one, _ = chats
    await _reply(db, one, "m", "slow", 500, 100_000)  # 5 tokens a second
    check = AttachmentCheck(db, one)
    verdict = await check.verdict("roadmap.md", ("word " * 4000).encode())
    assert (
        verdict.ok
        and verdict.warning == "roadmap.md is long: on this server the reply may take about 14 minutes to start."
    )
    assert (await check.verdict("note.md", b"short note")).warning is None
    assert (await AttachmentCheck(db).verdict("roadmap.md", ("word " * 4000).encode())).warning is None


def test_wait_words():
    assert ReadSpeed.wait_words(70) == "about a minute"
    assert ReadSpeed.wait_words(20 * 60) == "about 20 minutes"
    assert ReadSpeed.wait_words(2 * 3600) == "over an hour"


def test_read_progress_keeps_a_slow_read_alive_and_writing_gets_the_full_timeout():
    async def run() -> list[str]:
        outcomes = []
        # A read reporting progress every 0.04 s outlives a 0.1 s timeout; then 0.05 s of writing fits.
        async with asyncio.timeout(0.1) as timeout:
            deadline = ReplyDeadline(timeout, 0.1)
            for _ in range(5):
                await asyncio.sleep(0.04)
                deadline.progress()
            deadline.text()
            await asyncio.sleep(0.05)
            outcomes.append("finished")
        # No progress at all: the timeout still fires.
        try:
            async with asyncio.timeout(0.05) as timeout:
                ReplyDeadline(timeout, 0.05)
                await asyncio.sleep(0.2)
        except TimeoutError:
            outcomes.append("timed out")
        return outcomes

    assert asyncio.run(run()) == ["finished", "timed out"]


def test_read_progress_counts_only_the_new_part_of_the_prompt_for_both_engines():
    assert ReplySideEvents.read_fraction({"cached": 100, "read": 225, "total": 1000}) == pytest.approx(0.25)
    llamacpp = {"cache": 100, "processed": 325, "total": 1000}  # processed includes the cache
    assert ReplySideEvents.read_fraction(llamacpp) == pytest.approx(0.25)
    assert ReplySideEvents.read_fraction({"cached": 50, "read": 0, "total": 50}) is None  # nothing new to read


@pytest.mark.asyncio
async def test_progress_reaches_the_chat_each_time_it_moved_a_percent(db, monkeypatch):
    published: list[float] = []
    monkeypatch.setattr(
        reply_side_events.reply_broadcast_service,
        "publish_read_progress",
        lambda _conversation, fraction: published.append(round(fraction, 3)),
    )
    events = ReplySideEvents(db, Message(role="assistant", content=""), "c1")
    for read in (100, 104, 300):
        assert await events.handle({"read_progress": {"cached": 0, "read": read, "total": 1000}}) is False
    assert published == [0.1, 0.3]  # 10.4% is less than a point after 10%


@pytest.mark.asyncio
async def test_a_chat_deleted_while_its_reply_is_prepared_gets_no_reply(db, user, chats, monkeypatch):
    from app.services import chat_service, reply_generation_service

    one, _ = chats
    started: list[str] = []

    async def stream_reply(*_args, **_kwargs):
        started.append("reply")
        yield {"done": True}

    monkeypatch.setattr(reply_generation_service, "stream_reply", stream_reply)
    monkeypatch.setattr(model_catalog_service, "sees_images", lambda _model: asyncio.sleep(0, result=False))

    async def deleted(_db, _conversation_id):
        return False

    monkeypatch.setattr(chat_service, "_still_asked", deleted)
    events = [e async for e in chat_service.build_reply_stream(db, one, user, "hello")]
    assert started == [] and "user_message_id" in events[0]


def test_an_embedding_model_that_fails_stops_the_index_early(monkeypatch, tmp_path):
    from app.services import chat_file_index
    from app.services.chat_file_index import ChatFileIndex
    from app.services.inference_client import InferenceError

    calls: list[str] = []

    async def failing(text, _model):
        calls.append(text)
        raise InferenceError("cannot embed")

    monkeypatch.setattr(chat_file_index, "embed", failing)
    path = tmp_path / "long.txt"
    path.write_text("word " * 5000)
    asyncio.run(ChatFileIndex._build(path, "emb"))
    assert len(calls) == 3 and not ChatFileIndex.index_path(path).exists()


@pytest.mark.asyncio
async def test_a_question_deleted_alone_or_with_its_chat_is_no_longer_asked(db, chats):
    from app.services import chat_service

    one, _ = chats
    question = Message(conversation_id=one.id, role="user", content="q")
    db.add(question)
    await db.commit()
    assert await chat_service._still_asked(db, question.id)
    question.status = "deleted"  # a channel post deleted by its admin
    await db.commit()
    assert not await chat_service._still_asked(db, question.id)
    assert not await chat_service._still_asked(db, "no-such-message")  # gone with its chat
