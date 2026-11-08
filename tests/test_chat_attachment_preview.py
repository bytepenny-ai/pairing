"""The chat file viewer's text previews (GET /api/chat/attachments/{id}/preview) and how attachments are served."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models import Message, MessageAttachment
from app.routers import chat as chat_router
from app.schemas import ConversationCreate
from app.services import chat_attachment_preview, conversation_service
from app.services.chat_attachment_preview import AttachmentPreviewer
from app.services.chat_attachment_service import AttachmentServing


async def _attach(db, user, tmp_path: Path, filename: str, content: bytes, kind: str = "text") -> str:
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    (tmp_path / conversation.id).mkdir()
    (tmp_path / conversation.id / f"abc_{filename}").write_bytes(content)
    message = Message(conversation_id=conversation.id, role="user", content="see attached", sender_id=user.id)
    message.attachments = [MessageAttachment(path=f"{conversation.id}/abc_{filename}", filename=filename, type=kind)]
    db.add(message)
    await db.commit()
    return message.attachments[0].id


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(chat_attachment_preview, "ATTACHMENTS_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_markdown_is_previewed_as_markdown(db, user, folder: Path) -> None:
    attachment_id = await _attach(db, user, folder, "notes.md", b"# Title\n\nSome *text*")
    preview = await chat_router.preview_attachment(attachment_id, db=db, user=user)
    assert (preview.format, preview.text, preview.truncated) == ("markdown", "# Title\n\nSome *text*", False)


@pytest.mark.asyncio
async def test_html_is_previewed_as_its_text_never_as_html(db, user, folder: Path) -> None:
    attachment_id = await _attach(db, user, folder, "page.html", b"<p>Hello</p><script>alert(1)</script>")
    preview = await chat_router.preview_attachment(attachment_id, db=db, user=user)
    assert preview.format == "text"
    assert "Hello" in preview.text and "<script>" not in preview.text and "alert" not in preview.text


@pytest.mark.asyncio
async def test_csv_is_previewed_as_written(db, user, folder: Path) -> None:
    attachment_id = await _attach(db, user, folder, "data.csv", b"a,b\n1,2\n")
    preview = await chat_router.preview_attachment(attachment_id, db=db, user=user)
    assert preview.text == "a,b\n1,2\n"


@pytest.mark.asyncio
async def test_a_long_file_is_cut_and_marked(db, user, folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_attachment_preview, "_MAX_CHARS", 10)
    attachment_id = await _attach(db, user, folder, "long.txt", b"x" * 25)
    preview = await chat_router.preview_attachment(attachment_id, db=db, user=user)
    assert (preview.text, preview.truncated) == ("x" * 10, True)


@pytest.mark.asyncio
async def test_a_damaged_document_gives_a_clear_error(db, user, folder: Path) -> None:
    attachment_id = await _attach(db, user, folder, "broken.docx", b"not a docx")
    with pytest.raises(HTTPException) as exc_info:
        await chat_router.preview_attachment(attachment_id, db=db, user=user)
    assert (exc_info.value.status_code, exc_info.value.detail) == (422, "This file could not be read")


@pytest.mark.asyncio
async def test_an_image_has_no_text_preview(db, user, folder: Path) -> None:
    attachment_id = await _attach(db, user, folder, "photo.png", b"\x89PNG", kind="image")
    with pytest.raises(HTTPException) as exc_info:
        await chat_router.preview_attachment(attachment_id, db=db, user=user)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_preview_checks_access_to_the_conversation(db, user, admin_user, folder: Path) -> None:
    attachment_id = await _attach(db, user, folder, "notes.txt", b"private")
    with pytest.raises(HTTPException) as exc_info:
        await chat_router.preview_attachment(attachment_id, db=db, user=admin_user)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_previewer_reads_from_the_folder_it_is_given(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi")
    attachment = MessageAttachment(path="a.txt", filename="a.txt", type="text")
    preview = await AttachmentPreviewer(tmp_path).preview(attachment)
    assert preview.text == "hi"


def test_a_pdf_is_served_inline_for_the_browser_viewer() -> None:
    assert AttachmentServing.for_file("text", "report.PDF") == AttachmentServing("application/pdf", "inline")
