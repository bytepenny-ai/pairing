"""Whether a model can read each chat attachment, checked when the file is picked (POST /api/chat/attachments/check)
and again on send: a real image and a vision model to read it, or a document with text in it. Plain-words reasons.
A long document also gets a warning of how long the reply may take to start, from the chat model's measured reading
speed (read_speed.py)."""

import asyncio
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MAX_ATTACHMENT_MB
from app.models import Conversation
from app.schemas.chat import AttachmentVerdictOut
from app.services import context_window_setting, model_catalog_service
from app.services.chat_attachment_service import SUPPORTED_IMAGE_EXTENSIONS
from app.services.chat_commands import ChatCommand
from app.services.document_extract import SUPPORTED_EXTENSIONS, extract_text
from app.services.engines.registry import registry
from app.services.read_speed import ReadSpeed
from app.services.turn_context_fit import TokenEstimate


class AttachmentCheck:
    # The first bytes of each image type chats take.
    _IMAGE_SIGNATURES = (b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")

    # Without a measured speed, a file this many tokens long gets a general "long file" warning.
    _LONG_TOKENS = 3000
    _WARN_SECONDS = 60

    def __init__(self, db: AsyncSession, conversation: Conversation | None = None) -> None:
        self._db = db
        self._conversation = conversation
        self._vision: str | None | bool = False  # looked up once, on the first image

    async def check_uploads(self, uploads: list[UploadFile]) -> list[AttachmentVerdictOut]:
        verdicts = []
        for upload in uploads:
            verdicts.append(await self.verdict(upload.filename or "", await upload.read()))
            await upload.seek(0)  # the send path saves the same upload next
        return verdicts

    async def require_readable(self, content: str, uploads: list[UploadFile]) -> None:
        """On send: a 400 with the first reason, before anything is saved or streamed."""
        verdicts = await self.check_uploads(uploads)
        bad = next((v for v in verdicts if not v.ok), None)
        if bad is not None:
            raise HTTPException(status_code=400, detail=bad.reason)
        missing = ChatCommand.missing_attachment(content, [v.kind for v in verdicts])
        if missing:
            raise HTTPException(status_code=400, detail=missing)

    async def verdict(self, filename: str, raw: bytes) -> AttachmentVerdictOut:
        suffix = Path(filename).suffix.lower()
        kind = "image" if suffix in SUPPORTED_IMAGE_EXTENSIONS else "text" if suffix in SUPPORTED_EXTENSIONS else None

        def no(reason: str) -> AttachmentVerdictOut:
            return AttachmentVerdictOut(filename=filename, kind=kind, ok=False, reason=reason)

        if kind is None:
            return no(
                f"{filename}: chats can't read {suffix or 'this'} files. Use an image or a text, PDF or Word file."
            )
        if len(raw) > MAX_ATTACHMENT_MB * 1024 * 1024:
            return no(f"{filename} is larger than the {MAX_ATTACHMENT_MB} MB limit.")
        if not raw:
            return no(f"{filename} is empty.")
        if kind == "image":
            reason, warning = await self._image_problem(filename, raw), None
        else:
            reason, text = await self._text_problem(filename, raw, suffix)
            warning = None if reason else await self._wait_warning(filename, text)
        if reason:
            return no(reason)
        return AttachmentVerdictOut(filename=filename, kind=kind, ok=True, warning=warning)

    async def _wait_warning(self, filename: str, text: str) -> str | None:
        """How long the chat model may need to read `text` before its reply starts, when that's long."""
        if self._conversation is None:
            return None
        tokens = min(TokenEstimate.of(text), await context_window_setting.get_num_ctx(self._db))
        speed = await ReadSpeed(self._db).tokens_per_second(self._conversation.model, self._conversation.id)
        if speed:
            seconds = tokens / speed
            if seconds >= self._WARN_SECONDS:
                return (
                    f"{filename} is long: on this server the reply may take {ReadSpeed.wait_words(seconds)} to start."
                )
            return None
        if tokens >= self._LONG_TOKENS:
            return f"{filename} is long. Without a GPU, reading it can take many minutes before the reply starts."
        return None

    async def _image_problem(self, filename: str, raw: bytes) -> str | None:
        is_webp = raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
        if not (raw.startswith(self._IMAGE_SIGNATURES) or is_webp):
            return f"{filename} isn't a readable picture (it may be damaged, or another kind of file renamed)."
        if not registry.active().capabilities.vision:
            return "The active engine can't read images. Ask an admin to switch to Matricxon or llama.cpp."
        if self._vision is False:
            self._vision = await model_catalog_service.get_default_vision_model(self._db)
        if not self._vision:
            return (
                "No model here can read images yet. Ask an admin to install a vision model (Admin settings → Models)."
            )
        return None

    @staticmethod
    async def _text_problem(filename: str, raw: bytes, suffix: str) -> tuple[str | None, str]:
        """(why it can't be read, or None; its text)."""
        try:
            text = await asyncio.to_thread(extract_text, raw, suffix)
        except Exception:  # noqa: BLE001 - any parser failure means the same thing to the user
            return f"{filename} can't be read: it may be damaged, password-protected or not really a {suffix} file.", ""
        if text.strip():
            return None, text
        if suffix == ".pdf":
            return (
                f"No text found in {filename}: it looks like a scanned PDF (pictures of pages). Copy its text into "
                "the chat, or add it to the Knowledge base, which can read scanned PDFs."
            ), ""
        return f"No text found in {filename}: the file is empty.", ""
