"""Words that tell what a question is about, per language: kept as data, so the code holds no language's words.
The shipped file (app/language_data/question_words.json) has English; a server adds its own languages in
question_words.local.json beside it (not in git, so updates keep it). Each entry is a regular expression part per
language; a question matches when any language's part does."""

import json
import re
from functools import cache
from pathlib import Path

_FOLDER = Path(__file__).resolve().parent.parent / "language_data"


class QuestionWords:
    @staticmethod
    @cache
    def pattern(kind: str) -> re.Pattern[str]:
        """`kind`: an entry of the files, e.g. "about_an_image" or "asks"."""
        parts: dict[str, str] = {}
        for name in ("question_words.json", "question_words.local.json"):
            path = _FOLDER / name
            if path.is_file():
                parts.update(json.loads(path.read_text("utf-8")).get(kind, {}))
        return re.compile("|".join(f"(?:{part})" for part in parts.values()), re.IGNORECASE)
