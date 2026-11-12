"""The chat commands a message can start with (/describe, /summarize and their short and long forms): each a `Command`
with its own instruction for the model, what it needs attached, and what the chat shows about it. `CommandCatalog`
holds them and their aliases; chat_commands.py parses messages with it, and GET /api/chat/commands lists it for the
page (the "/" menu, and the command put in the box when a file is attached: chat_command_menu.js).

Adding a command is one more `Command` in `CommandCatalog.default()`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class AttachmentKind(StrEnum):
    IMAGE = "image"
    TEXT = "text"

    @property
    def described(self) -> str:
        return "an image" if self is AttachmentKind.IMAGE else "a text file (PDF, Word, text...)"


@dataclass(frozen=True)
class Command:
    name: str
    instruction: str  # what the model reads in place of the command
    description: str  # one line for the "/" menu
    title: str  # the chat title before the first file's name ("Summary of report.pdf")
    needs: AttachmentKind | None = None  # None: works on the message's own words
    prefill_for: AttachmentKind | None = None  # attaching this kind puts this command in the box
    hint: str = ""  # under the box while the command waits: "Send /describe to <hint>"
    aliases: tuple[str, ...] = ()

    def missing_reason(self, attached: Iterable[str]) -> str | None:
        """Why it can't run on these attachment kinds, or None."""
        if self.needs is None or self.needs in set(attached):
            return None
        return f"Attach {self.needs.described} to use /{self.name}."


class CommandCatalog:
    def __init__(self, commands: Iterable[Command]) -> None:
        self._commands = {command.name: command for command in commands}
        self._aliases = {alias: c.name for c in self._commands.values() for alias in c.aliases}

    def get(self, name: str) -> Command | None:
        name = name.lower()
        return self._commands.get(self._aliases.get(name, name))

    def all(self) -> list[Command]:
        return list(self._commands.values())

    @classmethod
    def default(cls) -> "CommandCatalog":
        image, text = AttachmentKind.IMAGE, AttachmentKind.TEXT
        return cls(
            [
                Command(
                    "describe",
                    # Short on purpose: on a CPU each word of a reply costs about half a second, and a separate
                    # vision model's description is read again by the chat model before the next message.
                    "Describe the attached image in 3 to 4 sentences: what it shows, any text in it, and anything "
                    "notable.",
                    "Describe the attached image in a few sentences",
                    "Describe",
                    needs=image,
                    prefill_for=image,
                    hint="describe the image",
                ),
                Command(
                    "describe_short",
                    "Describe the attached image in one sentence.",
                    "Describe the attached image in one sentence",
                    "Describe",
                    needs=image,
                    hint="describe the image in one sentence",
                ),
                Command(
                    "describe_long",
                    "Describe the attached image in detail: everything it shows, its layout, colors and style, all "
                    "the text in it, and anything notable. Use a few paragraphs.",
                    "Describe the attached image in detail (slower on a CPU)",
                    "Describe",
                    needs=image,
                    hint="describe the image in detail",
                ),
                Command(
                    "summarize",
                    "Summarize the attached file(s): the main points, key facts and figures, and any conclusions.",
                    "Summarize the attached files",
                    "Summary of",
                    needs=text,
                    prefill_for=text,
                    hint="summarize the files",
                    aliases=("summarise", "summary"),
                ),
                Command(
                    "summarize_short",
                    "Summarize the attached file(s) in 2 to 3 sentences: only the main point and the most "
                    "important fact.",
                    "Summarize the attached files in 2 to 3 sentences",
                    "Summary of",
                    needs=text,
                    hint="summarize the files in 2 to 3 sentences",
                    aliases=("summarise_short",),
                ),
                Command(
                    "summarize_long",
                    "Summarize the attached file(s) in detail, section by section: the main points, key facts and "
                    "figures, arguments, and conclusions. Use headings and bullet points.",
                    "Summarize the attached files in detail, section by section (slower on a CPU)",
                    "Summary of",
                    needs=text,
                    hint="summarize the files in detail",
                    aliases=("summarise_long",),
                ),
            ]
        )
