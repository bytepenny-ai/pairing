"""At most MAX_SKILLS_PER_CHAT skills per chat or channel (conversation_skills._replace), and the pickers learn it."""

import pytest
from fastapi import HTTPException

from app.config import MAX_SKILLS_PER_CHAT
from app.models import Conversation
from app.schemas.skill import SkillIn
from app.services import conversation_skills
from app.services.skill_library import SkillLibrary


async def _skills(db, count: int) -> list[str]:
    library = SkillLibrary(db)
    return [(await library.create(SkillIn(name=f"Skill {n}", content="Do it."))).id for n in range(count)]


async def _chat(db, owner) -> Conversation:
    conversation = Conversation(owner_id=owner.id, params={})
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation, ["messages", "skill_choices"])
    return conversation


def test_the_limit_is_two():
    assert MAX_SKILLS_PER_CHAT == 2


@pytest.mark.asyncio
async def test_a_chat_takes_two_skills_and_refuses_a_third(db, user):
    ids = await _skills(db, 3)
    chat = await _chat(db, user)

    result = await conversation_skills.choose(db, chat, user, ids[:2])
    assert len(result.chosen) == 2 and result.limit == 2

    with pytest.raises(HTTPException) as refused:
        await conversation_skills.choose(db, chat, user, ids)
    assert refused.value.status_code == 400 and "at most 2" in refused.value.detail
    assert len((await conversation_skills.chosen(db, chat, user)).chosen) == 2  # unchanged


@pytest.mark.asyncio
async def test_a_repeated_id_counts_once(db, user):
    ids = await _skills(db, 2)
    chat = await _chat(db, user)
    result = await conversation_skills.choose(db, chat, user, [ids[0], ids[0], ids[1]])
    assert len(result.chosen) == 2


@pytest.mark.asyncio
async def test_a_channel_skill_set_has_the_same_limit(db, admin_user):
    ids = await _skills(db, 3)
    chat = await _chat(db, admin_user)
    with pytest.raises(HTTPException) as refused:
        await conversation_skills.set_for_channel(db, chat, admin_user, ids)
    assert refused.value.status_code == 400
