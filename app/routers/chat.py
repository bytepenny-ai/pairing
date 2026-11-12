"""The core chat endpoint: takes a user message, streams the reply over SSE, persists both sides.
Logic: app/services/chat_service.py; this file wraps its events in SSE.

SSE over WebSockets: simpler for one-way streams, survives proxies, and chat.js needs only
`fetch` + `ReadableStream`.
"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ATTACHMENTS_DIR
from app.database import get_db
from app.models import User
from app.schemas.chat import AttachmentCheckOut, AttachmentPreviewOut, ChatCommandListOut, ChatCommandOut
from app.services import chat_attachment_service, conversation_service, reply_broadcast_service
from app.services.auth_service import get_current_user
from app.services.chat_attachment_check import AttachmentCheck
from app.services.chat_attachment_preview import AttachmentPreviewer, get_accessible_attachment
from app.services.chat_commands import ChatCommand
from app.services.chat_service import build_reply_stream
from app.services.model_catalog_service import HiddenModelTags
from app.services.usage_limits import UsageLimitService

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/commands", response_model=ChatCommandListOut)
async def list_chat_commands(_user: User = Depends(get_current_user)) -> ChatCommandListOut:
    """The commands a message can start with (chat_command_catalog.py), for the "/" menu and attach prefill."""
    return ChatCommandListOut(
        commands=[
            ChatCommandOut(
                name=c.name,
                description=c.description,
                needs=c.needs,
                prefill_for=c.prefill_for,
                hint=c.hint,
                aliases=list(c.aliases),
            )
            for c in ChatCommand.CATALOG.all()
        ]
    )


@router.post("/attachments/check", response_model=AttachmentCheckOut)
async def check_attachments(
    files: list[UploadFile] = File(...),
    conversation_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttachmentCheckOut:
    """Whether a model can read each picked file, before the message is sent (the chat composer calls it). With the
    chat's id, a long file also gets how long the reply may take to start."""
    conversation = (
        await conversation_service.get_accessible_conversation_or_404(db, conversation_id, user)
        if conversation_id
        else None
    )
    return AttachmentCheckOut(files=await AttachmentCheck(db, conversation).check_uploads(files))


@router.post("/{conversation_id}/stream")
async def stream_reply(
    conversation_id: str,
    content: str = Form(..., min_length=1),
    ask_ai: bool = Form(True),
    attachments: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = await conversation_service.get_accessible_conversation_or_404(db, conversation_id, user)
    if ask_ai and await HiddenModelTags(db).blocks(user, conversation.model):
        raise HTTPException(status_code=409, detail="This model is disabled by an admin. Pick another model.")

    if ask_ai:
        await UsageLimitService(db).check(user)  # 429 over the daily limits

    # Raise before StreamingResponse is built: Starlette locks in 200 once it starts pulling the body, so a
    # 409 from inside build_reply_stream would be too late. Best-effort, not race-free
    # (conversation_service.has_active_reply).
    if ask_ai and conversation.channel_id is not None and await conversation_service.has_active_reply(db, conversation):
        raise HTTPException(
            status_code=409,
            detail=(
                "The AI is still replying to another message in this channel — "
                "wait for it to finish, or send this as a normal message instead."
            ),
        )

    # Validated and written before streaming starts, so a bad batch gives a clean 400.
    attachments = [a for a in attachments if a.filename]
    if ask_ai or conversation.channel_id is None:
        # A file no model can read, or a /describe or /summarize without its file (chat_commands.py).
        await AttachmentCheck(db).require_readable(content, attachments)
    attachment_infos = (
        await chat_attachment_service.save_attachments(attachments, conversation_id) if attachments else []
    )

    async def event_stream():
        # SSE format "data: <payload>\n\n"; JSON payloads tell text chunks from the final "done".
        async for event in build_reply_stream(
            db, conversation, user, content, ask_ai=ask_ai, attachments=attachment_infos
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Stops nginx-style proxies buffering chunks.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """The only way attachments are served (not under /static), so the same access check applies."""
    attachment = await get_accessible_attachment(db, attachment_id, user)
    serving = chat_attachment_service.AttachmentServing.for_file(attachment.type, attachment.filename)
    return FileResponse(
        ATTACHMENTS_DIR / attachment.path,
        filename=attachment.filename,
        media_type=serving.media_type,
        content_disposition_type=serving.disposition,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/attachments/{attachment_id}/preview", response_model=AttachmentPreviewOut)
async def preview_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttachmentPreviewOut:
    """A document attachment as text, for the chat's file viewer."""
    attachment = await get_accessible_attachment(db, attachment_id, user)
    return await AttachmentPreviewer().preview(attachment)


@router.get("/{conversation_id}/subscribe")
async def subscribe_to_reply(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read-only SSE stream to watch an in-flight or just-finished reply without sending it (chat.js): a channel
    member's tab in "real" delivery mode (chat_settings_service.get_channel_delivery_mode), or an owner
    reconnecting after a dropped connection. Taps reply_broadcast_service's hub; independent of whether
    generation is still running. Gated by the access check only; "cheap" vs "real" delivery is a frontend choice.
    """
    # Only the access check matters; the conversation itself is not needed.
    await conversation_service.get_accessible_conversation_or_404(db, conversation_id, user)

    async def event_stream():
        state, queue = reply_broadcast_service.subscribe(conversation_id)
        try:
            if state is not None:
                # Shows the reply's partial content at once for someone joining mid-generation.
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "sync": True,
                            "message_id": state.message_id,
                            "content": state.content,
                            "status": state.status,
                            "sources": state.sources,
                            "tool_events": state.tool_events,
                            "reasoning": state.reasoning,
                            "read_progress": state.read_progress,
                        }
                    )
                    + "\n\n"
                )
                if state.status != "streaming":
                    return
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("done") or event.get("error") or event.get("deleted"):
                    return
        finally:
            reply_broadcast_service.unsubscribe(conversation_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
