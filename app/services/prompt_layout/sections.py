"""A chat's notes and skills as separate sections: each persona note, each rule and each skill, with a stable key
("persona:<note id>", "rules:<note id>", "skill:<skill id>"), so a layout can tell exactly what changed.

`ordered_prompt` is the system prompt with what changes least first: skills (fixed once a chat starts; only an edit
or an admin changes them) before notes (pinned and edited at any time). Its text per part is the one
note_service.build_pinned_system_prompt and conversation_skills.build_skills_prompt always gave.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Note, Skill
from app.services import conversation_skills
from app.services.note_service import resolve_conversation_notes
from app.services.vision_reply_setting import VisionReplyContextSetting

KINDS = ("persona", "rules", "skill")


@dataclass(frozen=True)
class PromptSection:
    key: str
    kind: str  # one of KINDS
    title: str  # a skill's name; "Persona" or "Rule" for a note
    text: str
    description: str = ""  # a skill's one-line description (the "index" layout lists it)

    @property
    def digest(self) -> str:
        return hashlib.sha256(f"{self.kind}\0{self.title}\0{self.text}".encode()).hexdigest()[:16]

    @classmethod
    def of_note(cls, note: Note, kind: str) -> "PromptSection":
        return cls(f"{kind}:{note.id}", kind, "Persona" if kind == "persona" else "Rule", note.content)

    @classmethod
    def of_skill(cls, skill: Skill) -> "PromptSection":
        return cls(f"skill:{skill.id}", "skill", skill.name, skill.content.strip(), (skill.description or "").strip())

    @classmethod
    def from_dict(cls, data: dict) -> "PromptSection | None":
        """None for a damaged saved entry (the layout then starts again, never a failed reply)."""
        try:
            section = cls(
                str(data["key"]),
                str(data["kind"]),
                str(data["title"]),
                str(data["text"]),
                str(data.get("description", "")),
            )
        except (KeyError, TypeError):
            return None
        return section if section.kind in KINDS else None

    def to_dict(self) -> dict:
        return asdict(self)


class PromptSections:
    def __init__(self, items: Iterable[PromptSection]) -> None:
        self.items = [item for item in items if item.kind in KINDS]

    @classmethod
    async def load(
        cls, db: AsyncSession, conversation: Conversation, user_id: str, has_image: bool = False
    ) -> "PromptSections":
        """The chat's sections now. A reply to an image may leave notes or skills out (Default models > Replies to
        an image include)."""
        with_notes, with_skills = await VisionReplyContextSetting(db).includes(has_image)
        notes = await resolve_conversation_notes(db, conversation, user_id) if with_notes else {}
        skills = await conversation_skills.active_skills(db, conversation) if with_skills else []
        return cls.of(notes, skills)

    @classmethod
    def of(cls, notes_by_type: dict[str, list[Note]], skills: list[Skill]) -> "PromptSections":
        items = [PromptSection.of_note(n, "persona") for n in notes_by_type.get("persona", [])]
        items += [PromptSection.of_note(n, "rules") for n in notes_by_type.get("rules", [])]
        return cls(items + [PromptSection.of_skill(s) for s in skills])

    @classmethod
    def from_saved(cls, saved: object) -> "PromptSections | None":
        if not isinstance(saved, list):
            return None
        items = [PromptSection.from_dict(entry) if isinstance(entry, dict) else None for entry in saved]
        return None if any(item is None for item in items) else cls(items)

    def to_saved(self) -> list[dict]:
        return [item.to_dict() for item in self.items]

    def of_kind(self, kind: str) -> list[PromptSection]:
        return [item for item in self.items if item.kind == kind]

    def by_key(self) -> dict[str, PromptSection]:
        return {item.key: item for item in self.items}

    def notes_text(self) -> str:
        parts = []
        if persona := self.of_kind("persona"):
            parts.append("Persona:\n" + "\n\n".join(p.text for p in persona))
        if rules := self.of_kind("rules"):
            parts.append("Rules you must always follow:\n" + "\n\n".join(f"- {r.text}" for r in rules))
        return "\n\n".join(parts)

    @staticmethod
    def skills_text(skills: list[PromptSection]) -> str:
        if not skills:
            return ""
        blocks = [f"## {s.title}\n{s.text}" for s in skills]
        return "Skills for this conversation (follow the one that fits the request):\n\n" + "\n\n".join(blocks)

    def ordered_prompt(self) -> str:
        """Skills first, then notes: what changes least comes first."""
        return "\n\n".join(p for p in (self.skills_text(self.of_kind("skill")), self.notes_text()) if p)

    def signature(self) -> list[tuple[str, str]]:
        return [(item.key, item.digest) for item in self.items]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PromptSections) and self.signature() == other.signature()

    def __hash__(self) -> int:
        return hash(tuple(self.signature()))
