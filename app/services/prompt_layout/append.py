"""The "append" layout: the system prompt stays as the chat started, so the engine's cache of it stays valid. When
the notes or skills change, a short update (update_note.py) is added to the message where it happened and stays
there. Exact: nothing cached is re-read.

When a message holding an update is deleted or leaves the history window, the update would be lost: one update
with every change since the prompt was made goes on the current message instead ("carried"), so only that is read.
A long update (a skill's text) waits while the message has an image: there it hides the image from the model.

The prompt is rebuilt from the current notes and skills (one full re-read) when:
  - the updates pass the admin's limit (count or length): many updates cost more to read than they save;
  - a carried update can't go on the current message (an image, or it doesn't fit the window);
  - nothing usable is saved (a new chat, another layout before, a damaged save).
"""

from app.services.prompt_layout.base import LONG_INSERT_CHARS, LayoutContext, PromptLayout, PromptStrategy, ToolNote
from app.services.prompt_layout.sections import PromptSections
from app.services.prompt_layout.skill_chat_tool import NOTICE_NAME
from app.services.prompt_layout.update_note import UpdateNote


class AppendLayout(PromptStrategy):
    mode = "append"

    async def layout(self, ctx: LayoutContext) -> tuple[PromptLayout, dict]:
        saved = self._saved(ctx.saved)
        if saved is None:
            return self._fresh(ctx)
        base, current, updates = saved
        if ctx.read_only:
            return self._layout(ctx, base, updates), ctx.saved
        if current != ctx.sections:
            text = UpdateNote.between(current, ctx.sections)
            if not self._waits(ctx, text):
                updates = [*updates, {"message_id": ctx.message_id, "text": text}] if text else updates
                current = ctx.sections
        updates = await self._carried(ctx, base, current, updates)
        if updates is None or self._too_long(updates):
            return self._fresh(ctx)
        state = {"mode": self.mode, "base": base.to_saved(), "current": current.to_saved(), "updates": updates}
        return self._layout(ctx, base, updates), state

    def _layout(self, ctx: LayoutContext, base: PromptSections, updates: list[dict]) -> PromptLayout:
        """The prompt as the chat started, and each update at its message (a tool result for a tool model)."""
        parts: dict[str, list[ToolNote]] = {}
        for update in updates:
            parts.setdefault(update["message_id"], []).append(ToolNote(NOTICE_NAME, {}, update["text"]))
        return PromptLayout(base.ordered_prompt(), **self.delivered(ctx, parts))

    def _fresh(self, ctx: LayoutContext) -> tuple[PromptLayout, dict]:
        saved = ctx.sections.to_saved()
        return self._layout(ctx, ctx.sections, []), {
            "mode": self.mode,
            "base": saved,
            "current": saved,
            "updates": [],
        }

    def _saved(self, saved: dict) -> tuple[PromptSections, PromptSections, list[dict]] | None:
        if saved.get("mode") != self.mode:
            return None
        base = PromptSections.from_saved(saved.get("base"))
        current = PromptSections.from_saved(saved.get("current"))
        updates = saved.get("updates")
        if base is None or current is None or not isinstance(updates, list):
            return None
        if not all(
            isinstance(u, dict) and isinstance(u.get("message_id"), str) and isinstance(u.get("text"), str)
            for u in updates
        ):
            return None
        return base, current, updates

    def _too_long(self, updates: list[dict]) -> bool:
        return (
            len(updates) > self._setting.max_updates
            or sum(len(u["text"]) for u in updates) > self._setting.max_update_chars
        )

    @staticmethod
    def _waits(ctx: LayoutContext, text: str) -> bool:
        return ctx.has_image and len(text) > LONG_INSERT_CHARS

    async def _carried(
        self, ctx: LayoutContext, base: PromptSections, current: PromptSections, updates: list[dict]
    ) -> list[dict] | None:
        """`updates` with every one still in the window; if one isn't, they are replaced on the current message by
        one update from the prompt's start (`base`) to now. None when that can't be done (rebuild instead)."""
        if not updates:
            return updates
        kept = await ctx.kept(self._inserts(updates))
        if all(u["message_id"] in kept for u in updates):
            return updates
        text = UpdateNote.between(base, current)
        if self._waits(ctx, text):
            return None
        stay = [u for u in updates if u["message_id"] in kept and u["message_id"] != ctx.message_id]
        carried = [*stay, {"message_id": ctx.message_id, "text": text}] if text else stay
        kept = await ctx.kept(self._inserts(carried))
        return carried if all(u["message_id"] in kept for u in carried) else None

    def _inserts(self, updates: list[dict]) -> dict[str, str]:
        parts: dict[str, list[str]] = {}
        for update in updates:
            parts.setdefault(update["message_id"], []).append(update["text"])
        return self.joined(parts)
