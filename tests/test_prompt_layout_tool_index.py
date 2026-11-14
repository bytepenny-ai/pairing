"""Option 3's tool index (app/services/prompt_layout/tool_index.py): the chat's MCP tools go through "use_tool" and
are told as a note, so the Tools switch never changes the prompt's start."""

import pytest

from app.schemas import ConversationCreate
from app.services import conversation_service, inference_client, tool_loop_service
from app.services.mcp_client import McpToolResult
from app.services.prompt_layout.base import LayoutContext
from app.services.prompt_layout.sections import PromptSections
from app.services.prompt_layout.skill_chat_tool import NOTICE_NAME, TOOL_INDEX_PARAM_KEY
from app.services.prompt_layout.tool_index import NAME, ToolIndexNotes, UseTool
from app.services.tool_loop_service import ToolLoop
from tests.test_prompt_layout_index import window
from tests.test_prompt_layouts import ask, chat_parts, use  # noqa: F401 - fixtures

SEARCH = {
    "type": "function",
    "function": {
        "name": "web__search",
        "description": "Search the web.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
}


class FakeTool:
    name, server_name, tool_name = "web__search", "web", "search"
    description = "Search the web."

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def definition(self) -> dict:
        return SEARCH

    async def call(self, arguments: dict) -> McpToolResult:
        self.calls.append(arguments)
        return McpToolResult("Paris", False)


def ctx(message_id: str, on: bool, specs=None, kept=("m1", "m2", "m3", "m4")) -> LayoutContext:
    c = LayoutContext(PromptSections([]), {}, "q?", message_id, window(*kept), tools=True)
    c.tools_on, c.tool_specs = on, (specs if specs is not None else [SEARCH] if on else [])
    return c


def test_tools_are_told_when_on_again_when_changed_and_once_when_off():
    on = ToolIndexNotes.notes(ctx("m1", True), [])
    assert len(on) == 1 and "web__search(query: string, required): Search the web." in on[0]["text"]
    assert ToolIndexNotes.notes(ctx("m2", True), on) == []  # already told
    other = {**SEARCH, "function": {**SEARCH["function"], "description": "Search the news."}}
    changed = ToolIndexNotes.notes(ctx("m2", True, [other]), on)
    assert "Search the news." in changed[0]["text"]
    off = ToolIndexNotes.notes(ctx("m3", False), on)
    assert off[0]["text"] == f"Tools are now off: don't call {NAME}; answer from what you know."
    assert ToolIndexNotes.notes(ctx("m4", False), [*on, *off]) == []  # once
    assert ToolIndexNotes.notes(ctx("m1", False), []) == []  # never on: nothing to say


@pytest.mark.asyncio
async def test_use_tool_runs_the_named_tool_and_refuses_otherwise():
    search = FakeTool()
    tool, arguments = UseTool([search]).route({"name": "web__search", "arguments": {"query": "capital of France"}})
    assert tool is search and arguments == {"query": "capital of France"}
    wrong, _ = UseTool([search]).route({"name": "nope"})
    assert "web__search" in (await wrong.call({"name": "nope"})).text
    off, _ = UseTool([]).route({"name": "web__search"})
    assert (await off.call({})).text.startswith("Tools are turned off")


@pytest.mark.asyncio
async def test_the_loop_shows_and_runs_the_tool_use_tool_names(monkeypatch):
    search, turns = FakeTool(), []

    async def model(_model, messages, params):
        turns.append(messages)
        if len(turns) == 1:
            call = {"function": {"name": NAME, "arguments": {"name": "web__search", "arguments": {"query": "x"}}}}
            params["tool_sink"].add_calls([call])
            return
        yield "It is Paris."

    monkeypatch.setattr(inference_client, "chat_stream", model)
    items = [i async for i in ToolLoop([UseTool([search])]).run("m", [{"role": "user", "content": "hi"}], {})]
    (event,) = [i["tool"] for i in items if isinstance(i, dict)]
    assert search.calls == [{"query": "x"}]
    assert (event["name"], event["server"], event["tool"], event["result"]) == ("web__search", "web", "search", "Paris")


@pytest.mark.asyncio
async def test_with_the_index_no_mcp_definition_is_offered_even_while_tools_are_on(db, monkeypatch):
    async def mcp(_db, params):
        return [FakeTool()] if params.get("use_tools") else []

    async def can(_model):
        return True

    monkeypatch.setattr(tool_loop_service, "chat_mcp_tools", mcp)
    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", can)
    base = {TOOL_INDEX_PARAM_KEY: True, "notice_tool": True}
    on = await tool_loop_service.offered_tools(db, "m", {**base, "use_tools": True})
    off = await tool_loop_service.offered_tools(db, "m", base)
    assert [t.name for t in on] == [t.name for t in off] == [NOTICE_NAME, NAME]  # the same list either way
    plain = await tool_loop_service.offered_tools(db, "m", {"use_tools": True})
    assert [t.name for t in plain] == ["web__search"]  # other layouts: the tool's own definition


@pytest.mark.asyncio
async def test_turning_tools_on_mid_chat_keeps_the_prompt_start_and_adds_a_note(db, user, monkeypatch):
    calls: list[tuple[list[dict], dict]] = []

    async def model(_model, messages, params):
        calls.append(([dict(m) for m in messages], dict(params)))
        yield "ok"

    async def can(_model):
        return True

    async def mcp(_db, params):
        return [FakeTool()] if params.get("use_tools") else []

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", can)
    monkeypatch.setattr(tool_loop_service, "chat_mcp_tools", mcp)
    monkeypatch.setattr(inference_client, "chat_stream", model)
    await use(db, "index")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "hello")
    conversation.params = {**(conversation.params or {}), "use_tools": True}  # the chat's Tools switch
    await db.commit()
    await ask(db, conversation, user, "search it")

    (first, first_params), (second, second_params) = calls
    names = [t["function"]["name"] for t in second_params["tools"]]
    assert second[0] == first[0] and names == [t["function"]["name"] for t in first_params["tools"]]
    assert "web__search" not in names  # never in the tool list: no re-read
    assert second[-1] == {"role": "user", "content": "search it"}
    assert second[-2]["role"] == "tool" and "web__search(query: string, required)" in second[-2]["content"]


def test_the_chat_page_skips_the_reread_warning_where_switching_is_cheap():
    from app.schemas.prompt_cache import PromptCacheSetting

    cheap = {m: PromptCacheSetting(mode=m).mid_chat_changes.tools for m in ("ordered", "append", "index", "blocks")}
    assert cheap == {"ordered": False, "append": True, "index": True, "blocks": True}


class FakeNews(FakeTool):
    name, server_name, tool_name = "web__news", "web", "news"

    def definition(self) -> dict:
        return {**SEARCH, "function": {**SEARCH["function"], "name": "web__news"}}


@pytest.mark.parametrize(
    "call",
    [
        {"arguments": {"query": "x"}},  # no name (Gemma 4, seen live): the one tool these arguments fit
        {"name": "search", "arguments": {"query": "x"}},  # the short name
        {"name": "Web Search", "arguments": {"query": "x"}},
        {"tool": "web__search", "args": {"query": "x"}},
        {"name": "web__search", "query": "x"},  # flat arguments
    ],
)
def test_use_tool_takes_the_forms_models_send(call):
    search = FakeTool()
    assert UseTool([search]).route(call) == (search, {"query": "x"})


@pytest.mark.asyncio
async def test_use_tool_never_guesses_between_two_tools_and_shows_the_form():
    tools = UseTool([FakeTool(), FakeNews()])
    tool, _ = tools.route({"arguments": {"query": "x"}})  # both take a query
    refusal = (await tool.call({})).text
    assert tool is tools and '{"name": "web__search", "arguments": {...}}' in refusal and "web__news" in refusal
    assert tools.route({"arguments": {"other": 1}})[0] is tools  # fits none


NEWS = {
    **SEARCH,
    "function": {**SEARCH["function"], "name": "web__news", "description": "Latest news. Use it for events."},
}


def test_a_change_tells_only_what_changed():
    first = ToolIndexNotes.notes(ctx("m1", True), [])
    (added,) = ToolIndexNotes.notes(ctx("m2", True, [SEARCH, NEWS]), first)
    assert "web__news(query: string, required): Latest news." in added["text"]  # cut to its first sentence
    assert "web__search" not in added["text"] and added["full"] is False  # the model has it already
    (gone,) = ToolIndexNotes.notes(ctx("m3", True, [SEARCH]), [*first, added])
    assert gone["text"] == "No longer available: web__news."


def test_the_full_list_comes_again_when_the_one_it_built_on_left_the_window():
    first = ToolIndexNotes.notes(ctx("m1", True), [])
    (added,) = ToolIndexNotes.notes(ctx("m2", True, [SEARCH, NEWS]), first)
    (again,) = ToolIndexNotes.notes(ctx("m3", True, [SEARCH, NEWS]), [added])  # m1's full list was trimmed
    assert again["full"] and "web__search" in again["text"] and "web__news" in again["text"]
    off = ToolIndexNotes.notes(ctx("m4", False), [*first, added])
    (back_on,) = ToolIndexNotes.notes(ctx("m5", True, [SEARCH]), [*first, added, *off])
    assert back_on["full"] and back_on["text"].startswith("Tools are on.")  # after off: the whole list


@pytest.mark.asyncio
async def test_a_call_while_tools_are_off_is_refused_without_a_tool_box(monkeypatch):
    turns = []

    async def model(_model, messages, params):
        turns.append(messages)
        if len(turns) == 1:  # a small model may still try
            call = {"function": {"name": NAME, "arguments": {"name": "web__search", "arguments": {"query": "x"}}}}
            params["tool_sink"].add_calls([call])
            return
        yield "Paris, as far as I know."

    monkeypatch.setattr(inference_client, "chat_stream", model)
    items = [i async for i in ToolLoop([UseTool([])]).run("m", [{"role": "user", "content": "hi"}], {})]
    assert not [i for i in items if isinstance(i, dict)]  # no tool box
    assert "".join(i for i in items if isinstance(i, str)) == "Paris, as far as I know."
    assert turns[1][-1]["content"].startswith("Tools are turned off")  # the model still learns why
