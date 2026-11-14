"""Which files pAIring reads as text, by their content rather than their name: any text file (code in any language,
config, logs, a "Dockerfile" with no extension) is accepted, a binary one (a program, a zip, a database) isn't. The
formats with a reader of their own (KNOWN_EXTENSIONS: PDF, Word, ODT, RTF, HTML, CSV...) still go by their type.
Used by chat attachments (chat_attachment_check.py, chat_attachment_service.py), the knowledge base (document_upload.py,
document_sync.py, knowledge_watcher.py) and the file viewer (chat_attachment_preview.py). The chat page checks the same
way when a file is picked (chat_attachment_commands.js); the server's check is the one that counts.
"""

from functools import lru_cache
from pathlib import Path

# Read by type, each by its reader (document_extract.extract_text); every other file only if its content is text.
KNOWN_EXTENSIONS = frozenset({".txt", ".md", ".pdf", ".docx", ".rtf", ".html", ".htm", ".csv", ".json", ".odt"})
HEAD_BYTES = 8192  # how much of a file's start is looked at
_CONTROL_SHARE = 0.02  # text: at most this share of control characters
_ALLOWED_CONTROLS = {9, 10, 12, 13, 27}  # tab, newline, form feed, return, escape (coloured logs)


class TextFiles:
    @staticmethod
    def is_text(head: bytes) -> bool:
        """Whether a file starting with `head` is text: UTF-16 with its mark, or no zero byte and nearly no control
        characters, in any 8-bit encoding (UTF-8 or an older one). A binary file fails at once: zero bytes and control
        codes run all through it."""
        if head.startswith((b"\xff\xfe", b"\xfe\xff")):
            return True
        if not head or b"\x00" in head:
            return False
        controls = sum(1 for byte in head if byte < 32 and byte not in _ALLOWED_CONTROLS)
        return controls <= len(head) * _CONTROL_SHARE

    @classmethod
    def readable(cls, filename: str, head: bytes) -> bool:
        """A format with its own reader, or text by its content."""
        return Path(filename).suffix.lower() in KNOWN_EXTENSIONS or cls.is_text(head)

    @classmethod
    def readable_path(cls, path: Path) -> bool:
        """`readable` for a file on disk, remembered while it is unchanged (the knowledge folder is scanned often)."""
        try:
            stat = path.stat()
        except OSError:
            return False
        return cls._readable_cached(str(path), stat.st_mtime_ns, stat.st_size)

    @staticmethod
    @lru_cache(maxsize=4096)
    def _readable_cached(path: str, _mtime_ns: int, _size: int) -> bool:
        try:
            with open(path, "rb") as file:
                head = file.read(HEAD_BYTES)
        except OSError:
            return False
        return TextFiles.readable(path, head)

    @staticmethod
    def decode(raw: bytes) -> str:
        """A text file's characters: UTF-16 by its mark, else UTF-8 (a leading mark dropped), else each byte as itself
        (an older 8-bit encoding keeps its Latin letters; others may show as replacement characters)."""
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            return raw.decode("utf-16", errors="replace")
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")
