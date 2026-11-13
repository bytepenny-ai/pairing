"""How close in meaning a question is to each skill (the "index" layout): cosine similarity of embeddings, 0 to 1.
A skill's vector is kept in memory per embedding model and skill version, so each skill is embedded once."""

import logging
from collections import OrderedDict

import numpy as np

from app.services.inference_client import InferenceError, embed
from app.services.prompt_layout.sections import PromptSection

logger = logging.getLogger(__name__)

_SKILL_CHARS = 1500  # what of a skill is embedded: its name, purpose and the start of its text
_KEEP = 512  # skill vectors kept in memory


class SkillRelevance:
    _vectors: "OrderedDict[tuple[str, str], np.ndarray]" = OrderedDict()

    def __init__(self, embedding_model: str | None) -> None:
        self._model = embedding_model

    @property
    def available(self) -> bool:
        return bool(self._model)

    async def scores(self, question: str, skills: list[PromptSection]) -> dict[str, float] | None:
        """Each skill's score by key, or None when it can't be worked out (no embedding model, or it failed)."""
        if not self._model:
            return None
        try:
            asked = await self._embed(question)
            scores = {}
            for skill in skills:
                vector = await self._skill_vector(skill)
                scores[skill.key] = self._cosine(asked, vector)
        except (InferenceError, ValueError) as error:
            logger.warning("Could not compare the question with the chat's skills: %s", error)
            return None
        return scores

    async def _skill_vector(self, skill: PromptSection) -> np.ndarray:
        key = (self._model or "", skill.digest)
        if key in self._vectors:
            self._vectors.move_to_end(key)
            return self._vectors[key]
        text = f"{skill.title}. {skill.description}\n{skill.text}"[:_SKILL_CHARS]
        vector = await self._embed(text)
        self._vectors[key] = vector
        while len(self._vectors) > _KEEP:
            self._vectors.popitem(last=False)
        return vector

    async def _embed(self, text: str) -> np.ndarray:
        vector = np.asarray(await embed(text, self._model), dtype=np.float32)
        if vector.ndim != 1 or not vector.size:
            raise ValueError("the embedding model returned no vector")
        return vector

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        if a.shape != b.shape:
            raise ValueError("vectors of different sizes (the embedding model changed?)")
        norms = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(a @ b) / norms if norms else 0.0
