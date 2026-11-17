"""A user's knowledge-base files and folders (Settings > Knowledge): listing, folders, moving and deleting, with one
ownership rule everywhere. Uploading and embedding stay in document_upload.py / document_sync.py.

Folders are a label in the database (Document.folder_id), one level deep: a file never moves on disk, so moving it
costs no re-embedding and can't confuse the folder sync. Anything not the user's own answers 404, not 403, so ids
can't be probed. Shared documents (owner NULL) are deleted only by an admin, as before.
"""

from collections import Counter
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import KNOWLEDGE_DIR
from app.models import Document, DocumentFolder, User
from app.schemas.knowledge_files import FileState, KnowledgeFileOut, KnowledgeFolderOut
from app.services import model_catalog_service

MAX_FOLDERS = 200


class KnowledgeFiles:
    def __init__(self, db: AsyncSession, user: User) -> None:
        self._db = db
        self._user = user

    # Files

    async def files(self, folder_id: str | None) -> list[KnowledgeFileOut]:
        """The user's files at the top level (`folder_id` None) or in one of their folders, newest first."""
        if folder_id is not None:
            await self._folder(folder_id)
        rows = await self._db.execute(
            select(Document)
            .where(Document.owner_id == self._user.id, self._in_folder(folder_id))
            .order_by(Document.created_at.desc())
        )
        model = await model_catalog_service.get_default_embedding_model(self._db)
        return [self._out(d, model) for d in rows.scalars().all()]

    async def move(self, file_ids: list[str], folder_id: str | None) -> int:
        """Moves the user's files to a folder of theirs or to the top level; all or none (404 for any not theirs)."""
        if folder_id is not None:
            await self._folder(folder_id)
        wanted = set(file_ids)
        own = await self._db.execute(
            select(Document.id).where(Document.id.in_(wanted), Document.owner_id == self._user.id)
        )
        if set(own.scalars().all()) != wanted:
            raise HTTPException(status_code=404, detail="Document not found.")
        await self._db.execute(update(Document).where(Document.id.in_(wanted)).values(folder_id=folder_id))
        await self._db.commit()
        return len(wanted)

    async def delete(self, document_id: str) -> None:
        """Deletes a document and its chunks: the user's own, or a shared one for an admin."""
        document = await self._db.get(Document, document_id)
        own = document is not None and document.owner_id == self._user.id
        shared = document is not None and document.owner_id is None and self._user.role == "admin"
        if not (own or shared):
            raise HTTPException(status_code=404, detail="Document not found.")
        # File first: a failure between the steps leaves a row without its file, which the next sync cleans; the
        # other order would silently re-ingest a leftover file.
        (KNOWLEDGE_DIR / document.filename).unlink(missing_ok=True)
        await self._db.delete(document)
        await self._db.commit()

    async def file(self, file_id: str) -> tuple[Path, str]:
        """(where it is on disk, its name) for one of the user's own files or a shared one, to view or download it
        (Settings > Knowledge, and a reply's sources). Every chat searches shared files, so anyone may read them."""
        document = await self._db.get(Document, file_id)
        if document is None or document.owner_id not in (self._user.id, None):
            raise HTTPException(status_code=404, detail="Document not found.")
        return KNOWLEDGE_DIR / document.filename, Path(document.filename).name

    async def delete_many(self, file_ids: list[str]) -> int:
        """Deletes several of the user's own files; all or none (404 when any isn't theirs, before anything goes)."""
        wanted = set(file_ids)
        documents = (
            (
                await self._db.execute(
                    select(Document).where(Document.id.in_(wanted), Document.owner_id == self._user.id)
                )
            )
            .scalars()
            .all()
        )
        if {d.id for d in documents} != wanted:
            raise HTTPException(status_code=404, detail="Document not found.")
        for document in documents:  # files first, as in `delete`
            (KNOWLEDGE_DIR / document.filename).unlink(missing_ok=True)
        for document in documents:
            await self._db.delete(document)
        await self._db.commit()
        return len(documents)

    # Folders

    async def folders(self) -> list[KnowledgeFolderOut]:
        rows = (
            (
                await self._db.execute(
                    select(DocumentFolder)
                    .where(DocumentFolder.owner_id == self._user.id)
                    .order_by(func.lower(DocumentFolder.name))
                )
            )
            .scalars()
            .all()
        )
        counts = Counter(
            (
                await self._db.execute(
                    select(Document.folder_id).where(
                        Document.owner_id == self._user.id, Document.folder_id.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        return [KnowledgeFolderOut(id=f.id, name=f.name, file_count=counts[f.id]) for f in rows]

    async def create_folder(self, name: str) -> KnowledgeFolderOut:
        count = await self._db.scalar(
            select(func.count()).select_from(DocumentFolder).where(DocumentFolder.owner_id == self._user.id)
        )
        if count >= MAX_FOLDERS:
            raise HTTPException(status_code=400, detail=f"You can have at most {MAX_FOLDERS} folders.")
        await self._unique(name)
        folder = DocumentFolder(owner_id=self._user.id, name=name)
        self._db.add(folder)
        await self._db.commit()
        return KnowledgeFolderOut(id=folder.id, name=folder.name, file_count=0)

    async def rename_folder(self, folder_id: str, name: str) -> KnowledgeFolderOut:
        folder = await self._folder(folder_id)
        await self._unique(name, except_id=folder.id)
        folder.name = name
        await self._db.commit()
        return next(f for f in await self.folders() if f.id == folder.id)

    async def delete_folder(self, folder_id: str) -> None:
        """Removes the folder; its files move to the top level (never deleted with it)."""
        folder = await self._folder(folder_id)
        await self._db.execute(update(Document).where(Document.folder_id == folder.id).values(folder_id=None))
        await self._db.delete(folder)
        await self._db.commit()

    # Helpers

    async def _folder(self, folder_id: str) -> DocumentFolder:
        folder = await self._db.get(DocumentFolder, folder_id)
        if folder is None or folder.owner_id != self._user.id:
            raise HTTPException(status_code=404, detail="Folder not found.")
        return folder

    async def _unique(self, name: str, except_id: str | None = None) -> None:
        """409 when the user has another folder by this name (ignoring case)."""
        clash = await self._db.scalar(
            select(DocumentFolder.id).where(
                DocumentFolder.owner_id == self._user.id,
                func.lower(DocumentFolder.name) == name.lower(),
                DocumentFolder.id != (except_id or ""),
            )
        )
        if clash is not None:
            raise HTTPException(status_code=409, detail=f'You already have a folder named "{name}".')

    @staticmethod
    def _in_folder(folder_id: str | None) -> ColumnElement[bool]:
        return Document.folder_id.is_(None) if folder_id is None else Document.folder_id == folder_id

    @staticmethod
    def _out(document: Document, model: str | None) -> KnowledgeFileOut:
        name = Path(document.filename).name
        state: FileState = "ready"
        if not document.chunk_count:
            state = "empty"
        elif model and document.embedding_model != model:
            state = "outdated"
        return KnowledgeFileOut(
            id=document.id,
            name=name,
            extension=Path(name).suffix.lower().lstrip("."),
            size_bytes=document.size_bytes or 0,
            chunk_count=document.chunk_count or 0,
            created_at=document.created_at,
            folder_id=document.folder_id,
            state=state,
        )
