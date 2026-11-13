"""Admin settings > Inference > Prompt cache (prompt_cache_setting.py, app/services/prompt_layout)."""

from typing import Literal

from pydantic import BaseModel, Field

# How a chat's notes and skills are laid out so a change to them costs the engine as little re-reading as possible:
#   "ordered": what changes least comes first (skills, then notes); a change re-reads from it to the end. Exact.
#   "append": the prompt stays as the chat started; changes are added as a short update on the message where they
#             happened, and the prompt is rebuilt once the updates grow. Exact.
#   "index": skills appear as a one-line list; a skill's full text is added on the message that needs it. Exact.
#   "blocks": as "ordered", and Matricxon keeps the unchanged parts after a change (copied, not re-read).
#             Approximate; other engines treat it as "ordered".
PromptCacheMode = Literal["ordered", "append", "index", "blocks"]


class PromptCacheSetting(BaseModel):
    mode: PromptCacheMode = "ordered"
    # "append": the prompt is rebuilt (one full re-read) after this many updates, or this much update text.
    max_updates: int = Field(5, ge=1, le=50)
    max_update_chars: int = Field(6000, ge=500, le=100_000)
    # "index": a skill is added when a question is at least this close in meaning to it (0 to 1), at most
    # `max_loaded` per message. Without an embedding model, every skill is added with the chat's first message.
    load_above: float = Field(0.30, ge=0.0, le=1.0)
    max_loaded: int = Field(2, ge=1, le=10)
    # "blocks": the shortest run of unchanged tokens worth copying.
    min_block_tokens: int = Field(32, ge=8, le=4096)

    @property
    def mid_chat_changes(self) -> "MidChatChanges":
        """What a started chat may still change: what its layout makes cheap. "index" keeps notes in the system
        prompt (after the skill list), so a note change there re-reads from it, as under "ordered"."""
        return MidChatChanges(skills=self.mode != "ordered", notes=self.mode in ("append", "blocks"))


class MidChatChanges(BaseModel):
    """GET /api/prompt-cache/mid-chat-changes: whether a started chat's skills, and its persona and rules notes,
    may change."""

    skills: bool
    notes: bool
