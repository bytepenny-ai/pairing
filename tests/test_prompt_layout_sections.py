"""Prompt layouts' building blocks (app/services/prompt_layout): the notes and skills as keyed sections, the update
note between two versions, and the "ordered" and "blocks" layouts."""

from types import SimpleNamespace

import pytest

from app.schemas.prompt_cache import PromptCacheSetting
from app.services import conversation_skills
from app.services.note_service import build_pinned_system_prompt
from app.services.prompt_layout.base import LayoutContext, PromptLayout
from app.services.prompt_layout.ordered import BlockLayout, OrderedLayout
from app.services.prompt_layout.sections import PromptSection, PromptSections
from app.services.prompt_layout.update_note import HEADER, UpdateNote


def note(note_id: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(id=note_id, content=content)


def skill(skill_id: str, name: str, content: str, description: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=skill_id, name=name, content=content, description=description)


NOTES = {
    "persona": [note("p1", "You are terse.")],
    "rules": [note("r1", "Answer in English."), note("r2", "No emoji.")],
}
SKILLS = [skill("s1", "Review", "Check the code.\n", "Code review"), skill("s2", "Poem", "Write a poem.")]


async def keep_everything(_inserts: dict[str, str]) -> set[str]:
    return {"m1", "m2"}


def ctx(sections: PromptSections, saved: dict | None = None, message_id: str | None = "m2") -> LayoutContext:
    return LayoutContext(sections, saved or {}, "question?", message_id, keep_everything)


def test_each_part_keeps_the_text_it_always_had_with_skills_first():
    sections = PromptSections.of(NOTES, SKILLS)
    skills_part = conversation_skills.build_skills_prompt(SKILLS)
    assert sections.ordered_prompt() == f"{skills_part}\n\n{build_pinned_system_prompt(NOTES)}"
    assert [s.key for s in sections.items] == ["persona:p1", "rules:r1", "rules:r2", "skill:s1", "skill:s2"]


def test_no_notes_or_skills_is_an_empty_prompt():
    assert PromptSections.of({}, []).ordered_prompt() == ""
    assert PromptSections.of({}, SKILLS[:1]).ordered_prompt().startswith("Skills for this conversation")


def test_a_saved_list_round_trips_and_a_damaged_one_is_refused():
    sections = PromptSections.of(NOTES, SKILLS)
    assert PromptSections.from_saved(sections.to_saved()) == sections
    assert PromptSections.from_saved([{"key": "x"}]) is None
    assert PromptSections.from_saved([{"key": "k", "kind": "secret", "title": "t", "text": "x"}]) is None
    assert PromptSections.from_saved("nope") is None


def test_sections_differ_by_content_and_by_which_note_holds_it():
    one = PromptSections([PromptSection("rules:a", "rules", "Rule", "x")])
    assert one == PromptSections([PromptSection("rules:a", "rules", "Rule", "x")])
    assert one != PromptSections([PromptSection("rules:a", "rules", "Rule", "y")])
    assert one != PromptSections([PromptSection("rules:b", "rules", "Rule", "x")])


def test_the_update_names_what_was_added_removed_and_changed():
    before = PromptSections.of(NOTES, SKILLS)
    changed_notes = {
        "persona": [note("p1", "You are warm.")],
        "rules": [note("r1", "Answer in English."), note("r3", "Cite sources.")],
    }
    after = PromptSections.of(
        changed_notes, [skill("s1", "Review", "Check the tests too."), skill("s9", "Plan", "Plan.")]
    )
    text = UpdateNote.between(before, after)
    assert text.startswith(HEADER)
    assert "This rule no longer applies: No emoji." in text
    assert 'The skill "Poem" was removed' in text
    assert "The persona changed. It is now: You are warm." in text
    assert "New rule you must always follow: Cite sources." in text
    assert 'The skill "Review" changed. Its instructions now:\nCheck the tests too.' in text
    assert 'New skill "Plan"' in text
    assert "Answer in English" not in text  # unchanged parts aren't repeated
    assert UpdateNote.between(before, before) == ""


def test_a_rule_edited_says_what_it_replaces():
    before = PromptSections.of({"rules": [note("r1", "Be short.")]}, [])
    after = PromptSections.of({"rules": [note("r1", "Be detailed.")]}, [])
    assert "Instead of: Be short.\n  Now: Be detailed." in UpdateNote.between(before, after)


def test_inserts_go_before_their_message_only():
    text_of = PromptLayout({}, {"m2": "UPDATE"}).text_of(lambda m: m.content)
    assert text_of(SimpleNamespace(id="m1", content="a")) == "a"
    assert text_of(SimpleNamespace(id="m2", content="b")) == "UPDATE\n\n---\n\nb"
    plain = PromptLayout("", {}).text_of(str)
    assert plain is str  # no inserts: the same function, no wrapper


@pytest.mark.asyncio
async def test_ordered_saves_nothing_and_blocks_asks_matricxon_to_keep_unchanged_parts():
    sections = PromptSections.of(NOTES, SKILLS)
    layout, state = await OrderedLayout(PromptCacheSetting()).layout(ctx(sections))
    assert layout.system_prompt == sections.ordered_prompt() and layout.inserts == {} and state == {}
    assert layout.engine_options == {}
    blocks, state = await BlockLayout(PromptCacheSetting(mode="blocks", min_block_tokens=48)).layout(ctx(sections))
    assert blocks.system_prompt == sections.ordered_prompt() and state == {}
    assert blocks.engine_options == {"cache_reuse": {"mode": "blocks", "min_tokens": 48}}
