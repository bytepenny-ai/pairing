"""Admin settings > Models > Default models > "Replies to an image include" (vision_reply_setting.py): notes and skills
can be left out of a reply to an image (slow on a CPU), never out of a text reply."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers import vision_reply_admin
from app.schemas.vision_reply import VisionReplySetting
from app.services import chat_prompt_service
from app.services.chat_attachment_service import AttachmentInfo
from app.services.prompt_layout import sections

IMAGE = [AttachmentInfo(path=Path("/x/cat.png"), filename="cat.png", type="image")]


@pytest.fixture
def stubs(monkeypatch):
    """A chat with one note and one skill, and an empty knowledge base."""

    async def notes(_db, _conversation, _user_id):
        return {"persona": [SimpleNamespace(id="n1", content="NOTE")]}

    async def skills(_db, _conversation):
        return [SimpleNamespace(id="s1", name="S", content="SKILL", description="")]

    async def nothing(*_args, **_kwargs):
        return []

    monkeypatch.setattr(sections, "resolve_conversation_notes", notes)
    monkeypatch.setattr(sections.conversation_skills, "active_skills", skills)
    monkeypatch.setattr(sections.PromptSections, "notes_text", lambda self: "NOTE" if self.of_kind("persona") else "")
    monkeypatch.setattr(
        sections.PromptSections, "skills_text", staticmethod(lambda found: found[0].text if found else "")
    )
    monkeypatch.setattr(chat_prompt_service, "retrieve_context", nothing)


async def _system_prompt(db, attachments) -> str:
    conversation = SimpleNamespace(channel_id=None)
    user = SimpleNamespace(id="u1")
    prompt, *_ = await chat_prompt_service.build_system_prompt(
        db, conversation, user, "/describe", {"num_ctx": 4096}, attachments, [], 512
    )
    return prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(("include", "expected"), [("all", "SKILL\n\nNOTE"), ("notes", "NOTE"), ("none", "")])
async def test_a_reply_to_an_image_includes_what_the_admin_chose(db, stubs, include, expected):
    await vision_reply_admin.set_vision_reply_context(VisionReplySetting(include=include), db=db, _admin=None)
    assert await _system_prompt(db, IMAGE) == expected


@pytest.mark.asyncio
async def test_a_text_reply_always_includes_notes_and_skills(db, stubs):
    await vision_reply_admin.set_vision_reply_context(VisionReplySetting(include="none"), db=db, _admin=None)
    assert await _system_prompt(db, []) == "SKILL\n\nNOTE"


@pytest.mark.asyncio
async def test_the_default_is_just_the_message_and_the_image(db, stubs):
    assert (await vision_reply_admin.get_vision_reply_context(db=db, _admin=None)).include == "none"
    assert await _system_prompt(db, IMAGE) == ""


def test_only_the_three_choices_are_accepted():
    with pytest.raises(ValidationError):
        VisionReplySetting(include="some")
