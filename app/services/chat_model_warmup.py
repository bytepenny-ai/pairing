"""After a reply from the vision model, the chat's own model has never read the chat: the next text message would
re-read all of it, the image's long description too (80 s for "OK" on a CPU). So pAIring reads it to the chat model
in the background right away, with a one-token answer that is thrown away. The engine keeps what it read in its prompt
cache (tagged with the chat), and the next message reuses it; the model's weights are back in memory by then too.
"""

import asyncio
import logging

from app.database import AsyncSessionLocal
from app.models import Conversation
from app.services import channel_history_setting, chat_history_service, conversation_service, tool_loop_service
from app.services.chat_attachment_memory import AttachmentMemory
from app.services.inference_client import InferenceError, chat_stream
from app.services.prompt_layout.layouts import PromptLayouts

logger = logging.getLogger(__name__)

# What the warm-up's question says; only the turn before it needs to match the next message.
_PLACEHOLDER = "OK"


class ChatModelWarmUp:
    _running: set[asyncio.Task] = set()  # strong references for detached tasks (as title_service)

    @classmethod
    def schedule(cls, conversation_id: str, user_id: str, model: str, params: dict) -> None:
        task = asyncio.create_task(cls._warm(conversation_id, user_id, model, params))
        cls._running.add(task)
        task.add_done_callback(cls._running.discard)

    @classmethod
    async def _warm(cls, conversation_id: str, user_id: str, model: str, params: dict) -> None:
        try:
            async with AsyncSessionLocal() as db:
                conversation = await db.get(Conversation, conversation_id)
                if conversation is None:
                    return
                past = conversation_service.visible_messages(conversation)
                if conversation.channel_id and not await channel_history_setting.get_include_plain_messages(db):
                    past = chat_history_service.only_addressed_to_ai(past)
                past = chat_history_service.without_failed_replies(past)
                if not past or past[-1].role != "assistant":
                    return
                # The chat's prompt layout as saved (Prompt cache setting): the next message's prompt starts the same.
                layout = await PromptLayouts(db).current(conversation, user_id)
                warm_params = {**params, **layout.reply_params(), "num_predict": 1, "conversation_id": conversation_id}
                # The reply's tools too: they start the prompt, so without them the warm cache wouldn't match it.
                tools = await tool_loop_service.offered_tools(db, model, warm_params)
                if tools:
                    warm_params["tools"] = [t.definition() for t in tools]
            reserved = max(512, params.get("num_predict", 0))
            history = chat_history_service.trim_history(
                past,
                params["num_ctx"],
                reserved,
                layout.text_of(AttachmentMemory().history_text),
                None,
                layout.notes_of,
            )
            messages = [
                {"role": "system", "content": layout.system_prompt},
                *history,
                {"role": "user", "content": _PLACEHOLDER},
            ]
            async for _chunk in chat_stream(model, messages, warm_params):
                pass
            logger.info("Chat %s: the chat model read the image reply ahead of the next message", conversation_id[:8])
        except InferenceError as error:
            logger.warning("Could not warm the chat model for chat %s: %s", conversation_id[:8], error)
        except Exception:  # a detached task: log, never fail anything
            logger.exception("Warming the chat model failed for chat %s", conversation_id[:8])
