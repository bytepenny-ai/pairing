"""What one reply's preparation passes from stage to stage (sanitize.py): set by chat_service.build_reply_stream, then
filled by each stage in turn. Fields after `attachments` start empty; `TurnStage.provides` says which stage sets which.
"""

from dataclasses import dataclass, field, fields
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, User
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_follow_up import ChatFollowUp, FollowUpPlan
from app.services.image_fallback_stream import ImageFallback
from app.services.prompt_layout.base import PromptLayout

# Set before the first stage runs; every other field is a stage's to provide.
GIVEN = frozenset({"db", "conversation", "user", "message", "content", "attachments", "is_personal"})


@dataclass
class ChatTurn:
    db: AsyncSession
    conversation: Conversation
    user: User
    message: Message  # the user's message being answered, already saved
    content: str  # as typed, chat commands included
    attachments: list[AttachmentInfo]
    is_personal: bool
    params: dict[str, Any] = field(default_factory=dict)
    reserved_tokens: int = 0  # room kept for the reply
    past: list[Message] = field(default_factory=list)  # the chat's messages the model may see
    sees_images: bool = False  # the chat's model reads images itself
    follow_up: ChatFollowUp | None = None
    question: str = ""  # the message with chat commands removed
    has_image: bool = False
    layout: PromptLayout | None = None
    plan: FollowUpPlan | None = None
    reply_files: list[AttachmentInfo] = field(default_factory=list)
    system_prompt: str = ""
    turn_context: str = ""
    source_filenames: list[str] = field(default_factory=list)
    chat_messages: list[dict] = field(default_factory=list)
    reply_model: str | None = None  # the vision model for this reply only, else None (the chat's model)
    fallback: ImageFallback | None = None
    stopped: bool = False  # a stage ended the turn: no reply

    @classmethod
    def field_names(cls) -> frozenset[str]:
        return frozenset(f.name for f in fields(cls))
