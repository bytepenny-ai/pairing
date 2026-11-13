"""What every prompt layout shares: its result (`PromptLayout`), what it is given (`LayoutContext`) and its base class
(`PromptStrategy`).

A layout returns the system prompt plus what the app tells the model at one message (an update to the notes, a
skill's full instructions). It stays at that message on every later turn, so the prompt the engine cached keeps
matching; it leaves when its message leaves the history window, and the layout then adjusts. How it is told:
  - a model that can call tools: as tool results right before the message (`notes`, ToolNote). Never inside the
    user's own words: a model reads everything in a user turn as the user speaking, so a notice there ("New skill:
    Create user story") made it act on the notice when the user only wrote "OK";
  - other models: as text before the message's own text (`inserts`), worded so it asks for nothing.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.models import Message
from app.schemas.prompt_cache import PromptCacheSetting
from app.services.prompt_layout.sections import PromptSections
from app.services.prompt_layout.skill_chat_tool import NOTICE_PARAM_KEY, PARAM_KEY as SKILL_PARAM_KEY

TextOf = Callable[[Message], str]
# Which messages stay in the history window when these inserts are added (longer text pushes old ones out).
KeptIds = Callable[[dict[str, str]], Awaitable[set[str]]]
INSERT_SEPARATOR = "\n\n---\n\n"
# Longer inserts never go on a message with an image: on Gemma 4 a skill's text (3300 characters) there made the
# model say it had no image, while a 150-character update was fine. They wait for the next message.
LONG_INSERT_CHARS = 600


@dataclass(frozen=True)
class ToolNote:
    """App text a tool model gets as a tool's result before a message (chat_history_service adds the call)."""

    tool: str
    arguments: dict[str, Any]
    text: str


@dataclass
class PromptLayout:
    system_prompt: str
    inserts: dict[str, str] = field(default_factory=dict)  # message id -> text put before that message
    engine_options: dict[str, Any] = field(default_factory=dict)  # added to the reply's params
    # The skills the "use_skill" tool serves this reply ({title: text}; skill_chat_tool.py); empty: no such tool.
    skill_texts: dict[str, str] = field(default_factory=dict)
    notes: dict[str, list[ToolNote]] = field(default_factory=dict)  # message id -> tool results before it
    notice_tool: bool = False  # offers "instruction_updates", the tool `notes` come from (skill_chat_tool.py)

    def notes_of(self, message: Message) -> list[ToolNote]:
        return self.notes.get(message.id, [])

    @staticmethod
    def wrap(text_of: TextOf, inserts: dict[str, str]) -> TextOf:
        if not inserts:
            return text_of

        def with_insert(message: Message) -> str:
            text = text_of(message)
            insert = inserts.get(message.id)
            return f"{insert}{INSERT_SEPARATOR}{text}" if insert else text

        return with_insert

    def reply_params(self) -> dict[str, Any]:
        """What this layout adds to the reply's (and the warm-up's) params."""
        params = {**self.engine_options, **({SKILL_PARAM_KEY: self.skill_texts} if self.skill_texts else {})}
        return {**params, NOTICE_PARAM_KEY: True} if self.notice_tool else params

    @staticmethod
    def add_after_insert(content: str, insert: str, text: str) -> str:
        """`content` (a message as `wrap` made it) with `text` right after its insert, or in front without one.
        For text that comes with this turn only (its files, excerpts): the next turn puts the message's files
        after the insert too, so the prompt matches up to there, and a long insert stays cached when the
        excerpts go."""
        head = f"{insert}{INSERT_SEPARATOR}" if insert and content.startswith(f"{insert}{INSERT_SEPARATOR}") else ""
        return f"{head}{text}{INSERT_SEPARATOR}{content[len(head) :]}"

    def text_of(self, text_of: TextOf) -> TextOf:
        """`text_of` with this layout's inserts in front of their messages."""
        return self.wrap(text_of, self.inserts)


@dataclass
class LayoutContext:
    sections: PromptSections  # the chat's notes and skills now
    saved: dict  # what this layout saved for the chat last time (a copy; {} for none)
    question: str
    # The message being answered, or None to only render what is saved (the warm-up must not change anything).
    message_id: str | None
    kept: KeptIds
    has_image: bool = False  # the message being answered has an image: no long text goes on it (it hides the image)
    tools: bool = False  # the chat's model can call tools ("index" then offers use_skill)
    skill_uses: list[tuple[str, list[str]]] = field(default_factory=list)  # (reply id, skills it read), skill_chat_tool

    @property
    def read_only(self) -> bool:
        return self.message_id is None


class PromptStrategy(ABC):
    mode: ClassVar[str]

    def __init__(self, setting: PromptCacheSetting) -> None:
        self._setting = setting

    @abstractmethod
    async def layout(self, ctx: LayoutContext) -> tuple[PromptLayout, dict]:
        """(layout, state to save for the chat). The state is saved only when it differs from `ctx.saved`."""

    @staticmethod
    def joined(parts: dict[str, list[str]]) -> dict[str, str]:
        """Inserts from several texts per message, in order."""
        return {message_id: "\n\n".join(texts) for message_id, texts in parts.items() if texts}

    @staticmethod
    def delivered(ctx: LayoutContext, parts: dict[str, list[ToolNote]]) -> dict:
        """`PromptLayout` fields for what is told at each message: tool results for a tool model, else text."""
        if ctx.tools:
            return {"notes": {m: notes for m, notes in parts.items() if notes}, "notice_tool": True}
        return {"inserts": PromptStrategy.joined({m: [n.text for n in notes] for m, notes in parts.items()})}
