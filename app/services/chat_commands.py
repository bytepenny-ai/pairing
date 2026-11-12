"""Chat commands that start a message: /describe (an attached image) and /summarize (attached files). The chat shows
what the user typed; the model gets the full instruction (expand), so a message can be just the command."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    name: str
    needs: str  # the attachment type it works on: "image" or "text"
    instruction: str
    title: str  # the chat title before the first file name


class ChatCommand:
    COMMANDS = {
        "describe": Command(
            "describe",
            "image",
            # Short on purpose: on a CPU each word of a reply costs about half a second to write, and the chat's own
            # model reads the whole description again before the next message (chat_model_warmup.py). Details it
            # leaves out are fetched later from the image itself (Files in a chat > image follow-ups).
            "Describe the attached image in 3 to 4 sentences: what it shows, any text in it, and anything notable.",
            "Describe",
        ),
        "summarize": Command(
            "summarize",
            "text",
            "Summarize the attached file(s): the main points, key facts and figures, and any conclusions.",
            "Summary of",
        ),
    }
    ALIASES = {"summarise": "summarize", "summary": "summarize"}
    _PATTERN = re.compile(r"^\s*/([a-z]+)\b[ \t]*(.*)$", re.IGNORECASE | re.DOTALL)

    @classmethod
    def parse(cls, content: str) -> tuple[list[Command], str]:
        """The commands a message starts with, in order ("/describe /summarize" for an image and a document; none
        for plain text), and the user's own words after them."""
        commands: list[Command] = []
        rest = content or ""
        while match := cls._PATTERN.match(rest):
            name = match.group(1).lower()
            command = cls.COMMANDS.get(cls.ALIASES.get(name, name))
            if command is None:
                break
            if command not in commands:
                commands.append(command)
            rest = match.group(2)
        return (commands, rest.strip()) if commands else ([], content)

    @classmethod
    def expand(cls, content: str) -> str:
        """The text the model reads: each command's instruction, then any words the user added after them."""
        commands, rest = cls.parse(content)
        if not commands:
            return content
        instructions = "\n".join(command.instruction for command in commands)
        return f"{instructions}\n\n{rest}" if rest else instructions

    @classmethod
    def missing_attachment(cls, content: str, attachment_types: list[str]) -> str | None:
        """Why a command can't run on this message's attachments, or None."""
        commands, _ = cls.parse(content)
        for command in commands:
            if command.needs not in attachment_types:
                what = "an image" if command.needs == "image" else "a text file (PDF, Word, text...)"
                return f"Attach {what} to use /{command.name}."
        return None

    @classmethod
    def title_text(cls, content: str, files: list[tuple[str, str]]) -> str:
        """For the chat title: "Summary of report.pdf" instead of "/summarize". `files`: (filename, type) pairs;
        each command names the first file of its kind."""
        commands, rest = cls.parse(content)
        parts = []
        for command in commands:
            name = next((filename for filename, kind in files if kind == command.needs), None)
            if name:
                parts.append(f"{command.title} {name}")
        if not parts:
            return cls.expand(content)
        return ", ".join(parts) + (f": {rest}" if rest else "")
