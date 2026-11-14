"""Which files pAIring reads as text, by content (app/services/text_files.py): any text file is a document, a binary
one isn't, and the known formats still go by their type."""

import pytest

from app.services.chat_attachment_preview import AttachmentPreviewer
from app.services.document_extract import extract_text
from app.services.text_files import HEAD_BYTES, TextFiles


@pytest.mark.parametrize(
    ("head", "text"),
    [
        (b"def first(items):\n    return items[0]\n", True),  # code
        ("שלום עולם".encode(), True),  # UTF-8 Hebrew
        ("א".encode() * (HEAD_BYTES // 2) + "ב".encode()[:1], True),  # a character cut at the 8 KB edge
        ("שלום".encode("cp1255") + b" and some English text " * 10, True),  # an older 8-bit encoding
        ("hi".encode("utf-16"), True),  # UTF-16 with its mark
        (b"\x1b[32mOK\x1b[0m done\n", True),  # a coloured log
        (b"PK\x03\x04\x14\x00\x00\x00", False),  # a zip (and so a .docx renamed)
        (b"\x7fELF\x02\x01\x01\x00", False),  # a Linux program
        (bytes(range(1, 32)) * 4, False),  # mostly control characters
        (b"", False),
    ],
)
def test_text_is_told_from_binary_by_content(head, text):
    assert TextFiles.is_text(head) is text


def test_known_formats_go_by_type_and_any_other_name_by_content():
    assert TextFiles.readable("report.pdf", b"%PDF-1.7\x00\x01")  # binary, but it has its own reader
    assert TextFiles.readable("Dockerfile", b"FROM python:3.13\n")  # no extension at all
    assert not TextFiles.readable("photo.jpg.exe", b"MZ\x90\x00")


def test_a_text_file_of_any_type_decodes_and_extracts():
    assert TextFiles.decode("﻿hello".encode()) == "hello"  # a UTF-8 mark dropped
    assert TextFiles.decode("hi".encode("utf-16")) == "hi"
    assert extract_text(b"SELECT 1;\n", ".sql") == "SELECT 1;\n"


def test_a_path_is_checked_once_while_unchanged(tmp_path):
    code = tmp_path / "main.rs"
    code.write_text('fn main() { println!("hi"); }\n')
    assert TextFiles.readable_path(code)
    code.write_bytes(b"\x00\x01binary now")  # changed: checked again
    assert not TextFiles.readable_path(code)
    assert not TextFiles.readable_path(tmp_path / "missing.txt")


@pytest.mark.asyncio
async def test_the_viewer_shows_a_code_file_as_text(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text("print('hi')\n")
    preview = await AttachmentPreviewer().preview_file(script, "tool.py")
    assert (preview.format, preview.text) == ("text", "print('hi')\n")
