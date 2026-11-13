"""The "index" layout: the system prompt lists each skill in one line (name and purpose), and a skill's full text
joins the chat only when a request needs it, where it then stays. Exact: an added skill doesn't touch what the
engine cached, and a long skill nobody asks about is never read.

Who decides a request needs a skill:
  - a model that can call tools: the model itself, with the "use_skill" tool (skill_chat_tool.py). The tool's result
    isn't kept in the history, so the next message carries the skill's text from then on;
  - otherwise: the default embedding model (skill_relevance.py); without one (or when it fails), every skill not
    added yet is added at once, so none is ever lost. A short reply ("OK", "thanks") adds nothing.

The list is the chat's skills when it started, so it never changes the prompt's start. A skill added later gets a
one-line note ("new"), a removed one too ("gone"), and a changed one is read or added again in its new version.
A skill's full text never goes on a message with an image (a long text there hides the image from the model): it
waits for the next message. When a message holding an entry leaves the history window, the entry goes with it.
Notes follow the list (a note change re-reads from there).
"""

from app.schemas.prompt_cache import PromptCacheSetting
from app.services.chat_follow_up import ChatFollowUp
from app.services.prompt_layout.base import LayoutContext, PromptLayout, PromptStrategy, ToolNote
from app.services.prompt_layout.index_notes import IndexNotes
from app.services.prompt_layout.sections import PromptSection, PromptSections
from app.services.prompt_layout.skill_chat_tool import NAME, NOTICE_NAME
from app.services.prompt_layout.skill_relevance import SkillRelevance

_TYPES = ("load", "gone", "new", "changed")


class IndexLayout(PromptStrategy):
    mode = "index"

    def __init__(self, setting: PromptCacheSetting, relevance: SkillRelevance) -> None:
        super().__init__(setting)
        self._relevance = relevance

    async def layout(self, ctx: LayoutContext) -> tuple[PromptLayout, dict]:
        saved = self._saved(ctx.saved)
        listed, entries, recorded = saved if saved else (ctx.sections.of_kind("skill"), [], [])
        if not ctx.read_only:
            entries = await self._still_kept(ctx, entries)
            entries = entries + IndexNotes.gone(ctx, listed, entries)
            if ctx.tools:
                loads, recorded = IndexNotes.used(ctx, entries, recorded)
                entries = entries + loads
                entries = entries + IndexNotes.new(ctx, listed, entries) + IndexNotes.changed(ctx, entries)
            else:
                entries = entries + await self._loads(ctx, entries)
            entries = await self._still_kept(ctx, entries)
        system = "\n\n".join(p for p in (self.index_text(listed, ctx.tools), ctx.sections.notes_text()) if p)
        texts = {s.title: s.text for s in ctx.sections.of_kind("skill")} if ctx.tools else {}
        layout = PromptLayout(system, skill_texts=texts, **self.delivered(ctx, self._notes(entries)))
        if ctx.read_only:
            return layout, ctx.saved
        listed_state = [s.to_dict() for s in listed]
        return layout, {"mode": self.mode, "listed": listed_state, "entries": entries, "recorded": recorded}

    @staticmethod
    def index_text(listed: list[PromptSection], tools: bool = False) -> str:
        if not listed:
            return ""
        lines = "\n".join(f"- {s.title}: {IndexNotes.purpose(s)}" for s in listed)
        if tools:
            how = (
                "Most requests need no skill: answer them directly. Only when a request is exactly the task a skill is "
                f"for, first read its full instructions with {NAME}"
            )
            return f"Skills for this conversation. {how}:\n{lines}"
        return (
            "Skills for this conversation. A skill's full instructions are given with the message that needs "
            "it; follow them for that request and later ones it fits:\n" + lines
        )

    async def _loads(self, ctx: LayoutContext, entries: list[dict]) -> list[dict]:
        """Without tools: the skills the question is close to (or every waiting one, with nothing to judge by)."""
        loaded = {e["key"]: e["digest"] for e in entries if e["type"] == "load"}  # the newest load wins
        waiting = [s for s in ctx.sections.of_kind("skill") if loaded.get(s.key) != s.digest]
        if not waiting or ctx.has_image:
            return []
        if self._relevance.available and ChatFollowUp.is_small_talk(ctx.question):
            return []  # "OK", "thanks": nothing to look up
        scores = await self._relevance.scores(ctx.question, waiting) if self._relevance.available else None
        if scores is None:
            chosen = waiting  # nothing to judge by: every skill now, rather than one missing when it's needed
        else:
            ranked = sorted(
                (s for s in waiting if scores.get(s.key, 0.0) >= self._setting.load_above), key=lambda s: -scores[s.key]
            )
            chosen = ranked[: self._setting.max_loaded]
        return [IndexNotes.load(ctx, s) for s in chosen]

    async def _still_kept(self, ctx: LayoutContext, entries: list[dict]) -> list[dict]:
        """Entries whose message is still in the history window (else their text is gone from the prompt)."""
        if not entries:
            return entries
        kept = await ctx.kept(self._inserts(entries))
        return [e for e in entries if e["message_id"] in kept]

    @staticmethod
    def _notes(entries: list[dict]) -> dict[str, list[ToolNote]]:
        """Each entry as the app tells it at its message: a skill's text as use_skill's result, a note as an
        instruction_updates result (text before the message for a model without tools; base.delivered)."""
        parts: dict[str, list[ToolNote]] = {}
        for e in entries:
            note = ToolNote(NAME, {"name": e.get("title", "")}, e["text"]) if e["type"] == "load" else None
            parts.setdefault(e["message_id"], []).append(note or ToolNote(NOTICE_NAME, {}, e["text"]))
        return parts

    def _inserts(self, entries: list[dict]) -> dict[str, str]:
        parts: dict[str, list[str]] = {}
        for entry in entries:
            parts.setdefault(entry["message_id"], []).append(entry["text"])
        return self.joined(parts)

    def _saved(self, saved: dict) -> tuple[list[PromptSection], list[dict], list[str]] | None:
        if saved.get("mode") != self.mode:
            return None
        listed = PromptSections.from_saved(saved.get("listed"))
        entries, recorded = saved.get("entries"), saved.get("recorded", [])
        if listed is None or not isinstance(entries, list) or not isinstance(recorded, list):
            return None
        fields = ("type", "key", "message_id", "text")
        if not all(
            isinstance(e, dict)
            and all(isinstance(e.get(f), str) for f in fields)
            and e["type"] in _TYPES
            and (e["type"] in ("gone", "new") or isinstance(e.get("digest"), str))
            for e in entries
        ) or not all(isinstance(r, str) for r in recorded):
            return None
        return listed.items, entries, recorded
