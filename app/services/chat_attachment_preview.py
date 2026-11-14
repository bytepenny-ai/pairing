"""Text previews of chat attachments, and of knowledge-base files (knowledge_files.py), for the file viewer
(chat_file_viewer.js; Settings > Knowledge uses it too).

Documents show as text: Markdown as Markdown, plain text formats as they are, and .docx/.odt/.rtf/.pdf/.html as
their extracted text (never as HTML, which would run in the page). A PDF opens in the browser's own viewer where
there is one; this text is its fallback (phones).
"""

import asyncio
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ATTACHMENTS_DIR
from app.models import Message, MessageAttachment, User
from app.schemas.chat import AttachmentPreviewOut
from app.services import conversation_service
from app.services.document_extract import SUPPORTED_EXTENSIONS, extract_text
from app.services.text_files import TextFiles

_RAW_TEXT = {".txt", ".md", ".csv", ".json"}  # shown as written, not reformatted
_MAX_CHARS = 200_000  # a preview, not the whole of a huge file


async def get_accessible_attachment(db: AsyncSession, attachment_id: str, user: User) -> MessageAttachment:
    """The attachment, if `user` may see its conversation; 404 otherwise."""
    attachment = await db.get(MessageAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    # By message_id: `attachment.message` is not eagerly loaded and would fail here (MissingGreenlet).
    message = await db.get(Message, attachment.message_id)
    await conversation_service.get_accessible_conversation_or_404(db, message.conversation_id, user)
    return attachment


class AttachmentPreviewer:
    def __init__(self, folder: Path | None = None) -> None:
        self._folder = folder or ATTACHMENTS_DIR

    async def preview(self, attachment: MessageAttachment) -> AttachmentPreviewOut:
        if attachment.type == "image":
            raise HTTPException(status_code=422, detail="This file has no text preview")
        return await self.preview_file(self._folder / attachment.path, attachment.filename or "")

    async def preview_file(self, path: Path, filename: str) -> AttachmentPreviewOut:
        """Any document or text file as text (422 for a file with no text, or one that can't be read)."""
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS and not TextFiles.readable_path(path):
            raise HTTPException(status_code=422, detail="This file has no text preview")
        try:
            text = await asyncio.to_thread(self._read, path, suffix)
        except Exception as exc:  # a missing file, or a parser's own error on a damaged one
            raise HTTPException(status_code=422, detail="This file could not be read") from exc
        return AttachmentPreviewOut(
            filename=filename,
            format="markdown" if suffix == ".md" else "text",
            text=text[:_MAX_CHARS],
            truncated=len(text) > _MAX_CHARS,
        )

    @staticmethod
    def _read(path: Path, suffix: str) -> str:
        raw = path.read_bytes()
        if suffix in _RAW_TEXT:
            return raw.decode("utf-8", errors="replace")
        return extract_text(raw, suffix)
