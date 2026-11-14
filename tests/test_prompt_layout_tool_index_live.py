"""Option 3 follows the server's current MCP tools: an admin's new tool reaches a chat as an updated list (one
note), never as "update to re-read the whole chat" (tool_loop_service.chat_mcp_tools, routers/mcp_tools.py)."""

import pytest

from app.routers import mcp_tools
from app.schemas import ConversationCreate
from app.services import conversation_service, inference_client, mcp_settings_service, tool_loop_service
from app.services.mcp_tool_catalog import McpToolCatalog
from tests.test_prompt_layout_tool_index import FakeNews, FakeTool
from tests.test_prompt_layouts import ask, chat_parts, use  # noqa: F401 - fixtures

LIVE: list = []


@pytest.fixture
def server(monkeypatch) -> list:
    """The server's MCP tools now (LIVE, edited by the tests); MCP is on and the model can call tools."""

    async def tools(_self):
        return list(LIVE)

    async def yes(*_args):
        return True

    LIVE[:] = [FakeTool()]
    monkeypatch.setattr(McpToolCatalog, "tools", tools)
    monkeypatch.setattr(mcp_settings_service, "get_enabled", yes)
    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", yes)
    return LIVE


@pytest.mark.asyncio
async def test_a_tool_added_mid_chat_joins_as_a_new_list_without_a_reread(db, user, server, monkeypatch):
    calls: list[tuple[list[dict], dict]] = []

    async def model(_model, messages, params):
        calls.append(([dict(m) for m in messages], dict(params)))
        yield "ok"

    monkeypatch.setattr(inference_client, "chat_stream", model)
    await use(db, "index")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    conversation.params = {**(conversation.params or {}), "use_tools": True}
    await db.commit()
    await ask(db, conversation, user, "hello")
    server.append(FakeNews())  # an admin adds a tool
    await ask(db, conversation, user, "any news?")

    (first, first_params), (second, second_params) = calls
    assert second[0] == first[0] and second_params["tools"] == first_params["tools"]  # the prompt's start kept
    assert "web__news" not in first[-2]["content"] and "web__news" in second[-2]["content"]  # the new list
    await db.refresh(conversation)
    assert [s["name"] for s in conversation.params["tool_snapshot"]] == ["web__news", "web__search"]


@pytest.mark.asyncio
async def test_other_layouts_keep_the_chats_saved_tools(db, server):
    saved = [{"name": "web__search", "server": "web", "tool": "search", "spec": FakeTool().definition()}]
    server.append(FakeNews())
    params = {"use_tools": True, "tool_snapshot": saved}
    assert [t.name for t in await tool_loop_service.chat_mcp_tools(db, params)] == ["web__search"]
    indexed = await tool_loop_service.chat_mcp_tools(db, {**params, "tool_index": True})
    assert [t.name for t in indexed] == ["web__news", "web__search"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "offered"), [("ordered", ["web__news"]), ("append", []), ("index", [])])
async def test_the_tools_popover_offers_new_tools_only_where_updating_rereads(db, user, server, mode, offered):
    await use(db, mode)
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    saved = [{"name": "web__search", "server": "web", "tool": "search", "spec": FakeTool().definition()}]
    conversation.params = {**(conversation.params or {}), "tool_snapshot": saved}
    await db.commit()
    server.append(FakeNews())
    info = await mcp_tools._chat_tools(db, conversation)
    assert [t.name for t in info.new_tools] == offered
    assert info.frozen is (mode == "ordered")


@pytest.mark.asyncio
async def test_option_2_turns_tools_on_and_off_with_a_note_not_a_reread(db, user, server, monkeypatch):
    calls: list[tuple[list[dict], dict]] = []

    async def model(_model, messages, params):
        calls.append(([dict(m) for m in messages], dict(params)))
        yield "ok"

    monkeypatch.setattr(inference_client, "chat_stream", model)
    await use(db, "append")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "hello")
    for on, text in ((True, "use a tool"), (False, "and now?")):
        conversation.params = {**(conversation.params or {}), "use_tools": on}
        await db.commit()
        await ask(db, conversation, user, text)

    (first, p1), (on, p2), (off, p3) = calls
    names = [[t["function"]["name"] for t in p["tools"]] for p in (p1, p2, p3)]
    assert names[0] == names[1] == names[2] and "web__search" not in names[0]  # the same tools, so no re-read
    assert first[0] == on[0] == off[0]  # nor a changed system prompt
    assert "web__search(query: string, required)" in on[-2]["content"]  # turned on: the list
    # turned off: one line
    assert off[-2]["content"] == "Tools are now off: don't call use_tool; answer from what you know."
