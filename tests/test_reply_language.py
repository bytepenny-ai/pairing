"""reply_language.py: a reply-language line for messages in a non-Latin script, and where the model reads it."""

import pytest

from app.schemas import ConversationCreate
from app.services import chat_service, conversation_service, model_catalog_service, reply_generation_service
from app.services.chat_commands import ChatCommand
from app.services.reply_language import ReplyLanguage

_HEBREW = "תאר את התמונה"  # "describe the image"
_RUSSIAN = "привет мир"  # "hello world"


def test_hebrew_gets_its_name_and_a_shared_script_the_generic_line():
    assert ReplyLanguage.hint(_HEBREW) == "(Reply in Hebrew.)"
    assert ReplyLanguage.hint(_RUSSIAN) == "(Reply in the language of this message.)"


def test_a_non_latin_script_missing_from_the_file_gets_the_generic_line():
    amharic = "\u1230\u120b\u121d \u12d3\u1208\u121d"  # Ethiopic script, not in reply_scripts.json
    assert ReplyLanguage.hint(amharic) == "(Reply in the language of this message.)"


def test_accented_latin_counts_as_latin():
    assert ReplyLanguage.hint("Caf\u00e9 cr\u00e8me br\u00fbl\u00e9e, s\u2019il vous pla\u00eet") == ""


def test_latin_script_numbers_and_mostly_english_get_none():
    assert ReplyLanguage.hint("Describe the image please") == ""
    assert ReplyLanguage.hint("1234 ?!") == ""
    assert ReplyLanguage.hint(f"Please describe this picture for the team, {_HEBREW[:3]}") == ""


def test_the_command_alone_gets_none_and_the_users_words_decide():
    assert ChatCommand.for_model("/describe") == ChatCommand.expand("/describe")
    with_words = ChatCommand.for_model(f"/describe {_HEBREW}")
    assert with_words.startswith(ChatCommand.expand(f"/describe {_HEBREW}"))
    assert with_words.endswith("\n\n(Reply in Hebrew.)")


@pytest.mark.asyncio
async def test_every_turn_sends_the_same_line_after_a_hebrew_message(db, user, monkeypatch):
    sent: list[list[dict]] = []

    async def fake_installed_chat_models():
        return ["fake-model"]

    async def fake_chat_stream(_model, messages, _params):
        sent.append([dict(m) for m in messages])
        yield "ok"

    monkeypatch.setattr(model_catalog_service, "installed_chat_models", fake_installed_chat_models)
    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    async for _ in chat_service.build_reply_stream(db, conversation, user, _HEBREW):
        pass
    await db.refresh(conversation, attribute_names=["messages"])
    async for _ in chat_service.build_reply_stream(db, conversation, user, "and in English?"):
        pass

    first, second = sent
    assert first[-1]["content"].endswith("(Reply in Hebrew.)")
    assert second[1]["content"] == first[-1]["content"]  # rebuilt the same: the cache still matches
    assert "(Reply in" not in second[-1]["content"]
