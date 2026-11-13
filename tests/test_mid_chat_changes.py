"""A started chat may change its notes and skills under every prompt cache layout but "ordered"
(conversation_skills.edit_block_reason, routers/notes.py, routers/prompt_cache_admin.py)."""

import pytest
from fastapi import HTTPException

from app.models import Conversation, Message
from app.routers import notes as notes_router, prompt_cache_admin
from app.schemas.channel import ChannelCreate
from app.schemas.note import NoteSlotUpdate
from app.schemas.prompt_cache import PromptCacheSetting
from app.schemas.skill import SkillIn
from app.services import channel_service, conversation_service, conversation_skills
from app.services.prompt_cache_setting import PromptCacheSettings
from app.services.prompt_layout.sections import PromptSections
from app.services.skill_library import SkillLibrary

CHEAP_MODES = ["append", "index", "blocks"]  # a skill change is cheap
NOTE_MODES = ["append", "blocks"]  # a note change too ("index" keeps notes in the system prompt)


async def _use(db, mode: str) -> None:
    await PromptCacheSettings(db).set(PromptCacheSetting(mode=mode))


async def _started_chat(db, user, conversation: Conversation | None = None) -> Conversation:
    if conversation is None:
        conversation = Conversation(owner_id=user.id, params={})
        db.add(conversation)
        await db.commit()
    db.add(Message(conversation_id=conversation.id, role="user", content="hi", sender_id=user.id))
    await db.commit()
    await db.refresh(conversation, ["messages", "skill_choices"])
    return conversation


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ordered", *CHEAP_MODES])
async def test_the_chat_page_is_told_whether_started_chats_may_change(db, user, mode):
    await _use(db, mode)
    result = await prompt_cache_admin.get_mid_chat_changes(db, user)
    assert (result.skills, result.notes) == (mode in CHEAP_MODES, mode in NOTE_MODES)


@pytest.mark.asyncio
async def test_stable_order_still_locks_skills_and_notes_after_the_first_message(db, user):
    skill = await SkillLibrary(db).create(SkillIn(name="Any", content="Do it."))
    chat = await _started_chat(db, user)

    with pytest.raises(HTTPException) as skills_locked:
        await conversation_skills.choose(db, chat, user, [skill.id])
    with pytest.raises(HTTPException) as notes_locked:
        await notes_router._require_slot_edit_rights(db, chat, user)
    assert skills_locked.value.status_code == notes_locked.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", CHEAP_MODES)
async def test_other_layouts_let_a_started_chat_change_skills_and_some_notes(db, user, mode):
    await _use(db, mode)
    skill = await SkillLibrary(db).create(SkillIn(name="Review", content="Check correctness first."))
    chat = await _started_chat(db, user)

    result = await conversation_skills.choose(db, chat, user, [skill.id])
    assert [s.name for s in result.chosen] == ["Review"] and result.editable

    body = NoteSlotUpdate(content="Answer in French.", only_this_chat=True)
    if mode not in NOTE_MODES:
        with pytest.raises(HTTPException) as notes_locked:
            await notes_router.update_slot(chat.id, "rules", body, db, user)
        assert notes_locked.value.status_code == 409
        prompt = (await PromptSections.load(db, chat, user.id, has_image=False)).ordered_prompt()
        assert "Check correctness first." in prompt and "Answer in French." not in prompt
        return
    slot = await notes_router.update_slot(chat.id, "rules", body, db, user)
    assert slot.content == "Answer in French."

    prompt = (await PromptSections.load(db, chat, user.id, has_image=False)).ordered_prompt()
    assert "Check correctness first." in prompt and "Answer in French." in prompt


@pytest.mark.asyncio
async def test_a_channel_member_still_cannot_change_them(db, user, admin_user, channel_manager_user):
    await _use(db, "append")
    body = ChannelCreate(
        name="team", member_user_ids=[user.id, channel_manager_user.id], manager_user_ids=[channel_manager_user.id]
    )
    channel = await channel_service.create_channel(db, body, admin_user)
    chat = await _started_chat(db, user, channel.conversation)
    skill = await SkillLibrary(db).create(SkillIn(name="Shared", content="Do it."))

    with pytest.raises(HTTPException) as member:
        await conversation_skills.choose(db, chat, user, [skill.id])
    assert member.value.status_code == 403
    with pytest.raises(HTTPException) as notes:
        await notes_router._require_slot_edit_rights(db, chat, user)
    assert notes.value.status_code == 403
    assert (await conversation_skills.choose(db, chat, channel_manager_user, [skill.id])).chosen


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ordered", *CHEAP_MODES])
async def test_a_channel_skill_change_keeps_the_cache_unless_stable_order(
    db, user, admin_user, channel_manager_user, monkeypatch, mode
):
    await _use(db, mode)
    dropped = []

    async def drop(conversation_id: str) -> None:
        dropped.append(conversation_id)

    monkeypatch.setattr(conversation_service, "_drop_engine_cache", drop)
    body = ChannelCreate(
        name="ops", member_user_ids=[user.id, channel_manager_user.id], manager_user_ids=[channel_manager_user.id]
    )
    channel = await channel_service.create_channel(db, body, admin_user)
    chat = await _started_chat(db, user, channel.conversation)
    skill = await SkillLibrary(db).create(SkillIn(name="Shared", content="Do it."))

    await conversation_skills.set_for_channel(db, chat, admin_user, [skill.id])

    assert dropped == ([chat.id] if mode == "ordered" else [])
