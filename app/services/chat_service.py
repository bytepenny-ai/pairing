"""Core chat logic: saves the user's message, prepares the reply through the chat_turn stages (history, notes and
skills, RAG, which model: chat_turn/pipeline.py), calls the engine and persists both sides. routers/chat.py only
wraps build_reply_stream's events into SSE. Titles live in title_service.py, history trimming in
chat_history_service.py.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ATTACHMENTS_DIR
from app.models import Conversation, Message, MessageAttachment, User
from app.services import (
    chat_settings_service,
    reply_generation_service,
    title_service,
)
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_commands import ChatCommand
from app.services.chat_model_warmup import ChatModelWarmUp
from app.services.chat_turn.pipeline import ChatPipelines
from app.services.chat_turn.turn import ChatTurn
from app.services.live_workflow_bus import live_workflow


async def build_reply_stream(
    db: AsyncSession,
    conversation: Conversation,
    user: User,
    content: str,
    *,
    ask_ai: bool = True,
    attachments: list[AttachmentInfo] | None = None,
):
    """Async generator of events for routers/chat.py to SSE-encode:
      {"user_message_id": str}                      first event, always
      {"chunk": str}                                while streaming
      {"error": str}                                the engine failed mid-stream
      {"done": True, "title": str, "sources": [...]} once persisted
    ("title" only for personal chats. With `ask_ai` False, "done" follows "user_message_id" directly.)

    "user_message_id" lets the sender's tab tag its optimistic bubble, so a later channel poll/live-watch
    (reply_generation_service.stream_reply's cancel_on_disconnect, chat.js ownSendInFlight) doesn't duplicate it.

    `ask_ai=False` (chat.js, channels only; personal chats always ask) saves the message but generates no
    reply: no RAG/history, no stream_reply, no assistant Message. It still counts as history for later asks
    (chat_history_service.trim_history reads every message).

    The user's message is saved first, so it survives a failed reply. Title depends on the admin mode
    (chat_settings_service.get_title_mode): "simple" (title_service.maybe_set_title) sets it with the user's
    message, needing no reply; "smart" (title_service.maybe_generate_title_with_model) asks the model after
    "done" is yielded, so it never delays the reply. Both skipped for channels (title is the channel name,
    conversation_service.update_conversation refuses edits).

    The reply runs in reply_generation_service as a detached background task. On disconnect
    (stream_reply's cancel_on_disconnect): channels always finish (others may watch); personal chats are
    cancelled. Either way a clean status="error" record keeps what was generated. This function adds the
    title handling and the title in personal "done" events (channels have none).
    """
    attachments = attachments or []
    is_personal = conversation.channel_id is None
    title_mode = await chat_settings_service.get_title_mode(db) if is_personal else None
    # Personal chats always ask the AI, whatever the caller passes (no other human to message). Enforced here
    # as well as in the frontend, in case a client sends ask_ai=False.
    ask_ai = ask_ai or is_personal

    user_message = Message(conversation_id=conversation.id, role="user", content=content, sender_id=user.id)
    # Appended through the relationship: user_message.id isn't assigned until flush, and SQLAlchemy wires the FK.
    user_message.attachments = [
        MessageAttachment(
            # Stored relative to ATTACHMENTS_DIR so moving that folder doesn't strand urls.
            path=str(attachment.path.relative_to(ATTACHMENTS_DIR)),
            filename=attachment.filename,
            type=attachment.type,
        )
        for attachment in attachments
    ]
    db.add(user_message)

    if title_mode == "simple":
        title_service.maybe_set_title(
            conversation, ChatCommand.title_text(content, [(a.filename, a.type) for a in attachments])
        )

    await db.commit()

    yield {"user_message_id": user_message.id}

    # "Simple" mode already knows the title, so the sidebar needn't wait for the full reply. ("Smart" resends
    # the unchanged "New chat" placeholder: harmless.)
    if is_personal:
        yield {"title": conversation.title}

    if not ask_ai:
        done_event = {"done": True, "sources": []}
        if is_personal:
            done_event["title"] = conversation.title
        yield done_event
        return

    # Stats live workflow (Matricxon only): this reply's stages from here on.
    live_workflow.begin(conversation.model)
    live_workflow.pulse("chat_js_send")
    live_workflow.enter("chat_js_stream", "chat_router_stream", "chat_service_build")
    # Everything before the model: history, notes and skills, earlier files, knowledge, which model (chat_turn/).
    turn = ChatTurn(db, conversation, user, user_message, content, attachments, is_personal)
    try:
        async for notice in ChatPipelines.for_chat(conversation).run(turn):
            yield notice
    finally:
        live_workflow.exit("chat_service_build")
    if turn.stopped:
        return
    if turn.knowledge_sources:  # excerpts found: chat_vector_space.js shows until the reply starts, with the best score
        scores = [source["score"] for source in turn.knowledge_sources if "score" in source]
        yield {"retrieval": len(turn.knowledge_sources), "retrieval_best": max(scores) if scores else None}
    follow_up, params, reply_model, fallback = turn.follow_up, turn.params, turn.reply_model, turn.fallback
    # Channels always finish generating (other members may rely on it); a personal chat has one viewer, so
    # leaving stops generation (cancel_on_disconnect=True). Both leave a clean status="error" record
    # (reply_generation_service.stream_reply).
    async for event in reply_generation_service.stream_reply(
        db,
        conversation,
        turn.chat_messages,
        turn.knowledge_sources,
        reply_to_message_id=user_message.id,
        cancel_on_disconnect=is_personal,
        model=reply_model,
        has_image=reply_model is not None,
        params=params,
        fallback=fallback,
    ):
        if event.get("done"):
            # Detached, like the smart title below: long files become searchable for the next questions.
            if follow_up is not None:
                follow_up.schedule_indexing(attachments)
            # The vision model answered: the chat model reads that reply now, not on the next message.
            vision_model = reply_model or (
                fallback.model if fallback and fallback.model == fallback.vision_model else None
            )
            if vision_model and vision_model != conversation.model:
                ChatModelWarmUp.schedule(conversation.id, user.id, conversation.model, params)
        if is_personal and event.get("done"):
            # "Simple" mode: the title was set before streaming, so it is final. "Smart": still the old value
            # (usually "New chat"); chat.js polls for the scheduled result. reply_generation_service knows nothing of
            # titles (channels have none), so it is layered on here.
            event = {**event, "title": conversation.title}
        yield event

        if is_personal and event.get("done") and title_mode == "smart":
            # Scheduled as a detached task (title_service.schedule_smart_title_generation), not awaited: chat.js stops
            # reading after "done" and ASGI then cancels this generator, so an await would silently drop the title.
            title_service.schedule_smart_title_generation(
                conversation.id, ChatCommand.title_text(content, [(a.filename, a.type) for a in attachments])
            )
