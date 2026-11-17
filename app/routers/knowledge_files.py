"""Settings > Knowledge's file browser: the user's own files and folders (app/services/knowledge_files.py). Uploads
stay on /api/documents/upload (with an optional folder_id)."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import OkResponse
from app.schemas.chat import AttachmentPreviewOut
from app.schemas.knowledge_files import (
    KnowledgeDeleteIn,
    KnowledgeFileOut,
    KnowledgeFolderIn,
    KnowledgeFolderOut,
    KnowledgeMoveIn,
)
from app.services.auth_service import get_current_user
from app.services.chat_attachment_preview import AttachmentPreviewer
from app.services.chat_attachment_service import AttachmentServing
from app.services.knowledge_files import KnowledgeFiles

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/files", response_model=list[KnowledgeFileOut])
async def list_files(
    folder_id: str | None = None, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[KnowledgeFileOut]:
    """The top level's files (no `folder_id`) or one folder's."""
    return await KnowledgeFiles(db, user).files(folder_id)


@router.get("/files/{file_id}")
async def get_file(
    file_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> FileResponse:
    """One of the user's files or a shared one, for the viewer and Download: a PDF inline (the browser's viewer),
    anything else as a download that never runs in the page (as chat attachments)."""
    path, name = await KnowledgeFiles(db, user).file(file_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found.")
    serving = AttachmentServing.for_file("text", name)
    return FileResponse(
        path,
        filename=name,
        media_type=serving.media_type,
        content_disposition_type=serving.disposition,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/files/{file_id}/preview", response_model=AttachmentPreviewOut)
async def preview_file(
    file_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> AttachmentPreviewOut:
    """The file as text, for the viewer (as a chat attachment's preview)."""
    path, name = await KnowledgeFiles(db, user).file(file_id)
    return await AttachmentPreviewer().preview_file(path, name)


@router.post("/files/move", response_model=OkResponse)
async def move_files(
    body: KnowledgeMoveIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> OkResponse:
    await KnowledgeFiles(db, user).move(body.file_ids, body.folder_id)
    return OkResponse()


@router.post("/files/delete", response_model=OkResponse)
async def delete_files(
    body: KnowledgeDeleteIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> OkResponse:
    """Deletes several of the user's own files at once (all or none)."""
    await KnowledgeFiles(db, user).delete_many(body.file_ids)
    return OkResponse()


@router.delete("/files/{file_id}", response_model=OkResponse)
async def delete_file(
    file_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> OkResponse:
    await KnowledgeFiles(db, user).delete(file_id)
    return OkResponse()


@router.get("/folders", response_model=list[KnowledgeFolderOut])
async def list_folders(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[KnowledgeFolderOut]:
    return await KnowledgeFiles(db, user).folders()


@router.post("/folders", response_model=KnowledgeFolderOut)
async def create_folder(
    body: KnowledgeFolderIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> KnowledgeFolderOut:
    return await KnowledgeFiles(db, user).create_folder(body.name)


@router.put("/folders/{folder_id}", response_model=KnowledgeFolderOut)
async def rename_folder(
    folder_id: str, body: KnowledgeFolderIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> KnowledgeFolderOut:
    return await KnowledgeFiles(db, user).rename_folder(folder_id, body.name)


@router.delete("/folders/{folder_id}", response_model=OkResponse)
async def delete_folder(
    folder_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> OkResponse:
    """Its files move to the top level."""
    await KnowledgeFiles(db, user).delete_folder(folder_id)
    return OkResponse()
