"""The "index" layout with a model that calls tools: the model reads a skill itself with "use_skill"
(app/services/prompt_layout/skill_chat_tool.py, index.py, index_notes.py, tool_loop_service.offered_tools)."""

from types import SimpleNamespace

import pytest

from app.schemas.prompt_cache import PromptCacheSetting
from app.services import tool_loop_service
from app.services.prompt_layout.base import LayoutContext
from app.services.prompt_layout.index import IndexLayout
from app.services.prompt_layout.sections import PromptSection, PromptSections
from app.services.prompt_layout.skill_chat_tool import GUARD, NAME, NOTICE_NAME, NOTICE_PARAM_KEY, PARAM_KEY, SkillTool
from tests.test_prompt_layout_index import ALL, POEM, REVIEW, RULE, FakeRelevance, window

WIDE = window(*(f"m{i}" for i in range(1, 9)))


async def run(sections, saved, message_id, uses=(), has_image=False, relevance=None):
    layout = IndexLayout(PromptCacheSetting(mode="index"), relevance or FakeRelevance({}))
    ctx = LayoutContext(sections, dict(saved), "Any question?", message_id, WIDE, has_image, True, list(uses))
    return await layout.layout(ctx)


def reply(message_id: str, *events: dict, role: str = "assistant") -> SimpleNamespace:
    return SimpleNamespace(id=message_id, role=role, tool_events=list(events))


def used(name: str, is_error: bool = False) -> dict:
    return {"name": NAME, "arguments": {"name": name}, "is_error": is_error, "result": "..."}


# The tool


@pytest.mark.asyncio
async def test_the_tool_returns_a_skill_by_name_and_lists_the_names_when_wrong():
    tool = SkillTool({"Code review": "Check correctness first."})
    assert (await tool.call({"name": "code  REVIEW"})).text == f"{GUARD}\n\nCheck correctness first."
    missing = await tool.call({"name": "Poem"})
    assert missing.is_error and '"Code review"' in missing.text
    assert "Code review" not in str(SkillTool.definition())  # names stay out: the definition never changes


def test_only_successful_use_skill_calls_by_replies_count():
    messages = [
        reply("r1", used("Review"), {"name": "search", "arguments": {"name": "Review"}}),
        reply("r2", used("Poem", is_error=True)),
        reply("u1", used("Review"), role="user"),
        SimpleNamespace(id="r3", role="assistant", tool_events=None),
    ]
    assert SkillTool.uses(messages) == [("r1", ["Review"])]


def test_the_tool_comes_from_the_reply_params_only_with_skills():
    assert SkillTool.from_params({}) == [] and SkillTool.from_params({PARAM_KEY: {}}) == []
    assert len(SkillTool.from_params({PARAM_KEY: {"Review": "x"}})) == 1


# The layout


@pytest.mark.asyncio
async def test_the_list_says_how_to_read_a_skill_and_nothing_is_added_up_front():
    layout, state = await run(PromptSections([REVIEW, POEM, RULE]), {}, "m1")
    assert NAME in layout.system_prompt and "- Review: Code review" in layout.system_prompt
    assert "Most requests need no skill" in layout.system_prompt  # cautious: small models read too many
    assert layout.inserts == {} and layout.notes == {} and state["entries"] == []
    assert layout.skill_texts == {"Review": REVIEW.text, "Poem": POEM.text}
    params = layout.reply_params()
    assert params[PARAM_KEY] == layout.skill_texts and params[NOTICE_PARAM_KEY] is True


@pytest.mark.asyncio
async def test_a_skill_the_model_read_joins_the_next_message_once():
    sections = PromptSections([REVIEW, POEM])
    _, state = await run(sections, {}, "m1")
    second, state = await run(sections, state, "m2", [("r1", ["review"])])
    (note,) = second.notes["m2"]  # a tool result before the message, never in the user's words
    assert second.inserts == {} and (note.tool, note.arguments) == (NAME, {"name": "Review"})
    assert note.text.endswith(REVIEW.text) and GUARD in note.text
    assert state["recorded"] == ["r1"]
    third, state3 = await run(sections, state, "m3", [("r1", ["review"]), ("r2", ["Review"])])
    assert third.notes == second.notes  # already in the chat: not added again
    assert state3["recorded"] == ["r1", "r2"]


@pytest.mark.asyncio
async def test_a_skill_waits_while_the_message_has_an_image():
    sections = PromptSections([REVIEW])
    _, state = await run(sections, {}, "m1")
    on_image, state = await run(sections, state, "m2", [("r1", ["Review"])], has_image=True)
    assert on_image.notes == {} and state["recorded"] == []
    after, _ = await run(sections, state, "m3", [("r1", ["Review"])])
    assert list(after.notes) == ["m3"]


@pytest.mark.asyncio
async def test_new_changed_and_removed_skills_get_one_note_each():
    _, state = await run(PromptSections([REVIEW]), {}, "m1")
    _, state = await run(PromptSections([REVIEW]), state, "m2", [("r1", ["Review"])])
    changed = PromptSection("skill:1", "skill", "Review", "Check the tests too.", "Code review")
    layout, state = await run(PromptSections([changed, POEM]), state, "m3")
    notes = layout.notes["m3"]
    assert {n.tool for n in notes} == {NOTICE_NAME}
    text = " ".join(n.text for n in notes)
    assert 'New skill available: "Poem"' in text and "only when a request is exactly that task" in text
    assert 'The skill "Review" was changed' in text
    again, state = await run(PromptSections([changed, POEM]), state, "m4")
    assert "m4" not in again.notes  # once
    gone, _ = await run(PromptSections([POEM]), state, "m5")
    assert 'The skill "Review" is no longer available' in gone.notes["m5"][0].text


@pytest.mark.asyncio
async def test_with_tools_no_embedding_is_asked():
    relevance = FakeRelevance(None)  # would add every skill at once without tools
    layout, _ = await run(PromptSections([REVIEW, POEM]), {}, "m1", relevance=relevance)
    assert layout.inserts == {} and layout.notes == {} and relevance.asked == []


@pytest.mark.asyncio
async def test_without_tools_a_skill_never_goes_on_an_image_message():
    layout = IndexLayout(PromptCacheSetting(mode="index"), FakeRelevance(None))
    ctx = LayoutContext(PromptSections([REVIEW]), {}, "Describe it.", "m1", ALL, has_image=True)
    result, state = await layout.layout(ctx)
    assert result.inserts == {} and result.skill_texts == {} and state["entries"] == []


@pytest.mark.asyncio
async def test_read_only_offers_the_same_tool_and_changes_nothing():
    _, state = await run(PromptSections([REVIEW]), {}, "m1")
    layout = IndexLayout(PromptCacheSetting(mode="index"), FakeRelevance(None))
    ctx = LayoutContext(PromptSections([REVIEW]), dict(state), "", None, ALL, False, True, [("r1", ["Review"])])
    result, saved = await layout.layout(ctx)
    assert saved == state and result.skill_texts == {"Review": REVIEW.text} and result.notice_tool


@pytest.mark.asyncio
async def test_a_state_saved_before_the_tool_still_loads():
    old = {"mode": "index", "listed": [REVIEW.to_dict()], "entries": []}
    _, state = await run(PromptSections([REVIEW]), old, "m1", [("r1", ["Review"])])
    assert state["recorded"] == ["r1"] and state["entries"][0]["key"] == "skill:1"


# Which tools a reply offers


@pytest.mark.asyncio
async def test_the_skill_tool_comes_after_the_chats_mcp_tools_and_only_for_a_tool_model(db, monkeypatch):
    mcp = SimpleNamespace(name="search")

    async def mcp_tools(_db, _params):
        return [mcp]

    async def can(_model):
        return True

    monkeypatch.setattr(tool_loop_service, "_mcp_tools", mcp_tools)
    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", can)
    tools = await tool_loop_service.offered_tools(db, "m", {PARAM_KEY: {"Review": "x"}})
    assert [t.name for t in tools] == ["search", NAME]

    async def cannot(_model):
        return False

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", cannot)
    assert await tool_loop_service.offered_tools(db, "m", {PARAM_KEY: {"Review": "x"}}) == []
