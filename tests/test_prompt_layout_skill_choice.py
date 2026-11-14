"""Who picks a skill under the "Short index" layout (PromptCacheSetting.skill_choice): pAIring's pre-check ("auto"),
or the user with /use_skill "<skill>" ("command"); and the one shared question embedding (question_vectors.py)."""

import asyncio
from types import SimpleNamespace

import pytest

from app.schemas import ConversationCreate
from app.schemas.prompt_cache import PromptCacheSetting
from app.services import conversation_service, inference_client, tool_loop_service
from app.services.chat_commands import ChatCommand
from app.services.chat_skill_command import SkillCommand
from app.services.prompt_layout import index as index_module
from app.services.prompt_layout.base import LayoutContext
from app.services.prompt_layout.index import IndexLayout
from app.services.prompt_layout.sections import PromptSections
from app.services.prompt_layout.skill_chat_tool import NAME, NOTICE_NAME
from app.services.question_vectors import QuestionVectors
from tests.test_prompt_layout_index import POEM, REVIEW, FakeRelevance, window
from tests.test_prompt_layouts import SKILLS, ask, chat_parts, use  # noqa: F401 - fixtures

KEPT = window("m1", "m2", "m3")


async def run(choice, relevance, question="Please review my code", asked=None, tools=True, saved=None, mid="m1"):
    layout = IndexLayout(PromptCacheSetting(mode="index", skill_choice=choice), relevance)
    ctx = LayoutContext(PromptSections([REVIEW, POEM]), dict(saved or {}), question, mid, KEPT, tools=tools)
    ctx.asked_skill = asked
    return await layout.layout(ctx)


def test_the_command_is_read_at_the_start_or_the_end_and_the_model_never_sees_it():
    assert SkillCommand.parse('/use_skill "Create user story" export to PDF') == ("Create user story", "export to PDF")
    assert SkillCommand.parse('Translate this /use_skill "Translate"') == ("Translate", "Translate this")
    assert SkillCommand.parse('Translate /use_skill "Translate" this please') == ("Translate", "Translate this please")
    assert SkillCommand.parse('a/use_skill "X" b') == (None, 'a/use_skill "X" b')  # glued to a word: not a command
    assert SkillCommand.parse("use_skill without a slash") == (None, "use_skill without a slash")
    assert ChatCommand.expand('/use_skill "Review" check  this') == "check  this"
    assert ChatCommand.expand("  plain  ") == "  plain  "  # untouched without a command


@pytest.mark.asyncio
async def test_auto_adds_a_clear_match_before_the_reply_and_keeps_use_skill():
    relevance = FakeRelevance({"skill:1": 0.6, "skill:2": 0.1})
    layout, state = await run("auto", relevance)
    (note,) = layout.notes["m1"]
    assert (note.tool, note.arguments) == (NAME, {"name": "Review"}) and note.text.endswith(REVIEW.text)
    assert layout.skill_texts is not None and relevance.asked == ["Please review my code"]
    assert [e["key"] for e in state["entries"]] == ["skill:1"]


@pytest.mark.asyncio
async def test_auto_never_waits_on_a_slow_embedding_or_adds_all_for_a_tool_model(monkeypatch):
    class Slow(FakeRelevance):
        async def scores(self, question, skills):
            await asyncio.sleep(0.2)
            return await super().scores(question, skills)

    monkeypatch.setattr(index_module, "_PRECHECK_SECONDS", 0.05)
    slow, _ = await run("auto", Slow({"skill:1": 0.9}))
    assert slow.notes == {}  # skipped for this message
    unknown, _ = await run("auto", FakeRelevance(None))
    assert unknown.notes == {}  # nothing to judge by: a tool model reads one itself
    without_tools, _ = await run("auto", FakeRelevance(None), tools=False)
    assert set(without_tools.inserts) == {"m1"}  # a model without tools still gets every waiting skill


@pytest.mark.asyncio
async def test_command_adds_only_what_the_user_asked_for_and_offers_no_use_skill():
    relevance = FakeRelevance({"skill:1": 0.9})
    plain, _ = await run("command", relevance)
    assert plain.notes == {} and relevance.asked == []  # no pre-check
    assert plain.skill_texts is None and "The user picks one" in plain.system_prompt
    layout, state = await run("command", relevance, asked="poem")
    (note,) = layout.notes["m1"]
    assert note.tool == NOTICE_NAME and note.text.startswith('For this message, the user asked to use the skill "Poem"')
    again, _ = await run("command", relevance, asked="Poem", saved=state, mid="m2")
    assert "m2" not in again.notes  # already in the chat
    unknown, _ = await run("command", relevance, asked="Nope")
    assert unknown.notes == {}


@pytest.mark.asyncio
async def test_a_command_in_a_real_chat_reaches_the_model_without_the_command(db, user, monkeypatch):
    calls: list[list[dict]] = []

    async def model(_model, messages, _params):
        calls.append([dict(m) for m in messages])
        yield "ok"

    async def can(_model):
        return True

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", can)
    monkeypatch.setattr(inference_client, "chat_stream", model)
    await use(db, "index", skill_choice="command")
    SKILLS.append(SimpleNamespace(id="s1", name="Review", content="Check the code.", description="Code review"))
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, '/use_skill "Review" is this function safe?')

    (sent,) = calls
    assert sent[-1] == {"role": "user", "content": "is this function safe?"}
    assert sent[-2]["role"] == "tool" and "Check the code." in sent[-2]["content"]


def test_the_chat_page_offers_the_command_only_when_skills_are_chosen_by_it():
    flags = {
        (m, c): PromptCacheSetting(mode=m, skill_choice=c).mid_chat_changes.skill_command
        for m in ("ordered", "index")
        for c in ("auto", "command")
    }
    assert flags == {
        ("ordered", "auto"): False,
        ("ordered", "command"): False,
        ("index", "auto"): False,
        ("index", "command"): True,
    }


@pytest.mark.asyncio
async def test_a_question_is_embedded_once_for_everyone_who_needs_it():
    calls = []

    async def embed(text, model):
        calls.append(text)
        return [1.0, 0.0]

    first = await QuestionVectors.of("same question", "m", embed)
    second = await QuestionVectors.of("same question", "m", embed)
    assert calls == ["same question"] and (first == second).all()


@pytest.mark.asyncio
async def test_a_chat_without_skills_can_use_any_skill_the_user_may(db, user, admin_user, monkeypatch):
    from app.schemas.skill import SkillIn
    from app.services.skill_library import SkillLibrary

    calls: list[list[dict]] = []

    async def model(_model, messages, _params):
        calls.append([dict(m) for m in messages])
        yield "ok"

    async def can(_model):
        return True

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", can)
    monkeypatch.setattr(inference_client, "chat_stream", model)
    await use(db, "index", skill_choice="command")
    await SkillLibrary(db).create(SkillIn(name="Explain code", content="Walk through the code step by step."))
    await SkillLibrary(db, owner_id=admin_user.id).create(SkillIn(name="Admin secret", content="Not for others."))
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, '/use_skill "Explain code" what does this do?')  # the chat has no skills
    await ask(db, conversation, user, '/use_skill "Admin secret" and this?')  # someone else's private skill

    first, second = calls
    assert first[-1] == {"role": "user", "content": "what does this do?"}
    assert "Walk through the code step by step." in first[-2]["content"]
    assert second[-1] == {"role": "user", "content": "and this?"}
    assert not any("Not for others." in str(m.get("content")) for m in second)
