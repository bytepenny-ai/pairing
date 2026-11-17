"""Asks for the reply in the user's language when they write in a non-Latin script (Hebrew, Arabic, Cyrillic…):
small models otherwise follow the English around a message (skill text, excerpts, earlier replies). One short line
after the user's words; worked out from the message alone, so later turns rebuild it the same and the prompt cache
keeps matching. The scripts are data (app/language_data/reply_scripts.json)."""

import json
import unicodedata
from functools import cache
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent / "language_data" / "reply_scripts.json"
_SHARE = 0.5  # of the letters, in one script
_OTHER = -1  # a non-Latin script the file doesn't list: the generic line


class ReplyLanguage:
    @staticmethod
    @cache
    def _scripts() -> list[tuple[str | None, list[tuple[int, int]]]]:
        data = json.loads(_FILE.read_text("utf-8"))["scripts"]
        return [(s["language"], [(int(a, 16), int(b, 16)) for a, b in s["ranges"]]) for s in data]

    @classmethod
    def _script_of(cls, char: str) -> int | None:
        code = ord(char)
        for index, (_language, ranges) in enumerate(cls._scripts()):
            if any(low <= code <= high for low, high in ranges):
                return index
        return None

    @classmethod
    def hint(cls, words: str) -> str:
        """The line to add, or "" for Latin script, no letters, or a mix with no main script. A non-Latin script
        missing from the file gets the generic line, so every one is covered."""
        letters = [c for c in words if c.isalpha()]
        if not letters:
            return ""
        counts: dict[int, int] = {}
        for char in letters:
            index = cls._script_of(char)
            if index is None and "LATIN" not in unicodedata.name(char, "LATIN"):
                index = _OTHER
            if index is not None:
                counts[index] = counts.get(index, 0) + 1
        if not counts:
            return ""
        index, count = max(counts.items(), key=lambda item: item[1])
        if count < len(letters) * _SHARE:
            return ""
        language = cls._scripts()[index][0] if index != _OTHER else None
        return f"(Reply in {language}.)" if language else "(Reply in the language of this message.)"

    @classmethod
    def add(cls, text: str, words: str) -> str:
        """`text` (what the model reads) with the hint for the user's own `words` after it."""
        hint = cls.hint(words)
        return f"{text}\n\n{hint}" if hint and text else text
