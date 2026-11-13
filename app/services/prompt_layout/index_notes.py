"""The entries the "index" layout adds to a message (index.py): a skill's full text ("load") and one-line notes about
a skill that was removed ("gone"), added after the chat started ("new") or changed after the model read it
("changed"). Each entry is {type, key, message_id, text}, plus `digest` for "load" and "changed"."""

from app.services.prompt_layout.base import LayoutContext
from app.services.prompt_layout.sections import PromptSection
from app.services.prompt_layout.skill_chat_tool import GUARD, NAME, SkillTool

_PURPOSE_CHARS = 160
_KEEP_RECORDED = 200  # replies whose use_skill calls were turned into entries


class IndexNotes:
    @staticmethod
    def purpose(skill: PromptSection) -> str:
        text = skill.description or next((line.strip() for line in skill.text.splitlines() if line.strip()), "")
        return text if len(text) <= _PURPOSE_CHARS else text[: _PURPOSE_CHARS - 1].rstrip() + "…"

    @staticmethod
    def load(ctx: LayoutContext, skill: PromptSection) -> dict:
        return {
            "type": "load",
            "key": skill.key,
            "digest": skill.digest,
            "message_id": ctx.message_id,
            "title": skill.title,
            "text": f'Skill "{skill.title}" (its full instructions). {GUARD}\n\n{skill.text}',
        }

    @staticmethod
    def gone(ctx: LayoutContext, listed: list[PromptSection], entries: list[dict]) -> list[dict]:
        """A note for each listed skill that is no longer the chat's, once."""
        current = ctx.sections.by_key()
        noted = {e["key"] for e in entries if e["type"] == "gone"}
        return [
            IndexNotes._note(
                ctx, "gone", s.key, f'The skill "{s.title}" is no longer available: don\'t use it any more.'
            )
            for s in listed
            if s.key not in current and s.key not in noted
        ]

    @staticmethod
    def new(ctx: LayoutContext, listed: list[PromptSection], entries: list[dict]) -> list[dict]:
        """A note for each skill added after the list was made (the model can't read it otherwise), once."""
        known = {s.key for s in listed} | {e["key"] for e in entries if e["type"] in ("new", "load")}
        return [
            IndexNotes._note(
                ctx,
                "new",
                s.key,
                f'New skill available: "{s.title}" ({IndexNotes.purpose(s)}). Read it with {NAME} only when a request '
                "is exactly that task.",
            )
            for s in ctx.sections.of_kind("skill")
            if s.key not in known
        ]

    @staticmethod
    def changed(ctx: LayoutContext, entries: list[dict]) -> list[dict]:
        """A note when a skill whose text the chat holds has changed since: read it again before following it."""
        current = ctx.sections.by_key()
        held = {e["key"]: e["digest"] for e in entries if e["type"] == "load"}  # the newest load wins
        noted = {(e["key"], e["digest"]) for e in entries if e["type"] == "changed"}
        notes = []
        for key, digest in held.items():
            skill = current.get(key)
            if skill is None or skill.digest == digest or (key, skill.digest) in noted:
                continue
            text = f'The skill "{skill.title}" was changed: if a request needs it again, read it again with {NAME}.'
            notes.append({**IndexNotes._note(ctx, "changed", key, text), "digest": skill.digest})
        return notes

    @staticmethod
    def used(ctx: LayoutContext, entries: list[dict], recorded: list[str]) -> tuple[list[dict], list[str]]:
        """The skills earlier replies read with use_skill, added in full to this message so they stay in the chat
        (the call itself isn't kept in the history). Waits while this message has an image: a long text hides it."""
        if ctx.has_image:
            return [], recorded
        skills = {s.title: s for s in ctx.sections.of_kind("skill")}
        held = {(e["key"], e["digest"]) for e in entries if e["type"] == "load"}
        loads, recorded = [], list(recorded)
        for reply_id, names in ctx.skill_uses:
            if reply_id in recorded:
                continue
            recorded.append(reply_id)
            for name in names:
                title = SkillTool.match(name, skills)
                skill = skills.get(title) if title else None
                if skill is not None and (skill.key, skill.digest) not in held:
                    held.add((skill.key, skill.digest))
                    loads.append(IndexNotes.load(ctx, skill))
        return loads, recorded[-_KEEP_RECORDED:]

    @staticmethod
    def _note(ctx: LayoutContext, kind: str, key: str, text: str) -> dict:
        return {"type": kind, "key": key, "message_id": ctx.message_id, "text": text}
