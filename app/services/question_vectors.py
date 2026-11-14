"""One embedding per question, shared: the knowledge-base search (document_retrieval.py), a file's matching parts
(chat_follow_up.py) and the skill pre-check (prompt_layout/skill_relevance.py) all embed the message being answered.
Each asked separately; now the first call embeds it and the others reuse that vector, so a reply costs one embedding
call however many of them run."""

from collections import OrderedDict
from collections.abc import Awaitable, Callable

import numpy as np

Embed = Callable[[str, str], Awaitable[list[float]]]

_KEEP = 256  # recent (model, text) pairs; a reply's callers run within seconds of each other


class QuestionVectors:
    _vectors: "OrderedDict[tuple[int, str, str], np.ndarray]" = OrderedDict()

    @classmethod
    async def of(cls, text: str, model: str, embed: Embed) -> np.ndarray:
        """The text's embedding with `model`, by the caller's `embed` (inference_client.embed; raises InferenceError).
        Keyed by that function too, so a test's fake never gets another's vectors."""
        key = (id(embed), model, text)
        if key in cls._vectors:
            cls._vectors.move_to_end(key)
            return cls._vectors[key]
        vector = np.asarray(await embed(text, model), dtype=np.float32)
        cls._vectors[key] = vector
        while len(cls._vectors) > _KEEP:
            cls._vectors.popitem(last=False)
        return vector
