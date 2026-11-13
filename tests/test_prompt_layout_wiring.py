"""How prompt layouts reach the rest of a reply: the history window with a layout's inserts (ChatFollowUp.kept_ids),
the warm-up (it reads the saved layout and changes nothing) and Matricxon's request ("blocks": cache_reuse)."""

from types import SimpleNamespace

import httpx
import pytest

from app.models import Message
from app.schemas import ConversationCreate
from app.schemas.common import GenerationParams
from app.services import chat_model_warmup, conversation_service, matricxon_client, matricxon_pool, tool_loop_service
from app.services.chat_follow_up import ChatFollowUp
from app.services.chat_model_warmup import ChatModelWarmUp
from app.services.prompt_layout.skill_chat_tool import NAME, NOTICE_NAME, PARAM_KEY
from tests.test_prompt_layouts import RULES, SKILLS, ask, chat_parts, engine, use  # noqa: F401 - fixtures


@pytest.mark.asyncio
async def test_a_long_insert_pushes_old_messages_out_of_the_window(db):
    messages = [Message(id=f"m{i}", role="user" if i % 2 == 0 else "assistant", content="x" * 400) for i in range(8)]
    follow_up = ChatFollowUp(db, messages, num_ctx=1400, reserved_tokens=512)  # room for 3552 characters
    everything = await follow_up.kept_ids({})
    assert everything == {m.id for m in messages}
    crowded = await follow_up.kept_ids({"m6": "y" * 1800})
    assert "m0" not in crowded and {"m6", "m7"} <= crowded


@pytest.mark.asyncio
async def test_the_warm_up_reads_the_saved_layout_and_changes_nothing(db, user, engine, monkeypatch):  # noqa: F811
    warmed: list[list[dict]] = []

    async def warm_stream(_model, messages, _params):
        warmed.append(messages)
        yield "x"

    monkeypatch.setattr(chat_model_warmup, "chat_stream", warm_stream)
    await use(db, "append")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "first question")
    RULES["rules"].append(SimpleNamespace(id="r2", content="No emoji."))
    await ask(db, conversation, user, "second question")
    saved = dict(conversation.params["prompt_layout"])
    RULES["rules"].append(SimpleNamespace(id="r3", content="Cite sources."))  # changed after the last reply

    params = {**GenerationParams().model_dump(), "num_ctx": 4096}
    await ChatModelWarmUp._warm(conversation.id, user.id, "fake-model", params)

    last_reply = engine[-1][0]
    assert warmed[0][0] == last_reply[0]  # the same system prompt as the last reply
    assert warmed[0][3] == last_reply[3]  # the update on its message, without the newer change
    await db.refresh(conversation)
    assert conversation.params["prompt_layout"] == saved


@pytest.mark.asyncio
async def test_matricxon_is_asked_for_block_reuse_only_when_the_layout_says_so(monkeypatch):
    sent: list[dict] = []

    async def on_one_host(make_stream, prefer=None, info=None, retry_on=()):
        async for chunk in make_stream("http://mx:8420"):
            yield chunk

    class _Reply:
        is_error = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def aiter_lines(self):
            yield '{"message": {"content": "ok"}, "done": true}'

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        def stream(self, _method, _url, json):
            sent.append(json)
            return _Reply()

    monkeypatch.setattr(matricxon_pool, "stream_with_failover", on_one_host)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())
    params = GenerationParams().model_dump()
    reuse = {"mode": "blocks", "min_tokens": 32}
    _ = [c async for c in matricxon_client.chat_stream("m", [], {**params, "cache_reuse": reuse})]
    _ = [c async for c in matricxon_client.chat_stream("m", [], params)]
    assert sent[0]["cache_reuse"] == reuse and "cache_reuse" not in sent[1]
    assert "prompt_layout" not in sent[0]  # the chat's saved state is never sent
    _ = [c async for c in matricxon_client.chat_stream("m", [], {**params, PARAM_KEY: {"Review": "x"}})]
    assert PARAM_KEY not in sent[2]  # nor the skills the use_skill tool serves


async def _tool_model(_model):
    return True


@pytest.mark.asyncio
async def test_the_model_reads_a_skill_with_the_tool_and_the_next_message_keeps_it(db, user, monkeypatch):
    calls: list[tuple[list[dict], dict]] = []

    async def model(_model, messages, params):
        calls.append(([dict(m) for m in messages], dict(params)))
        if len(calls) == 1:  # the first question: the model asks for the skill
            params["tool_sink"].add_calls([{"function": {"name": NAME, "arguments": {"name": "Review"}}}])
            return
        yield "ok"

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", _tool_model)
    monkeypatch.setattr(tool_loop_service.inference_client, "chat_stream", model)
    await use(db, "index")
    SKILLS.append(SimpleNamespace(id="s1", name="Review", content="Check the code.", description="Code review"))
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "please review my code")
    await ask(db, conversation, user, "and the edge cases?")

    (first, first_params), (tool_round, _), (second, _) = calls
    assert NAME in first[0]["content"]
    assert [t["function"]["name"] for t in first_params["tools"]] == [NAME, NOTICE_NAME]
    assert first[-1]["content"] == "please review my code"  # nothing added up front
    assert tool_round[-1]["role"] == "tool" and tool_round[-1]["content"].endswith("Check the code.")
    assert second[0] == first[0]  # the system prompt never changed
    # The skill stays as use_skill's result before the next message: never in the user's own words.
    assert second[-1] == {"role": "user", "content": "and the edge cases?"}
    assert second[-2]["role"] == "tool" and second[-2]["content"].endswith("Check the code.")
    reply, call = second[-3], second[-3]["tool_calls"][0]
    assert reply["role"] == "assistant" and reply["content"] == "ok"  # the call goes on the reply before
    assert call["function"] == {"name": NAME, "arguments": {"name": "Review"}}
    assert call["id"] == second[-2]["tool_call_id"]


@pytest.mark.asyncio
async def test_the_warm_up_offers_the_same_tools_as_the_reply(db, user, monkeypatch):
    warmed: list[dict] = []

    async def warm_stream(_model, _messages, params):
        warmed.append(params)
        yield "x"

    async def model(_model, _messages, _params):
        yield "ok"

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", _tool_model)
    monkeypatch.setattr(tool_loop_service.inference_client, "chat_stream", model)
    monkeypatch.setattr(chat_model_warmup, "chat_stream", warm_stream)
    await use(db, "index")
    SKILLS.append(SimpleNamespace(id="s1", name="Review", content="Check the code.", description="Code review"))
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "hello")

    params = {**GenerationParams().model_dump(), "num_ctx": 4096}
    await ChatModelWarmUp._warm(conversation.id, user.id, "fake-model", params)
    assert [t["function"]["name"] for t in warmed[0]["tools"]] == [NAME, NOTICE_NAME]


@pytest.mark.asyncio
async def test_with_a_tool_model_an_update_comes_as_a_tool_result_not_in_the_users_words(db, user, monkeypatch):
    calls: list[list[dict]] = []

    async def model(_model, messages, _params):
        calls.append([dict(m) for m in messages])
        yield "ok"

    monkeypatch.setattr(tool_loop_service, "model_can_use_tools", _tool_model)
    monkeypatch.setattr(tool_loop_service.inference_client, "chat_stream", model)
    await use(db, "append")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    await ask(db, conversation, user, "first question")
    RULES["rules"].append(SimpleNamespace(id="r2", content="No emoji."))
    await ask(db, conversation, user, "OK")

    first, second = calls
    assert second[0] == first[0]  # the system prompt never changed
    assert second[-1] == {"role": "user", "content": "OK"}
    assert second[-2]["role"] == "tool" and "No emoji." in second[-2]["content"]
    assert second[-3]["tool_calls"][0]["function"]["name"] == NOTICE_NAME
