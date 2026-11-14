"""/use_skill "<skill>": the user picks one of the chat's skills for one message (the chat's "/" menu offers it under
the "Short index" prompt cache layout when skills are chosen by command; prompt_layout/index.py applies it). It can
be anywhere in the message (the chat puts it at the start), with the skill's name in quotes so a name with spaces is
never confused with the user's words. The model never sees the command: ChatCommand.expand takes it out."""

import re

NAME = "use_skill"
_COMMAND = re.compile(r'(?<![^\s])/use_skill\s+"([^"\n]+)"', re.IGNORECASE)  # at the start or after a space


class SkillCommand:
    @staticmethod
    def parse(content: str) -> tuple[str | None, str]:
        """(the skill asked for, or None, and the message without the command: its first one, the words on either
        side joined by one space)."""
        text = content or ""
        match = _COMMAND.search(text)
        if match is None:
            return None, text
        left, right = text[: match.start()].rstrip(" \t"), text[match.end() :].lstrip(" \t")
        joined = f"{left} {right}" if left and right and not left.endswith("\n") else left + right
        return " ".join(match.group(1).split()), joined.strip()
