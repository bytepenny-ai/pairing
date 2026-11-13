"""Builds a reply's system prompt (persona/rule notes and the chat's skills, RAG context, then ad-hoc
attachments) and the RAG source-filename list. Split from chat_service.build_reply_stream for the file-size
rule: the "what goes into the prompt" half.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, User
from app.services import chat_attachment_service
from app.services.chat_attachment_service import AttachmentInfo
from app.services.document_retrieval import build_augmented_system_prompt, retrieve_context
from app.services.inference_client import InferenceError
from app.services.live_workflow_bus import live_workflow
from app.services.prompt_layout.base import PromptLayout
from app.services.prompt_layout.sections import PromptSections
from app.services.turn_context_fit import TurnContextFit


async def build_system_prompt(
    db: AsyncSession,
    conversation: Conversation,
    user: User,
    content: str,
    params: dict,
    attachments: list[AttachmentInfo],
    history: list[dict],
    reserved_tokens: int,
    sees_images: bool = False,
    system_prompt: str | None = None,
) -> tuple[str, str, list[str], list[str]]:
    """Returns (system_prompt, turn_context, source_filenames, notices) for this turn.

    The turn context gets only the room `history` (already trimmed) and `reserved_tokens` leave in num_ctx
    (turn_context_fit.py): excerpts that don't fit are dropped, attachments cut, and `notices` tells the user.

    `system_prompt` holds only the notes and skills, identical every turn, so the engine's prompt cache keeps matching.
    `turn_context` (RAG excerpts + text attachments) changes per message, so the caller puts it before the
    newest user message (prepend_turn_context); in the system prompt it would force a full re-read each turn.

    The system prompt is the skills chosen for this chat (conversation_skills.py), then the explicit persona/rules
    pins (Notes page or chat icons), falling back to the user's default note per slot (note_service.py).
    The turn context is RAG context (every chat searches the shared knowledge base; only rag_top_k is adjustable;
    degrades silently if the base is empty or the embedding model is unreachable), then `type="text"`
    attachments (images: chat_attachment_service.apply_image_attachment).
    Channels pass user_id=None to retrieve_context so only the global knowledge base is searched.
    """
    live_workflow.enter("chat_prompt_service")
    # A chat model that sees images keeps notes and skills in image turns too: leaving them out for one turn would
    # change the prompt's start and spoil the engine's cache for every message after it.
    # `system_prompt`: the reply's prompt layout gives it (app/services/prompt_layout); else the plain order.
    if system_prompt is None:
        has_image = any(attachment.type == "image" for attachment in attachments) and not sees_images
        system_prompt = await notes_and_skills_prompt(db, conversation, user.id, has_image)

    fit = TurnContextFit(params["num_ctx"], reserved_tokens, system_prompt, history)
    turn_context = ""
    source_filenames: list[str] = []
    rag_scope_user_id = user.id if conversation.channel_id is None else None
    try:
        retrieved = await retrieve_context(db, content, rag_scope_user_id, top_k=params.get("rag_top_k", 4))
    except InferenceError:
        retrieved = []
    retrieved = [chunk for chunk in retrieved if fit.take(chunk["text"])]  # best match first
    if retrieved:
        turn_context = build_augmented_system_prompt("", retrieved).strip()
        live_workflow.pulse("rag_augment")
        # De-duplicated in first-seen (best-match-first) order: a document may give several chunks but is listed once
        # under "Sources".
        seen = set()
        for chunk in retrieved:
            if chunk["filename"] not in seen:
                seen.add(chunk["filename"])
                source_filenames.append(chunk["filename"])

    if attachments:
        turn_context = chat_attachment_service.fold_text_attachments_into_prompt(turn_context, attachments, fit).strip()

    live_workflow.exit("chat_prompt_service")
    return system_prompt, turn_context, source_filenames, fit.notices


async def notes_and_skills_prompt(db: AsyncSession, conversation: Conversation, user_id: str, has_image: bool) -> str:
    """The plain system prompt: the chat's skills, then its notes (prompt_layout/sections.py). A reply to an image may
    leave them out (Default models > Replies to an image include)."""
    return (await PromptSections.load(db, conversation, user_id, has_image)).ordered_prompt()


def prepend_turn_context(history: list[dict], turn_context: str, insert: str = "") -> None:
    """Puts `turn_context` in front of the newest user message in `history` (in place): after its prompt-layout
    `insert` if it has one (PromptLayout.add_after_insert), where the next turn shows the message's files."""
    if not turn_context:
        return
    for message in reversed(history):
        if message["role"] == "user":
            message["content"] = PromptLayout.add_after_insert(message["content"], insert, turn_context)
            return
