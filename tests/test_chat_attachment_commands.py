"""Chat attachments the model can read (chat_attachment_check.py) and the /describe and /summarize commands
(chat_commands.py): checked when a file is picked and again on send, expanded only for the model."""

import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.models import Conversation, Message
from app.routers import chat as chat_router
from app.services import chat_attachment_check
from app.services.chat_attachment_check import AttachmentCheck
from app.services.chat_commands import ChatCommand
from app.services.chat_history_service import trim_history

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name)


@pytest.fixture
def vision(monkeypatch):
    """A vision-capable engine with a default vision model; tests switch either off."""
    state = SimpleNamespace(engine=True, model="vision:latest")
    monkeypatch.setattr(
        chat_attachment_check.registry,
        "active",
        lambda: SimpleNamespace(capabilities=SimpleNamespace(vision=state.engine)),
    )

    async def default_vision(_db):
        return state.model

    monkeypatch.setattr(chat_attachment_check.model_catalog_service, "get_default_vision_model", default_vision)
    return state


class TestCommands:
    @pytest.mark.parametrize(
        ("typed", "starts"),
        [
            ("/describe", "Describe the attached image"),
            ("/Summarise", "Summarize the attached"),
            ("/summary ", "Summarize"),
        ],
    )
    def test_a_command_becomes_its_instruction(self, typed, starts):
        assert ChatCommand.expand(typed).startswith(starts)

    def test_words_after_the_command_are_kept(self):
        assert ChatCommand.expand("/summarize in Hebrew, short").endswith("\n\nin Hebrew, short")

    @pytest.mark.parametrize("typed", ["hello", "/unknown thing", "a /describe in the middle", "/describer"])
    def test_other_text_is_unchanged(self, typed):
        assert ChatCommand.expand(typed) == typed

    def test_a_command_needs_its_kind_of_file(self):
        assert ChatCommand.missing_attachment("/describe", ["text"]) == "Attach an image to use /describe."
        assert "text file" in ChatCommand.missing_attachment("/summarize", [])
        assert ChatCommand.missing_attachment("/summarize", ["image", "text"]) is None
        assert ChatCommand.missing_attachment("plain question", []) is None

    def test_titles_name_the_file(self):
        assert ChatCommand.title_text("/summarize", [("report.pdf", "text")]) == "Summary of report.pdf"
        assert ChatCommand.title_text("/describe what color", [("cat.png", "image")]) == "Describe cat.png: what color"

    def test_an_image_and_a_document_use_both_commands(self):
        expanded = ChatCommand.expand("/describe /summarize compare them")
        assert expanded.startswith("Describe the attached image")
        assert "\nSummarize the attached file(s)" in expanded and expanded.endswith("\n\ncompare them")
        files = [("report.pdf", "text"), ("cat.png", "image")]
        assert ChatCommand.title_text("/describe /summarize", files) == "Describe cat.png, Summary of report.pdf"
        assert ChatCommand.missing_attachment("/describe /summarize", ["image", "text"]) is None
        assert ChatCommand.missing_attachment("/describe /summarize", ["image"]).endswith("/summarize.")

    def test_a_repeated_command_counts_once(self):
        assert ChatCommand.expand("/describe /describe").count("Describe") == 1

    def test_the_model_reads_the_instruction_in_history(self):
        history = trim_history([Message(role="user", content="/describe")], num_ctx=4096)
        assert history[-1]["content"].startswith("Describe the attached image")


@pytest.mark.asyncio
class TestCheck:
    async def test_a_real_image_with_a_vision_model_passes(self, db, vision):
        verdict = await AttachmentCheck(db).verdict("cat.png", PNG)
        assert (verdict.ok, verdict.kind) == (True, "image")

    async def test_an_image_without_a_vision_model_is_refused(self, db, vision):
        vision.model = None
        verdict = await AttachmentCheck(db).verdict("cat.png", PNG)
        assert not verdict.ok and "vision model" in verdict.reason

    async def test_an_engine_that_cant_see_is_refused(self, db, vision):
        vision.engine = False
        assert "can't read images" in (await AttachmentCheck(db).verdict("cat.png", PNG)).reason

    async def test_a_renamed_file_is_not_a_picture(self, db, vision):
        assert "readable picture" in (await AttachmentCheck(db).verdict("cat.jpg", b"hello")).reason

    async def test_text_files(self, db, vision):
        check = AttachmentCheck(db)
        assert (await check.verdict("notes.txt", b"some notes")).ok
        assert "empty" in (await check.verdict("blank.txt", b"   ")).reason
        assert "damaged" in (await check.verdict("bad.docx", b"not a zip")).reason
        assert "can't read .exe" in (await check.verdict("tool.exe", b"MZ")).reason

    async def test_a_pdf_without_text_is_called_scanned(self, db, vision, monkeypatch):
        monkeypatch.setattr(chat_attachment_check, "extract_text", lambda _raw, _suffix: "")
        assert "scanned PDF" in (await AttachmentCheck(db).verdict("scan.pdf", b"%PDF-1.4")).reason

    async def test_the_check_route_answers_per_file(self, db, user, vision):
        out = await chat_router.check_attachments(
            files=[_upload("notes.txt", b"hi"), _upload("cat.png", b"nope")], db=db, _user=user
        )
        assert [f.ok for f in out.files] == [True, False]


@pytest.mark.asyncio
class TestSend:
    async def _chat(self, db, user) -> Conversation:
        chat = Conversation(owner_id=user.id, params={}, model="m")
        db.add(chat)
        await db.commit()
        return chat

    async def test_a_command_without_its_file_is_refused_before_streaming(self, db, user, vision):
        chat = await self._chat(db, user)
        with pytest.raises(HTTPException) as refused:
            await chat_router.stream_reply(chat.id, content="/describe", ask_ai=True, attachments=[], db=db, user=user)
        assert (refused.value.status_code, refused.value.detail) == (400, "Attach an image to use /describe.")

    async def test_an_unreadable_file_is_refused_on_send(self, db, user, vision):
        vision.model = None
        chat = await self._chat(db, user)
        with pytest.raises(HTTPException) as refused:
            await chat_router.stream_reply(
                chat.id, content="/describe", ask_ai=True, attachments=[_upload("cat.png", PNG)], db=db, user=user
            )
        assert refused.value.status_code == 400 and "vision model" in refused.value.detail
