"""Request/response shapes for app/routers/chat.py and the message list in app/routers/conversations.py."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # The only one the frontend fetches (GET /api/chat/attachments/{id}).
    url: str
    filename: str
    # "image"/"text": how chat.js renders it.
    type: str


class AttachmentPreviewOut(BaseModel):
    """A document attachment as text, for the chat's file viewer (GET /api/chat/attachments/{id}/preview)."""

    filename: str
    format: Literal["markdown", "text"]
    text: str
    truncated: bool


class KnowledgeSourceOut(BaseModel):
    """A Knowledge base document a reply drew on; `id` opens it (GET /api/knowledge/files/{id})."""

    name: str
    # None for replies saved before sources had ids (a plain file name).
    id: str | None = None
    # Its cosine similarity to the question in the search; None for replies saved before scores were kept.
    score: float | None = None


class ReplyStatsOut(BaseModel):
    first_token_ms: int
    total_ms: int
    output_tokens: int | None = None
    prompt_tokens: int | None = None
    tokens_per_second: float | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    sources: list[KnowledgeSourceOut] | None = None
    # MCP tool calls the reply made, in order (Message.tool_events); null if none.
    tool_events: list[dict] | None = None
    # Only for "user" messages sent with files (chat_attachment_service, Message.attachments).
    attachments: list[AttachmentOut] = []
    # "streaming"/"complete"/"error"/"deleted" (Message.status). "deleted" appears only via GET /messages/latest
    # (conversation_service.get_messages_since); GET /messages filters it (visible_messages). Open polls need
    # it to remove a rendered bubble.
    status: str = "complete"
    # The real failure reason of a status="error" message (Message.error_message, set by
    # reply_model_unload_service.mark_error); null otherwise and for older errors (no backfill). chat.js shows
    # it instead of its generic notice.
    error_message: str | None = None
    # Sender label (username plus first/last name; Message.sender_display_name) for every "user" message, but
    # the frontend shows it only in channels (chat.js selectConversation). Null for assistant/system.
    sender_display_name: str | None = None
    # The sender's avatar (Message.sender_avatar_url); if null, chat.js renders sender_initials as a letter
    # circle (renderAvatar). Both null for assistant/system.
    sender_avatar_url: str | None = None
    sender_initials: str | None = None
    # "user" or "assistant" if shared into a channel from a private chat (Message.shared_from); null normally.
    # chat.js shows a "Shared from a private chat" remark.
    shared_from: str | None = None
    # The id behind sender_display_name/sender_avatar_url; chat.js's avatar-click modal fetches GET
    # /api/account/{id} (routers/account.py get_public_profile).
    sender_id: str | None = None
    created_at: datetime
    # When a reply ended (Message.completed_at); chat.js shows it instead of created_at.
    completed_at: datetime | None = None
    # A finished reply's speed (Message.stats); chat_reply_stats.js shows it beside the time.
    stats: ReplyStatsOut | None = None

    @field_validator("sources", mode="before")
    @classmethod
    def _named_sources(cls, value: list | None) -> list | None:
        """Older replies saved sources as plain file names."""
        return [{"name": item} if isinstance(item, str) else item for item in value] if value else value


class MessagesLatestResponse(BaseModel):
    """GET /api/conversations/{id}/messages/latest, the "cheap" channel delivery poll
    (chat_settings_service.get_channel_delivery_mode, conversation_service.get_messages_since): only
    messages new or changed since `since`.
    """

    messages: list[MessageOut]
    # Sent back as the next `since`; the server's clock avoids client skew gaps or duplicates.
    server_time: datetime
    # The reply still waiting for its first words, sent on every poll so its label (reasoning, compacting the cache,
    # read progress) stays right; null when there is none (reply_broadcast_service.waiting_reply).
    live: "WaitingReplyOut | None" = None


class WaitingReplyOut(BaseModel):
    message_id: str
    reasoning: list[str] = []
    read_progress: float | None = None
    compacting: bool = False


class DeleteMessageResponse(BaseModel):
    """DELETE /api/conversations/{id}/messages/{message_id}: every soft-deleted id
    (conversation_service.delete_message).
    Deleting a "user" message takes its streaming reply too; chat.js needs both ids to remove both bubbles at once.
    """

    deleted_message_ids: list[str]


class ShareMessageRequest(BaseModel):
    """Body of POST /api/conversations/{id}/messages/{message_id}/share."""

    channel_id: str


class AttachmentVerdictOut(BaseModel):
    """One file's answer from POST /api/chat/attachments/check (chat_attachment_check.py)."""

    filename: str
    kind: str | None  # "image" or "text"; None for a type chats don't take
    ok: bool
    reason: str | None = None  # why a model can't read it, in plain words
    warning: str | None = None  # readable, but long: how long the reply may take to start (read_speed.py)


class AttachmentCheckOut(BaseModel):
    files: list[AttachmentVerdictOut]


class ChatCommandOut(BaseModel):
    """One chat command, for the page's "/" menu and attach-a-file prefill (chat_command_catalog.py)."""

    name: str
    description: str
    needs: str | None = None  # "image" or "text": the attachment kind it works on
    prefill_for: str | None = None  # attaching this kind puts this command in the box
    hint: str = ""
    aliases: list[str] = []


class ChatCommandListOut(BaseModel):
    commands: list[ChatCommandOut]


MessagesLatestResponse.model_rebuild()
