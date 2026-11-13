"""Admin settings > Inference > Prompt cache end to end: the setting and its API, PromptLayouts (state saved in the
chat, hidden from the browser, a failing layout falling back), and real replies whose prompts follow each layout."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import SYSTEM_OWNER_ID, AppSetting
from app.routers import prompt_cache_admin
from app.schemas import ConversationCreate
from app.schemas.conversation import ConversationOut, ConversationUpdate
from app.schemas.prompt_cache import PromptCacheSetting
from app.services import (
    chat_service,
    conversation_service,
    model_catalog_service,
    reply_generation_service,
    tool_loop_service,
)
from app.services.prompt_cache_setting import PromptCacheSettings
from app.services.prompt_layout import layouts, sections
from app.services.prompt_layout.layouts import STATE_KEY, PromptLayouts
from app.services.prompt_layout.update_note import HEADER

RULES: dict[str, list] = {"rules": []}
SKILLS: list = []


@pytest.fixture(autouse=True)
def chat_parts(monkeypatch):
    """The chat's notes and skills come from RULES and SKILLS (edited by the tests); "fake-model" is installed."""

    async def notes(_db, _conversation, _user_id):
        return {"rules": list(RULES["rules"])}

    async def skills(_db, _conversation):
        return list(SKILLS)

    async def installed():
        return ["fake-model"]

    async def no_tools(_model):
        return False  # the text path; tool-model tests (test_prompt_layout_wiring.py) switch it on

    RULES["rules"] = [SimpleNamespace(id="r1", content="Answer in English.")]
    SKILLS.clear()
    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", no_tools)
    monkeypatch.setattr(sections, "resolve_conversation_notes", notes)
    monkeypatch.setattr(sections.conversation_skills, "active_skills", skills)
    monkeypatch.setattr(model_catalog_service, "installed_chat_models", installed)


@pytest.fixture
def engine(monkeypatch) -> list[tuple[list[dict], dict]]:
    """What each reply sent to the engine: (messages, params)."""
    sent: list[tuple[list[dict], dict]] = []

    async def fake_chat_stream(_model, messages, params):
        sent.append(([dict(m) for m in messages], dict(params)))
        yield "ok"

    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    return sent


async def ask(db, conversation, user, text: str) -> None:
    """One message and its reply. The chat's messages are read again first, as each real request loads the chat."""
    await db.refresh(conversation, ["messages"])
    async for _event in chat_service.build_reply_stream(db, conversation, user, text):
        pass


async def use(db, mode: str, **fields) -> None:
    await prompt_cache_admin.set_prompt_cache(PromptCacheSetting(mode=mode, **fields), db=db, _admin=None)


# The setting


@pytest.mark.asyncio
async def test_the_setting_defaults_to_ordered_and_saves(db):
    assert (await prompt_cache_admin.get_prompt_cache(db=db, _admin=None)).mode == "ordered"
    await use(db, "append", max_updates=3)
    saved = await prompt_cache_admin.get_prompt_cache(db=db, _admin=None)
    assert saved.mode == "append" and saved.max_updates == 3


def test_only_known_modes_and_ranges_are_accepted():
    for bad in ({"mode": "other"}, {"max_updates": 0}, {"load_above": 1.5}, {"min_block_tokens": 4}):
        with pytest.raises(ValidationError):
            PromptCacheSetting(**bad)


@pytest.mark.asyncio
async def test_a_damaged_saved_setting_reads_as_the_defaults(db):
    db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key="prompt_cache", value={"mode": "nonsense"}))
    await db.commit()
    assert (await PromptCacheSettings(db).get()).mode == "ordered"


# PromptLayouts and the chat's state


@pytest.mark.asyncio
async def test_the_state_is_saved_in_the_chat_hidden_from_the_browser_and_kept_by_a_settings_save(db, user):
    await use(db, "append")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)

    async def everything(_inserts):
        return {"m1"}

    await PromptLayouts(db).for_reply(conversation, user.id, "m1", "q?", everything)
    assert conversation.params[STATE_KEY]["mode"] == "append"
    assert "Answer in English." not in ConversationOut.model_validate(conversation).model_dump_json()
    params = ConversationOut.model_validate(conversation).params
    await conversation_service.update_conversation(db, conversation, ConversationUpdate(params=params), user)
    assert conversation.params[STATE_KEY]["mode"] == "append"


@pytest.mark.asyncio
async def test_a_failing_layout_falls_back_to_the_plain_order(db, user, monkeypatch):
    await use(db, "append")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)

    async def broken(_self, _ctx):
        raise RuntimeError("bug")

    monkeypatch.setattr(layouts.AppendLayout, "layout", broken)
    layout = await PromptLayouts(db).for_reply(conversation, user.id, "m1", "q?", None)
    assert layout.system_prompt == "Rules you must always follow:\n- Answer in English." and layout.inserts == {}


# Real replies


@pytest.mark.asyncio
async def test_ordered_puts_skills_before_notes(db, user, engine):
    SKILLS.append(SimpleNamespace(id="s1", name="Review", content="Check the code.", description=""))
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "hello")
    system = engine[0][0][0]["content"]
    assert system.index("Check the code.") < system.index("Answer in English.")
    assert "cache_reuse" not in engine[0][1]


@pytest.mark.asyncio
async def test_append_keeps_the_prompt_and_adds_the_change_to_the_message_where_it_happened(db, user, engine):
    await use(db, "append")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "first question")
    RULES["rules"].append(SimpleNamespace(id="r2", content="No emoji."))
    await ask(db, conversation, user, "second question")
    await ask(db, conversation, user, "third question")
    first, second, third = (messages for messages, _ in engine)
    assert first[0] == second[0] == third[0]  # the system prompt never changed
    assert second[-1]["content"].startswith(HEADER) and second[-1]["content"].endswith("second question")
    assert third[3]["content"] == second[-1]["content"]  # the update stayed on its message
    assert third[-1]["content"] == "third question"


@pytest.mark.asyncio
async def test_index_adds_a_skill_with_the_message_that_needs_it(db, user, engine, monkeypatch):
    async def no_tools(_model):
        return False

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", no_tools)  # judged by embeddings instead
    await use(db, "index")  # no embedding model in tests: every skill comes with the first message
    SKILLS.append(SimpleNamespace(id="s1", name="Review", content="Check the code.", description="Code review"))
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "hello")
    await ask(db, conversation, user, "and now?")
    first, second = (messages for messages, _ in engine)
    assert "- Review: Code review" in first[0]["content"] and "Check the code." not in first[0]["content"]
    assert first[-1]["content"].startswith('Skill "Review"') and first[-1]["content"].endswith("hello")
    assert second[0] == first[0] and second[1] == first[-1]


@pytest.mark.asyncio
async def test_blocks_asks_the_engine_to_keep_unchanged_parts(db, user, engine):
    await use(db, "blocks", min_block_tokens=64)
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "hello")
    messages, params = engine[0]
    assert params["cache_reuse"] == {"mode": "blocks", "min_tokens": 64}
    assert messages[0]["content"] == "Rules you must always follow:\n- Answer in English."
