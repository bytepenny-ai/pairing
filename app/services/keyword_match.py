"""Keyword part of RAG search (chunk_vector_index.py): a small embedding model can miss a rare exact term, such as a
name or acronym, that a question and a passage share. Each passage gets 0 to 1 from the share of the question's words
it contains (rarer words weigh more, common ones in language_data/common_words.json nothing) and from how many: one
shared word alone is weak evidence, such as "AI" in a question about AI in general, and adds nothing."""

import json
import math
import re
from pathlib import Path

import numpy as np

_WORD = re.compile(r"\w{2,}")
_COMMON_FILE = Path(__file__).resolve().parent.parent / "language_data" / "common_words.json"
_MIN_AFFIX = 3  # shorter words match only exactly
_MAX_EXTRA = 2  # a word matches another with up to this many more letters at either end (plurals, prefixes)


def _common_words() -> frozenset[str]:
    data = json.loads(_COMMON_FILE.read_text(encoding="utf-8"))
    return frozenset(word for key, words in data.items() if not key.startswith("_") for word in words)


_COMMON = _common_words()


class KeywordMatch:
    """The words of each passage, for `share`. Rows follow the order of `texts`."""

    def __init__(self, texts: list[str]) -> None:
        self._count = len(texts)
        postings: dict[str, list[int]] = {}
        for row, text in enumerate(texts):
            for word in set(self.words(text)):
                postings.setdefault(word, []).append(row)
        self._postings = {word: np.asarray(rows, dtype=np.int64) for word, rows in postings.items()}
        # Words by their first and last letters, to find close forms without reading every word.
        self._by_start: dict[str, list[str]] = {}
        self._by_end: dict[str, list[str]] = {}
        for word in postings:
            if len(word) >= _MIN_AFFIX:
                self._by_start.setdefault(word[:_MIN_AFFIX], []).append(word)
                self._by_end.setdefault(word[-_MIN_AFFIX:], []).append(word)

    @staticmethod
    def words(text: str) -> list[str]:
        return _WORD.findall(text.lower())

    def strength(self, question: str) -> np.ndarray:
        """Per passage, 0 to 1: the share of the question's word weight found in it, squared, times (n - 1) / n for
        n words found: 0 for one word, 1/2 for two, 3/4 for four."""
        found = np.zeros(self._count, dtype=np.float32)
        matched = np.zeros(self._count, dtype=np.float32)
        total = 0.0
        for word in set(self.words(question)) - _COMMON:
            rows = self._rows(word)
            weight = math.log((self._count + 1) / (len(rows) + 0.5))  # a word in fewer passages weighs more
            total += weight
            found[rows] += weight
            matched[rows] += 1
        if total <= 0:
            return found
        return (found / total) ** 2 * np.maximum(matched - 1, 0) / np.maximum(matched, 1)

    def _rows(self, word: str) -> np.ndarray:
        """Passages with `word` or a close form of it (a word that starts or ends with it, a few letters longer)."""
        matches = [self._postings[word]] if word in self._postings else []
        if len(word) >= _MIN_AFFIX:
            matches += [self._postings[other] for other in self._close(word)]
        return np.unique(np.concatenate(matches)) if matches else np.empty(0, dtype=np.int64)

    def _close(self, word: str) -> set[str]:
        close = set()
        candidates = self._by_start.get(word[:_MIN_AFFIX], []) + self._by_end.get(word[-_MIN_AFFIX:], [])
        for other in candidates:
            if other == word or abs(len(other) - len(word)) > _MAX_EXTRA:
                continue
            longer, shorter = (other, word) if len(other) > len(word) else (word, other)
            if longer.startswith(shorter) or longer.endswith(shorter):
                close.add(other)
        return close
