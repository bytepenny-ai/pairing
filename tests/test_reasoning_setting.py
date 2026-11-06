"""The system-wide Reasoning switch (Admin settings > System > Reasoning): setting, endpoint and chats' use."""

import pytest

from app.routers import reasoning_admin
from app.schemas import ConversationCreate
from app.schemas.settings import ReasoningSwitch
from app.services import chat_service, conversation_service, reply_generation_service
from app.services.reasoning_setting import reasoning_setting


@pytest.mark.asyncio
async def test_on_by_default_and_can_be_changed(db):
    assert await reasoning_setting.enabled(db) is True
    await reasoning_admin.set_setting(ReasoningSwitch(enabled=False), db=db, _admin=None)
    assert (await reasoning_admin.get_setting(db=db, _user=None)).enabled is False
    await reasoning_setting.set_enabled(db, True)
    assert await reasoning_setting.enabled(db) is True


@pytest.mark.asyncio
async def test_apply_forces_think_off_only_while_blocked(db):
    params = {"think": True, "num_ctx": 4096}
    assert await reasoning_setting.apply(db, params) == params
    await reasoning_setting.set_enabled(db, False)
    assert await reasoning_setting.apply(db, params) == {"think": False, "num_ctx": 4096}
    assert params["think"] is True  # the caller's dict is not changed


@pytest.mark.asyncio
async def test_a_chat_with_reasoning_on_sends_think_off_while_blocked_and_keeps_its_choice(db, user, monkeypatch):
    seen: list[bool] = []

    async def fake_chat_stream(_model, _messages, params):
        seen.append(params["think"])
        yield "ok"

    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    conversation.params = {**conversation.params, "think": True}
    await db.commit()

    async for _event in chat_service.build_reply_stream(db, conversation, user, "hi"):
        pass
    await reasoning_setting.set_enabled(db, False)
    async for _event in chat_service.build_reply_stream(db, conversation, user, "again"):
        pass

    assert seen == [True, False]
    assert conversation.params["think"] is True


@pytest.mark.asyncio
async def test_a_fresh_install_starts_with_reasoning_off(db):
    from app.services import auth_service

    await auth_service.seed_default_users(db)  # empty database: the first start
    assert await reasoning_setting.enabled(db) is False
    await reasoning_setting.set_enabled(db, True)
    await auth_service.seed_default_users(db)  # later starts keep the admin's choice
    assert await reasoning_setting.enabled(db) is True


@pytest.mark.asyncio
async def test_an_existing_install_keeps_reasoning_on_even_if_admin_is_recreated(db, user):
    from app.services import auth_service

    await auth_service.seed_default_users(db)  # "admin" missing, but other accounts exist
    assert await reasoning_setting.enabled(db) is True
