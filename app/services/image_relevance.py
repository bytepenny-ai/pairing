"""How close a question is in meaning to an earlier image's description (chat_follow_up.py): one embedding of the
question compared with the reply that described the image, from 0 (unrelated) to 1. Above the admin's "about the
image" mark the image is used; below the "unrelated" mark it never is; in between the recency rule decides.
The description's vector is saved next to the image ("<image>.about.npz"), so it is embedded once.
"""

import logging
import os
from pathlib import Path

import numpy as np

from app.services.inference_client import InferenceError, embed

logger = logging.getLogger(__name__)

_ABOUT_SUFFIX = ".about.npz"


class ImageRelevance:
    def __init__(self, embedding_model: str) -> None:
        self._model = embedding_model

    @staticmethod
    def about_path(image: Path) -> Path:
        return image.with_name(image.name + _ABOUT_SUFFIX)

    async def score(self, question_vector: np.ndarray, image: Path, description: str) -> float | None:
        """Cosine similarity of the question and the description; None when it can't be worked out."""
        about = await self._description_vector(image, description)
        if about is None or about.shape != question_vector.shape:
            return None
        norms = float(np.linalg.norm(about) * np.linalg.norm(question_vector))
        return float(about @ question_vector) / norms if norms else None

    async def _description_vector(self, image: Path, description: str) -> np.ndarray | None:
        saved = self.about_path(image)
        try:
            with np.load(saved, allow_pickle=False) as data:
                if str(data["model"]) == self._model:
                    return data["vector"]
        except (OSError, KeyError, ValueError):
            pass
        if not description.strip():
            return None
        try:
            vector = np.asarray(await embed(description, self._model), dtype=np.float32)
        except InferenceError as error:
            logger.warning("Could not embed the description of %s: %s", image.name, error)
            return None
        temporary = saved.with_name(saved.name + ".tmp.npz")
        try:
            np.savez(temporary, vector=vector, model=np.array(self._model))
            os.replace(temporary, saved)
        except OSError as error:
            logger.warning("Could not save the description vector of %s: %s", image.name, error)
        return vector
