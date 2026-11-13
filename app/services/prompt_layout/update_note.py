"""The short update the "append" layout adds to a message when the chat's notes or skills changed: what was added,
removed or changed, compared by each part's key (a note, a rule, a skill)."""

from app.services.prompt_layout.sections import PromptSection, PromptSections

HEADER = "Update to your instructions (it replaces what it names, from this message on):"


class UpdateNote:
    @classmethod
    def between(cls, before: PromptSections, after: PromptSections) -> str:
        """The update text, or "" when nothing changed."""
        old, new = before.by_key(), after.by_key()
        lines = [cls._removed(old[key]) for key in old if key not in new]
        for key, section in new.items():
            if key not in old:
                lines.append(cls._added(section))
            elif old[key].digest != section.digest:
                lines.append(cls._changed(old[key], section))
        return "\n".join([HEADER, *lines]) if lines else ""

    @staticmethod
    def _added(section: PromptSection) -> str:
        if section.kind == "skill":
            return f'- New skill "{section.title}" (follow it when it fits the request):\n{section.text}'
        if section.kind == "persona":
            return f"- New persona: {section.text}"
        return f"- New rule you must always follow: {section.text}"

    @staticmethod
    def _removed(section: PromptSection) -> str:
        if section.kind == "skill":
            return f'- The skill "{section.title}" was removed: don\'t use it any more.'
        if section.kind == "persona":
            return f"- This persona no longer applies: {section.text}"
        return f"- This rule no longer applies: {section.text}"

    @staticmethod
    def _changed(before: PromptSection, after: PromptSection) -> str:
        if after.kind == "skill":
            return f'- The skill "{before.title}" changed. Its instructions now:\n{after.text}'
        if after.kind == "persona":
            return f"- The persona changed. It is now: {after.text}"
        return f"- A rule changed. Instead of: {before.text}\n  Now: {after.text}"
