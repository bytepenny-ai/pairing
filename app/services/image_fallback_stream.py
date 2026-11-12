"""Admin settings > System > Chat > Files in a chat > "Description first, image if needed": a question about an
earlier image goes to the chat's own model with the earlier replies that described it. That model is asked to answer
only NEED_IMAGE when the description isn't enough; then its reply is dropped and the default vision model answers
with the image (reply_generation_service streams whichever this yields).
"""

import copy
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import chat_attachment_service
from app.services.chat_attachment_service import AttachmentInfo
from app.services.inference_client import chat_stream, stop_model

NEED_IMAGE = "NEED_IMAGE"
_INSTRUCTION = (
    "You cannot see the image attached earlier in this chat; only the earlier replies describe it. Only if the message "
    "below asks about a detail of that image which those replies don't mention, reply with exactly "
    f"{NEED_IMAGE} and nothing else. Otherwise, including thanks, greetings and anything not about the image, answer "
    "normally.\n\n---\n\n"
)
SWITCH_NOTE = "_Looking at the image again…_\n\n"


def image_question(system_prompt: str, question: str) -> list[dict]:
    """What the vision model gets for a question about an earlier image: just the question (the image is added to it),
    not the chat. A prompt with an image is never reused from the engine's cache, so with the whole chat a CPU spent
    minutes re-reading it (689 tokens) before the first word."""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": question}]


class ImageFallback:
    def __init__(self, vision_model: str, vision_messages: list[dict]) -> None:
        self.vision_model = vision_model
        self._vision_messages = vision_messages
        self.model = ""  # the model streaming now (reply_generation_service stops this one)

    @classmethod
    async def prepare(
        cls, db: AsyncSession, image: AttachmentInfo, chat_messages: list[dict], vision_messages: list[dict]
    ) -> "ImageFallback | None":
        """Adds the NEED_IMAGE instruction to the newest message of `chat_messages` (in place) and the image to
        `vision_messages` (image_question), for the vision model. None when no vision model is installed."""
        vision_messages = copy.deepcopy(vision_messages)
        vision_model = await chat_attachment_service.apply_image_attachment(db, [image], vision_messages)
        if vision_model is None:
            return None
        chat_messages[-1] = {**chat_messages[-1], "content": _INSTRUCTION + chat_messages[-1]["content"]}
        return cls(vision_model, vision_messages)

    async def stream(self, model: str, chat_messages: list[dict], params: dict) -> AsyncIterator[str | dict]:
        """The chat model's reply, or, when it starts with NEED_IMAGE, a short note and the vision model's reply."""
        self.model = model
        held = ""
        deciding = True
        first = chat_stream(model, chat_messages, params)
        try:
            async for chunk in first:
                if not deciding or isinstance(chunk, dict):
                    yield chunk
                    continue
                held += chunk
                start = held.lstrip()
                if start.startswith(NEED_IMAGE):
                    break
                if not NEED_IMAGE.startswith(start):
                    deciding = False
                    yield held
            else:
                if deciding and held:
                    yield held
                return
        finally:
            await first.aclose()
        await stop_model(model, request_id=params.get("request_id"))
        self.model = self.vision_model
        yield SWITCH_NOTE
        async for chunk in chat_stream(self.vision_model, self._vision_messages, {**params, "model_role": "vision"}):
            yield chunk
