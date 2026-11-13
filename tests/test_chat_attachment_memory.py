"""chat_attachment_memory.py: a follow-up question still sees the files and images sent earlier in the chat."""

from pathlib import Path

import pytest

from app.models import Message, MessageAttachment
from app.schemas import ConversationCreate
from app.services import (
    chat_attachment_memory,
    chat_attachment_service,
    chat_service,
    conversation_service,
    model_catalog_service,
    reply_generation_service,
)
from app.services.chat_attachment_memory import AttachmentMemory
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_history_service import trim_history, window_start


def _with_file(folder: Path, name: str, kind: str, content: str = "/summarize") -> Message:
    message = Message(role="user", content=content)
    message.attachments = [MessageAttachment(path=f"c1/x_{name}", filename=name, type=kind)]
    return message


def _save(folder: Path, name: str, raw: str) -> Path:
    path = folder / "c1" / f"x_{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw)
    return path


def test_the_text_sent_with_a_file_comes_back_on_the_next_turn_as_it_was_sent(tmp_path):
    path = _save(tmp_path, "notes.txt", "full file")
    sent = chat_attachment_service.fold_text_attachments_into_prompt(
        "", [AttachmentInfo(path=path, filename="notes.txt", type="text")]
    ).strip()
    message = _with_file(tmp_path, "notes.txt", "text")
    text = AttachmentMemory(folder=tmp_path).history_text(message)
    assert text.startswith(f"{sent}\n\n---\n\nSummarize the attached file(s)")  # same as the first turn: cache match


def test_a_message_with_a_file_and_a_layout_insert_reads_the_same_on_the_next_turn(tmp_path):
    from app.services.chat_prompt_service import prepend_turn_context
    from app.services.prompt_layout.base import PromptLayout

    path = _save(tmp_path, "notes.txt", "full file")
    files = chat_attachment_service.fold_text_attachments_into_prompt(
        "", [AttachmentInfo(path=path, filename="notes.txt", type="text")]
    ).strip()
    message = _with_file(tmp_path, "notes.txt", "text", "what is in it?")
    message.id = "m1"
    inserts = {"m1": "Update to your instructions: answer in French."}
    now = [
        {"role": "user", "content": PromptLayout.wrap(AttachmentMemory(current=message).history_text, inserts)(message)}
    ]
    prepend_turn_context(now, files, inserts["m1"])  # the turn it is sent
    later = PromptLayout.wrap(AttachmentMemory(folder=tmp_path).history_text, inserts)(message)  # every turn after
    assert now[0]["content"] == later


def test_a_file_sent_before_this_was_kept_is_read_once_and_saved(tmp_path):
    path = _save(tmp_path, "old.txt", "old content")
    text = AttachmentMemory(folder=tmp_path).history_text(_with_file(tmp_path, "old.txt", "text", "what is it?"))
    assert "old content" in text and text.endswith("what is it?")
    assert AttachmentMemory.sent_path(path).read_text() == "old content"


def test_an_earlier_image_leaves_a_note_and_is_not_sent_again(tmp_path):
    text = AttachmentMemory(folder=tmp_path).history_text(_with_file(tmp_path, "cat.png", "image", "/describe"))
    assert text.startswith('The user attached an image named "cat.png"') and text.endswith("anything notable.")


def test_the_message_being_answered_gets_its_files_in_the_turn_context_not_twice(tmp_path):
    _save(tmp_path, "notes.txt", "full file")
    current = _with_file(tmp_path, "notes.txt", "text", "hi")
    assert AttachmentMemory(current=current, folder=tmp_path).history_text(current) == "hi"


def test_a_missing_file_is_left_out_without_failing(tmp_path):
    text = AttachmentMemory(folder=tmp_path).history_text(_with_file(tmp_path, "gone.txt", "text", "hi"))
    assert text == "hi"


def test_the_history_counts_and_carries_the_file_text(tmp_path):
    _save(tmp_path, "notes.txt", "file body " * 50)
    memory = AttachmentMemory(folder=tmp_path)
    messages = [
        _with_file(tmp_path, "notes.txt", "text", "/summarize"),
        Message(role="assistant", content="A summary."),
        Message(role="user", content="and the second point?"),
    ]
    history = trim_history(messages, num_ctx=4096, text_of=memory.history_text)
    assert "file body" in history[0]["content"] and len(history) == 3


def test_the_user_is_told_once_when_a_file_leaves_the_window(tmp_path):
    first = _with_file(tmp_path, "cat.png", "image", "/describe")
    messages = [first, Message(role="assistant", content="A cat.")]
    for turn in range(8):
        messages += [Message(role="user", content=f"q{turn} " + "x" * 400), Message(role="assistant", content="ok")]
    messages.append(Message(role="user", content="last"))
    memory = AttachmentMemory(folder=tmp_path)
    this = window_start(messages, 256, 0, memory.history_text)
    assert this > 0
    assert "cat.png is no longer" in AttachmentMemory.forgotten_notice(messages, 0, this)
    assert AttachmentMemory.forgotten_notice(messages, this, this) is None


@pytest.mark.asyncio
async def test_a_follow_up_question_still_sees_the_file_from_the_turn_before(db, user, tmp_path, monkeypatch):
    sent: list[list[dict]] = []

    async def fake_chat_stream(_model, messages, _params):
        sent.append(messages)
        yield "ok"

    async def installed():
        return ["fake-model"]

    monkeypatch.setattr(model_catalog_service, "installed_chat_models", installed)
    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat_service, "ATTACHMENTS_DIR", tmp_path)
    monkeypatch.setattr(chat_attachment_memory, "ATTACHMENTS_DIR", tmp_path)
    path = _save(tmp_path, "notes.txt", "the launch code is 12345")
    attachment = AttachmentInfo(path=path, filename="notes.txt", type="text")

    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    async for _event in chat_service.build_reply_stream(db, conversation, user, "/summarize", attachments=[attachment]):
        pass
    await db.refresh(conversation)
    async for _event in chat_service.build_reply_stream(db, conversation, user, "what was the code again?"):
        pass

    first_turn = sent[0][1]["content"]
    follow_up = [m["content"] for m in sent[1] if m["role"] == "user"]
    assert follow_up[0] == first_turn and "12345" in follow_up[0]  # the same text: the prompt cache still matches
    assert follow_up[-1] == "what was the code again?"
