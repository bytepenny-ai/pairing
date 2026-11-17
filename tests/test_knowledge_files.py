"""Settings > Knowledge's file browser: a user's files and folders (app/services/knowledge_files.py,
routers/knowledge_files.py) and uploading into a folder (document_upload.py)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import KNOWLEDGE_DIR
from app.models import Document
from app.routers import knowledge_files as routes
from app.schemas.knowledge_files import KnowledgeFolderIn, KnowledgeMoveIn
from app.services import document_upload, model_catalog_service
from app.services.knowledge_files import KnowledgeFiles


@pytest.fixture(autouse=True)
def embedding_model(monkeypatch):
    async def current(_db):
        return "embed-v2"

    monkeypatch.setattr(model_catalog_service, "get_default_embedding_model", current)


async def doc(db, owner, name: str, chunks: int = 3, model: str = "embed-v2", folder_id=None) -> Document:
    owner_id = owner.id if owner else None
    path = f"users/{owner_id}/{name}" if owner else f"global/{name}"
    document = Document(
        owner_id=owner_id,
        filename=path,
        content_hash="x",
        chunk_count=chunks,
        size_bytes=2048,
        embedding_model=model,
        folder_id=folder_id,
    )
    db.add(document)
    await db.commit()
    return document


@pytest.mark.asyncio
async def test_files_show_their_state_and_live_at_the_top_level_or_in_a_folder(db, user):
    files = KnowledgeFiles(db, user)
    folder = await files.create_folder("Reports")
    await doc(db, user, "notes.md")
    await doc(db, user, "old.pdf", model="embed-v1")
    await doc(db, user, "scan.pdf", chunks=0)
    await doc(db, user, "q3.docx", folder_id=folder.id)

    top = {f.name: f for f in await files.files(None)}
    assert set(top) == {"notes.md", "old.pdf", "scan.pdf"}
    assert (top["notes.md"].state, top["old.pdf"].state, top["scan.pdf"].state) == ("ready", "outdated", "empty")
    assert top["notes.md"].extension == "md" and top["notes.md"].size_bytes == 2048
    assert [f.name for f in await files.files(folder.id)] == ["q3.docx"]
    assert [(f.name, f.file_count) for f in await files.folders()] == [("Reports", 1)]


@pytest.mark.asyncio
async def test_folder_names_are_tidy_unique_per_user_and_renamable(db, user, admin_user):
    files = KnowledgeFiles(db, user)
    assert KnowledgeFolderIn(name="  Tax   2026 ").name == "Tax 2026"
    with pytest.raises(ValidationError):
        KnowledgeFolderIn(name="a/b")
    first = await files.create_folder("Tax")
    with pytest.raises(HTTPException) as clash:
        await files.create_folder("tax")
    assert clash.value.status_code == 409
    await KnowledgeFiles(db, admin_user).create_folder("Tax")  # another user's: no clash
    assert (await files.rename_folder(first.id, "Taxes")).name == "Taxes"


@pytest.mark.asyncio
async def test_moving_is_all_or_none_and_only_between_the_users_own(db, user, admin_user):
    files = KnowledgeFiles(db, user)
    folder = await files.create_folder("Work")
    mine, theirs = await doc(db, user, "a.txt"), await doc(db, admin_user, "b.txt")
    with pytest.raises(HTTPException) as foreign:
        await files.move([mine.id, theirs.id], folder.id)
    assert foreign.value.status_code == 404
    await db.refresh(mine)
    assert mine.folder_id is None  # nothing moved
    await files.move([mine.id], folder.id)
    await db.refresh(mine)
    assert mine.folder_id == folder.id
    other_folder = await KnowledgeFiles(db, admin_user).create_folder("Theirs")
    with pytest.raises(HTTPException):
        await files.move([mine.id], other_folder.id)  # not their folder
    await files.move([mine.id], None)
    await db.refresh(mine)
    assert mine.folder_id is None


@pytest.mark.asyncio
async def test_deleting_a_folder_keeps_its_files_at_the_top_level(db, user):
    files = KnowledgeFiles(db, user)
    folder = await files.create_folder("Old")
    kept = await doc(db, user, "keep.md", folder_id=folder.id)
    await files.delete_folder(folder.id)
    await db.refresh(kept)
    assert kept.folder_id is None and await files.folders() == []


@pytest.mark.asyncio
async def test_only_own_files_or_shared_ones_for_an_admin_can_be_deleted(db, user, admin_user):
    shared, theirs = await doc(db, None, "handbook.pdf"), await doc(db, admin_user, "x.md")
    for document in (shared, theirs):
        with pytest.raises(HTTPException) as hidden:
            await KnowledgeFiles(db, user).delete(document.id)
        assert hidden.value.status_code == 404
    await KnowledgeFiles(db, admin_user).delete(shared.id)
    assert await db.get(Document, shared.id) is None


@pytest.mark.asyncio
async def test_the_routes_hand_over_to_the_service(db, user):
    folder = await routes.create_folder(KnowledgeFolderIn(name="Inbox"), db, user)
    document = await doc(db, user, "r.md")
    await routes.move_files(KnowledgeMoveIn(file_ids=[document.id], folder_id=folder.id), db, user)
    assert [f.name for f in await routes.list_files(folder.id, db, user)] == ["r.md"]
    await routes.delete_folder(folder.id, db, user)
    assert [f.name for f in await routes.list_files(None, db, user)] == ["r.md"]


@pytest.mark.asyncio
async def test_an_upload_goes_into_the_folder_it_was_added_from(db, user, admin_user):
    folder = await KnowledgeFiles(db, user).create_folder("Inbox")
    assert await document_upload.upload_folder(db, user, "mine", folder.id) == folder.id
    assert await document_upload.upload_folder(db, user, "mine", None) is None
    for scope, folder_id, status in (("global", folder.id, 400), ("mine", "nope", 404)):
        with pytest.raises(HTTPException) as refused:
            await document_upload.upload_folder(db, user, scope, folder_id)
        assert refused.value.status_code == status
    with pytest.raises(HTTPException):
        await document_upload.upload_folder(db, admin_user, "mine", folder.id)  # someone else's folder
    added = await doc(db, user, "new.pdf")
    await document_upload._put_in_folder(db, KNOWLEDGE_DIR / "users" / user.id, ["new.pdf"], folder.id)
    await db.refresh(added)
    assert added.folder_id == folder.id


@pytest.mark.asyncio
async def test_several_files_are_deleted_together_or_not_at_all(db, user, admin_user):
    files = KnowledgeFiles(db, user)
    a, b, theirs = await doc(db, user, "a.md"), await doc(db, user, "b.md"), await doc(db, admin_user, "c.md")
    with pytest.raises(HTTPException) as foreign:
        await files.delete_many([a.id, theirs.id])
    assert foreign.value.status_code == 404 and await db.get(Document, a.id) is not None  # nothing went
    a_id, b_id, theirs_id = a.id, b.id, theirs.id
    await routes.delete_files(routes.KnowledgeDeleteIn(file_ids=[a_id, b_id]), db, user)
    db.expire_all()
    assert await db.get(Document, a_id) is None and await db.get(Document, b_id) is None
    assert await db.get(Document, theirs_id) is not None


@pytest.mark.asyncio
async def test_a_file_can_be_viewed_by_its_owner_or_by_anyone_when_shared(db, user, admin_user, tmp_path, monkeypatch):
    from app.services import knowledge_files

    monkeypatch.setattr(knowledge_files, "KNOWLEDGE_DIR", tmp_path)
    notes = await doc(db, user, "notes.md")
    (tmp_path / notes.filename).parent.mkdir(parents=True)
    (tmp_path / notes.filename).write_text("# Title\n\nSome **notes**.")

    preview = await routes.preview_file(notes.id, db, user)
    assert (preview.filename, preview.format, preview.truncated) == ("notes.md", "markdown", False)
    assert preview.text.startswith("# Title")
    download = await routes.get_file(notes.id, db, user)
    assert str(download.path) == str(tmp_path / notes.filename)
    assert "attachment" in download.headers["content-disposition"]
    for call in (routes.preview_file, routes.get_file):
        with pytest.raises(HTTPException) as hidden:
            await call(notes.id, db, admin_user)  # not theirs
        assert hidden.value.status_code == 404
    # A shared file is in everyone's chat search, so its sources open for anyone.
    handbook = await doc(db, None, "handbook.md")
    (tmp_path / handbook.filename).parent.mkdir(parents=True)
    (tmp_path / handbook.filename).write_text("Shared.")
    assert (await routes.preview_file(handbook.id, db, user)).text == "Shared."
