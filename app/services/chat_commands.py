"""Chat commands that start a message (/describe, /summarize and their short and long forms; the catalog is
chat_command_catalog.py). The chat shows what the user typed; the model gets the full instruction (expand), so a
message can be just the command. Several can be chained: "/describe /summarize" for an image and a document."""

import re

from app.services.chat_command_catalog import Command, CommandCatalog


class ChatCommand:
    CATALOG = CommandCatalog.default()
    _PATTERN = re.compile(r"^\s*/([a-z][a-z_]*)\b[ \t]*(.*)$", re.IGNORECASE | re.DOTALL)

    @classmethod
    def parse(cls, content: str) -> tuple[list[Command], str]:
        """The commands a message starts with, in order (none for plain text, or a "/word" that isn't a command),
        and the user's own words after them."""
        commands: list[Command] = []
        rest = content or ""
        while match := cls._PATTERN.match(rest):
            command = cls.CATALOG.get(match.group(1))
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
        return next((r for c in commands if (r := c.missing_reason(attachment_types))), None)

    @classmethod
    def title_text(cls, content: str, files: list[tuple[str, str]]) -> str:
        """For the chat title: "Summary of report.pdf" instead of "/summarize". `files`: (filename, type) pairs;
        each command names the first file of its kind."""
        commands, rest = cls.parse(content)
        parts = []
        for command in commands:
            name = next((filename for filename, kind in files if kind == command.needs), None)
            if name and f"{command.title} {name}" not in parts:
                parts.append(f"{command.title} {name}")
        if not parts:
            return cls.expand(content)
        return ", ".join(parts) + (f": {rest}" if rest else "")
