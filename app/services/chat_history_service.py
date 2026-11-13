"""Pure history-assembly helpers for chat_service.build_reply_stream, split out for the file-size rule
(like title_service.py). No DB access: Message objects in, {"role", "content"} dicts out.
"""

import itertools
from collections.abc import Callable

from app.models import Message
from app.services.chat_commands import ChatCommand

# Rough characters per token for English. The engine offers no cheap client-side tokenizer, so this only
# sizes history locally; the engine still enforces num_ctx.
_CHARS_PER_TOKEN = 4


def only_addressed_to_ai(messages: list[Message]) -> list[Message]:
    """Channel history without messages posted without asking the AI (channel_history_setting): a user message
    stays only if an assistant reply answers it (failed counts). The current question is added by the caller.
    """
    answered = {m.reply_to_message_id for m in messages if m.role == "assistant" and m.reply_to_message_id}
    return [m for m in messages if m.role != "user" or m.id in answered]


def without_failed_replies(messages: list[Message]) -> list[Message]:
    """Drops failed or cancelled replies (status "error"): partial text plus a notice, not worth re-reading, and
    costly each turn. The question stays so the next reply can answer it.
    """
    return [m for m in messages if m.status != "error"]


# Trimming advances in steps of this fraction of the budget (see trim_history).
_TRIM_STEPS = 4

TextOf = Callable[[Message], str]
# Tool results the app puts before a message (prompt_layout.base.ToolNote: .tool, .arguments, .text).
NotesOf = Callable[[Message], list]


def _plain_text(message: Message) -> str:
    """A user's /describe or /summarize becomes its full instruction (chat_commands.py); the chat shows the command."""
    return ChatCommand.expand(message.content) if message.role == "user" else message.content


def trim_history(
    messages: list[Message],
    num_ctx: int,
    reserved_tokens: int = 512,
    text_of: TextOf = _plain_text,
    images_of: Callable[[Message], list[str]] | None = None,
    notes_of: NotesOf | None = None,
) -> list[dict]:
    """Keeps only the recent history that fits the context window, so long chats don't overflow num_ctx.
    `reserved_tokens` leaves room for the system prompt, RAG context and the reply. `text_of` gives a message as the
    model reads it (chat_attachment_memory.py adds earlier files). `images_of`, for a chat model that sees images,
    gives a message's earlier images (base64), sent with it again so the engine's prompt cache keeps matching.
    `notes_of` gives the app's tool results to put before a message (prompt layouts; counted in the window).
    """
    texts = [text_of(m) for m in messages]
    start = _window_start(_with_notes(texts, messages, notes_of), num_ctx, reserved_tokens)
    merged = _merge_consecutive_same_role(messages[start:], texts[start:])
    if images_of is not None:
        _add_images(merged, messages[start:], images_of)
    return _add_notes(merged, messages[start:], notes_of) if notes_of is not None else merged


def _with_notes(texts: list[str], messages: list[Message], notes_of: NotesOf | None) -> list[str]:
    """The texts as sized for the window: with the app's tool results before each message."""
    if notes_of is None:
        return texts
    return ["".join(n.text for n in notes_of(m)) + text for m, text in zip(messages, texts, strict=True)]


def _add_notes(merged: list[dict], messages: list[Message], notes_of: NotesOf) -> list[dict]:
    """Before each turn, the app's tool results for its messages: the calls go on the reply before it (or on a
    turn of their own), then one tool message each. Ids come from the message, so every turn renders the same."""
    out: list[dict] = []
    for turn, (_role, group) in zip(merged, itertools.groupby(messages, key=lambda m: m.role), strict=True):
        notes = [(m.id, i, n) for m in group for i, n in enumerate(notes_of(m))]
        if notes:
            calls = [
                {"id": f"app_{mid}_{i}", "function": {"name": n.tool, "arguments": n.arguments}} for mid, i, n in notes
            ]
            if out and out[-1]["role"] == "assistant" and not out[-1].get("tool_calls"):
                out[-1] = {**out[-1], "tool_calls": calls}
            else:
                out.append({"role": "assistant", "content": "", "tool_calls": calls})
            out += [
                {"role": "tool", "content": n.text, "tool_name": n.tool, "tool_call_id": f"app_{mid}_{i}"}
                for mid, i, n in notes
            ]
        out.append(turn)
    return out


def _add_images(merged: list[dict], messages: list[Message], images_of: Callable[[Message], list[str]]) -> None:
    """Puts each message's images on the turn it was merged into (same order as _merge_consecutive_same_role)."""
    turns = iter(merged)
    for _role, group in itertools.groupby(messages, key=lambda m: m.role):
        turn = next(turns)
        images = [image for message in group for image in images_of(message)]
        if images:
            turn["images"] = images


def window_start(
    messages: list[Message],
    num_ctx: int,
    reserved_tokens: int = 512,
    text_of: TextOf = _plain_text,
    notes_of: NotesOf | None = None,
) -> int:
    """Index of the first message trim_history keeps."""
    return _window_start(_with_notes([text_of(m) for m in messages], messages, notes_of), num_ctx, reserved_tokens)


def _window_start(texts: list[str], num_ctx: int, reserved_tokens: int) -> int:
    """Oldest messages go first, in steps: the history starts only where the running character count crosses a
    multiple of a quarter of the budget. Start points depend only on earlier messages, so a growing chat keeps
    the same first message for many turns. The prompt cache matches from the start, and a sliding window made
    it re-read the whole chat every turn. Failing all steps: the newest messages within the budget, at least one.
    """
    budget_chars = max(num_ctx - reserved_tokens, 256) * _CHARS_PER_TOKEN
    step = max(budget_chars // _TRIM_STEPS, 1)
    sizes = [len(t) for t in texts]
    total = sum(sizes)
    before = 0
    for index in range(len(texts)):
        starts_step = index == 0 or before // step > (before - sizes[index - 1]) // step
        if starts_step and total - before <= budget_chars:
            return index
        before += sizes[index]
    used = 0
    for index in range(len(texts) - 1, -1, -1):
        used += sizes[index]
        if used > budget_chars and index < len(texts) - 1:
            return index + 1
    return 0


def _merge_consecutive_same_role(messages: list[Message], texts: list[str]) -> list[dict]:
    """Folds runs of same-role messages into one turn. A channel can hold several "user" messages in a row
    (ask_ai=False; the AI replies only when asked), which strict chat templates (Mistral/Ministral, used by
    llama.cpp and Matricxon) reject: "conversation roles must alternate" (seen in Ollama's logs). Personal chats
    already alternate; paying the cost unconditionally is simpler. Single messages are unchanged; runs of 2+
    are joined with each line prefixed by the sender's display name (Message.sender_display_name).
    Assistant/system messages stay plain.
    """
    merged: list[dict] = []
    pairs = list(zip(messages, texts, strict=True))
    for role, group in itertools.groupby(pairs, key=lambda pair: pair[0].role):
        group = list(group)
        if len(group) == 1:
            merged.append({"role": role, "content": group[0][1]})
            continue
        lines = [f"{m.sender_display_name}: {text}" if m.sender_display_name else text for m, text in group]
        merged.append({"role": role, "content": "\n".join(lines)})
    return merged
