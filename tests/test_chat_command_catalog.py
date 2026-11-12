"""chat_command_catalog.py and chat_commands.py: /describe and /summarize with their short and long forms, aliases,
what each needs attached, and the list the page reads (GET /api/chat/commands)."""

import pytest

from app.routers import chat as chat_router
from app.services.chat_command_catalog import AttachmentKind, Command, CommandCatalog
from app.services.chat_commands import ChatCommand


@pytest.mark.parametrize(
    ("typed", "name"),
    [
        ("/describe", "describe"),
        ("/describe_short", "describe_short"),
        ("/describe_long", "describe_long"),
        ("/summarize_short", "summarize_short"),
        ("/summarise_long", "summarize_long"),
        ("/Summary", "summarize"),
    ],
)
def test_every_form_and_alias_is_known(typed, name):
    commands, rest = ChatCommand.parse(f"{typed} in Hebrew")
    assert [c.name for c in commands] == [name] and rest == "in Hebrew"


def test_short_and_long_forms_ask_for_what_they_say():
    assert "one sentence" in ChatCommand.expand("/describe_short")
    assert "in detail" in ChatCommand.expand("/describe_long")
    assert "2 to 3 sentences" in ChatCommand.expand("/summarize_short")
    assert "section by section" in ChatCommand.expand("/summarize_long")
    assert ChatCommand.expand("/describe") != ChatCommand.expand("/describe_long")


def test_commands_chain_and_an_unknown_word_stays_text():
    commands, rest = ChatCommand.parse("/describe_short /summarize_long please")
    assert [c.name for c in commands] == ["describe_short", "summarize_long"] and rest == "please"
    assert ChatCommand.parse("/etc/hosts is a file") == ([], "/etc/hosts is a file")
    assert ChatCommand.expand("/describe_medium") == "/describe_medium"


def test_each_form_needs_its_kind_of_file():
    assert ChatCommand.missing_attachment("/describe_long", ["text"]) == "Attach an image to use /describe_long."
    assert "text file" in ChatCommand.missing_attachment("/summarize_short", ["image"])
    assert ChatCommand.missing_attachment("/describe_short /summarize", ["image", "text"]) is None


def test_titles_name_the_file_once():
    files = [("cat.png", "image"), ("report.pdf", "text")]
    assert ChatCommand.title_text("/describe_long", files) == "Describe cat.png"
    assert ChatCommand.title_text("/summarize_short", files) == "Summary of report.pdf"


def test_a_command_without_a_file_needs_none():
    catalog = CommandCatalog([Command("translate", "Translate the message.", "Translate", "Translation")])
    command = catalog.get("translate")
    assert command is not None and command.missing_reason([]) is None


def test_only_one_command_per_kind_fills_the_box():
    catalog = CommandCatalog.default()
    for kind in AttachmentKind:
        assert [c.name for c in catalog.all() if c.prefill_for == kind] in (["describe"], ["summarize"])


@pytest.mark.asyncio
async def test_the_page_gets_every_command(user):
    listed = (await chat_router.list_chat_commands(_user=user)).commands
    names = {c.name for c in listed}
    assert names == {"describe", "describe_short", "describe_long", "summarize", "summarize_short", "summarize_long"}
    summarize = next(c for c in listed if c.name == "summarize")
    assert summarize.prefill_for == "text" and "summarise" in summarize.aliases and summarize.hint
