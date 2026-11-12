"""Keeps a chat's earlier attachments in its history, so a follow-up question still knows about them.

A file's text goes to the model with the message it came on (chat_prompt_service turn context). What was sent, after
any cut, is saved next to the file ("<file>.sent.txt") and put back in front of that message on later turns, the same
way it was sent, so the engine's prompt cache keeps matching. A long file (over `whole_limit` tokens, when an
embedding model can search it) is not repeated: a note stands in for it, and chat_follow_up.py adds the parts that
match each question (chat_file_index.py). An image is not sent again (the vision model's reply already describes it):
later turns get a short note that it was attached.

When the chat outgrows the context window, the oldest messages leave it (chat_history_service.trim_history), and their
files with them: summaries() keeps the reply about each file, and forgotten_notice tells the user once.
"""

import base64
import logging
from collections.abc import Sequence
from pathlib import Path

from app.config import ATTACHMENTS_DIR
from app.models import Message, MessageAttachment
from app.services.chat_commands import ChatCommand
from app.services.chat_file_index import ChatFileIndex
from app.services.document_extract import extract_text
from app.services.document_retrieval import build_attachment_system_prompt
from app.services.image_relevance import ImageRelevance
from app.services.turn_context_fit import TokenEstimate

logger = logging.getLogger(__name__)

_SENT_SUFFIX = ".sent.txt"
_CUT_MARK = "fitted; the rest was left out.]"  # TurnContextFit.cut's note at the end of a cut file
_SUMMARY_CHARS = 1500  # of the reply kept for a file that left the window
_SUMMARY_FILES = 4  # the latest files that left the window keep a summary


class AttachmentMemory:
    def __init__(
        self,
        current: Message | None = None,
        folder: Path | None = None,
        whole_limit: int | None = None,
        images_inline: bool = False,
    ) -> None:
        # The message being answered: its files go in this turn's context, not in its history text.
        self._current = current
        self._folder = folder or ATTACHMENTS_DIR
        # Tokens a file may take to stay whole; None: every file stays whole (no embedding model to search with).
        self._whole_limit = whole_limit
        # The chat model sees images: earlier ones go with their message (images_of), not as a note.
        self._images_inline = images_inline
        self._texts: dict[int, str] = {}  # per message, for this turn: the window is measured more than once
        self._sent: dict[Path, str] = {}

    @staticmethod
    def sent_path(path: Path) -> Path:
        return path.with_name(path.name + _SENT_SUFFIX)

    @classmethod
    def sidecars(cls, path: Path) -> list[Path]:
        """Files kept next to an attachment, deleted with it."""
        return [cls.sent_path(path), ChatFileIndex.index_path(path), ImageRelevance.about_path(path)]

    @classmethod
    def remember(cls, path: Path, text: str) -> None:
        """Saves the text the model got for the file at `path` ("" when none of it fitted)."""
        try:
            cls.sent_path(path).write_text(text, encoding="utf-8")
        except OSError as error:
            logger.warning("Could not save the sent text of %s: %s", path.name, error)

    def path_of(self, attachment: MessageAttachment) -> Path:
        return self._folder / attachment.path

    def is_long(self, path: Path) -> bool:
        """Too long to stay whole: over the limit, or already cut (or left out) when first sent."""
        if self._whole_limit is None or not path.exists():
            return False
        text = self._sent_text(path)
        return not text or text.endswith(_CUT_MARK) or TokenEstimate.of(text) > self._whole_limit

    def long_files(self, messages: Sequence[Message]) -> list[tuple[Path, str]]:
        """(path, filename) of every earlier long text file in `messages` whose file still exists."""
        found = []
        for message in messages:
            if message is self._current or message.role != "user":
                continue
            for attachment in message.attachments or []:
                path = self.path_of(attachment)
                if attachment.type == "text" and path.exists() and self.is_long(path):
                    found.append((path, attachment.filename))
        return found

    def history_text(self, message: Message) -> str:
        """`message` as the model reads it in the history: earlier files and images first, then the words."""
        if message.role != "user":
            return message.content
        content = ChatCommand.expand(message.content)
        if message is self._current or not message.attachments:
            return content
        if id(message) not in self._texts:
            parts = [part for part in map(self._part, message.attachments) if part]
            self._texts[id(message)] = "\n\n---\n\n".join(("\n\n".join(parts), content)) if parts else content
        return self._texts[id(message)]

    @staticmethod
    def summaries(messages: Sequence[Message], start: int) -> str:
        """Files in messages[:start] (out of the window): the reply about each, so the model still knows them."""
        lines = []
        for index, message in enumerate(messages[:start]):
            names = [a.filename for a in (message.attachments or [])] if message.role == "user" else []
            if not names:
                continue
            reply = next((m for m in messages[index + 1 :] if m.role == "assistant"), None)
            about = (reply.content if reply else "").strip()
            if len(about) > _SUMMARY_CHARS:
                about = about[:_SUMMARY_CHARS].rsplit(" ", 1)[0] + " …"
            listed = ", ".join(f'"{name}"' for name in names)
            lines.append(f"- The user attached {listed}. The reply then was: {about or '(none)'}")
        if not lines:
            return ""
        return "Earlier in this chat, before the messages below:\n" + "\n".join(lines[-_SUMMARY_FILES:])

    @staticmethod
    def forgotten_notice(messages: Sequence[Message], previous_start: int, start: int) -> str | None:
        """A notice when messages[previous_start:start] (in the last reply's history, not in this one) had files."""
        names = [a.filename for m in messages[previous_start:start] for a in (m.attachments or [])]
        if not names:
            return None
        listed = ", ".join(names)
        verb, pronoun = ("is", "it") if len(names) == 1 else ("are", "them")
        return (
            f"{listed} {verb} no longer in full in the model's memory for this chat: the chat outgrew the context "
            f"window. The model keeps the reply about {pronoun} as a summary; attach {pronoun} again for details."
        )

    def images_of(self, message: Message) -> list[str]:
        """An earlier message's images as base64, for a chat model that sees them (not the one being answered: its
        image is attached by the reply itself)."""
        if message is self._current or message.role != "user":
            return []
        images = []
        for attachment in message.attachments or []:
            path = self.path_of(attachment)
            if attachment.type == "image" and path.exists():
                images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
        return images

    def _part(self, attachment: MessageAttachment) -> str:
        if attachment.type == "image" and self._images_inline:
            return ""
        if attachment.type == "image":
            return (
                f'The user attached an image named "{attachment.filename}" with this message; the reply that '
                "follows describes it."
            )
        path = self.path_of(attachment)
        if self.is_long(path):
            return (
                f'The user attached a long file named "{attachment.filename}" with this message. It is too long to '
                "repeat here; the parts that match each new question are given with that question."
            )
        text = self._sent_text(path)
        return build_attachment_system_prompt("", attachment.filename, text).strip() if text else ""

    def _sent_text(self, path: Path) -> str:
        if path not in self._sent:
            self._sent[path] = self._read_sent_text(path)
        return self._sent[path]

    def _read_sent_text(self, path: Path) -> str:
        """The saved text; for a file sent before this was kept, its text read once now."""
        sent = self.sent_path(path)
        try:
            return sent.read_text(encoding="utf-8")
        except FileNotFoundError:
            pass
        except OSError as error:
            logger.warning("Could not read the sent text of %s: %s", path.name, error)
            return ""
        try:
            text = extract_text(path.read_bytes(), path.suffix.lower())
        except Exception as error:  # a missing or unreadable file must not fail the reply
            logger.warning("Could not read attachment %s for the history: %s", path.name, error)
            return ""
        self.remember(path, text)
        return text
