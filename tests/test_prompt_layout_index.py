"""The "index" prompt layout (app/services/prompt_layout/index.py): skills listed in one line each, a skill's full text
added to the message that needs it; and its relevance check (skill_relevance.py)."""

import numpy as np
import pytest

from app.schemas.prompt_cache import PromptCacheSetting
from app.services.prompt_layout import skill_relevance
from app.services.prompt_layout.base import LayoutContext
from app.services.prompt_layout.index import IndexLayout
from app.services.prompt_layout.sections import PromptSection, PromptSections
from app.services.prompt_layout.skill_chat_tool import GUARD
from app.services.prompt_layout.skill_relevance import SkillRelevance

REVIEW = PromptSection("skill:1", "skill", "Review", "Check the code carefully.", "Code review")
POEM = PromptSection("skill:2", "skill", "Poem", "Write rhyming verse.\nKeep it short.")
RULE = PromptSection("rules:9", "rules", "Rule", "Be kind.")


class FakeRelevance:
    """Scores by a table; None means "can't tell" (no embedding model)."""

    def __init__(self, table: dict[str, float] | None) -> None:
        self.table = table
        self.asked: list[str] = []

    @property
    def available(self) -> bool:
        return self.table is not None

    async def scores(self, question: str, skills: list[PromptSection]) -> dict[str, float] | None:
        self.asked.append(question)
        return {s.key: self.table.get(s.key, 0.0) for s in skills} if self.table is not None else None


def window(*ids: str):
    async def kept(_inserts: dict[str, str]) -> set[str]:
        return set(ids)

    return kept


ALL = window("m1", "m2", "m3", "m4")


async def run(relevance, sections, saved, message_id, question="How do I fix this bug?", kept=ALL, **setting):
    layout = IndexLayout(PromptCacheSetting(mode="index", **setting), relevance)
    return await layout.layout(LayoutContext(sections, dict(saved), question, message_id, kept))


@pytest.mark.asyncio
async def test_the_prompt_lists_skills_then_notes_and_adds_only_the_one_that_fits():
    sections = PromptSections([REVIEW, POEM, RULE])
    layout, state = await run(FakeRelevance({"skill:1": 0.6, "skill:2": 0.1}), sections, {}, "m1")
    assert layout.system_prompt.startswith("Skills for this conversation.")
    assert "- Review: Code review" in layout.system_prompt
    assert "- Poem: Write rhyming verse." in layout.system_prompt  # no description: the first line
    assert layout.system_prompt.endswith(sections.notes_text())
    assert "Check the code carefully." not in layout.system_prompt
    assert layout.inserts == {"m1": f'Skill "Review" (its full instructions). {GUARD}\n\nCheck the code carefully.'}
    assert [e["key"] for e in state["entries"]] == ["skill:1"]


@pytest.mark.asyncio
async def test_a_loaded_skill_stays_on_its_message_and_isnt_added_again():
    sections = PromptSections([REVIEW, POEM])
    relevance = FakeRelevance({"skill:1": 0.9})
    first, state = await run(relevance, sections, {}, "m1")
    second, state2 = await run(relevance, sections, state, "m2")
    assert second.system_prompt == first.system_prompt and second.inserts == first.inserts
    assert state2 == state


@pytest.mark.asyncio
async def test_at_most_max_loaded_best_first_and_nothing_for_small_talk():
    sections = PromptSections([REVIEW, POEM])
    table = {"skill:1": 0.5, "skill:2": 0.7}
    layout, _ = await run(FakeRelevance(table), sections, {}, "m1", max_loaded=1)
    assert list(layout.inserts) == ["m1"] and "Poem" in layout.inserts["m1"] and "Review" not in layout.inserts["m1"]
    quiet, state = await run(FakeRelevance(table), sections, {}, "m1", question="OK thanks")
    assert quiet.inserts == {} and state["entries"] == []


@pytest.mark.asyncio
async def test_without_an_embedding_model_every_skill_comes_with_the_first_message():
    sections = PromptSections([REVIEW, POEM])
    layout, state = await run(FakeRelevance(None), sections, {}, "m1", question="Hi")
    assert "Review" in layout.inserts["m1"] and "Poem" in layout.inserts["m1"]
    later, _ = await run(FakeRelevance(None), sections, state, "m2")
    assert list(later.inserts) == ["m1"]  # nothing added twice


@pytest.mark.asyncio
async def test_a_changed_skill_is_added_again_in_its_new_version_when_needed():
    relevance = FakeRelevance({"skill:1": 0.9})
    _, state = await run(relevance, PromptSections([REVIEW]), {}, "m1")
    edited = PromptSection(REVIEW.key, "skill", "Review", "Check the tests as well.", "Code review")
    layout, _ = await run(relevance, PromptSections([edited]), state, "m2")
    assert "Check the code carefully." in layout.inserts["m1"]  # the old text stays where it was read
    assert "Check the tests as well." in layout.inserts["m2"]


@pytest.mark.asyncio
async def test_a_removed_skill_gets_one_note_and_the_list_never_changes():
    relevance = FakeRelevance({})
    first, state = await run(relevance, PromptSections([REVIEW, POEM]), {}, "m1")
    layout, state = await run(relevance, PromptSections([REVIEW]), state, "m2")
    assert layout.system_prompt == first.system_prompt
    assert layout.inserts["m2"] == 'The skill "Poem" is no longer available: don\'t use it any more.'
    again, _ = await run(relevance, PromptSections([REVIEW]), state, "m3")
    assert list(again.inserts) == ["m2"]


@pytest.mark.asyncio
async def test_a_skill_whose_message_left_the_window_is_added_again_when_needed():
    relevance = FakeRelevance({"skill:1": 0.9})
    _, state = await run(relevance, PromptSections([REVIEW]), {}, "m1")
    layout, state = await run(relevance, PromptSections([REVIEW]), state, "m4", kept=window("m3", "m4"))
    assert list(layout.inserts) == ["m4"] and [e["message_id"] for e in state["entries"]] == ["m4"]


@pytest.mark.asyncio
async def test_read_only_changes_nothing_and_asks_no_one():
    relevance = FakeRelevance({"skill:1": 0.9})
    _, state = await run(relevance, PromptSections([REVIEW]), {}, "m1")
    relevance.asked.clear()
    layout, same = await run(relevance, PromptSections([REVIEW, POEM]), state, None)
    assert same == state and list(layout.inserts) == ["m1"] and relevance.asked == []


@pytest.mark.asyncio
async def test_a_damaged_save_starts_again():
    saved = {"mode": "index", "listed": [], "entries": [{"type": "load", "key": "skill:1"}]}
    layout, state = await run(FakeRelevance({}), PromptSections([REVIEW]), saved, "m1")
    assert "- Review" in layout.system_prompt and state["entries"] == []


@pytest.mark.asyncio
async def test_relevance_embeds_each_skill_once_and_scores_by_cosine(monkeypatch):
    calls: list[str] = []

    async def fake_embed(text: str, _model: str) -> list[float]:
        calls.append(text)
        return [1.0, 0.0] if "code" in text.lower() else [0.0, 1.0]

    monkeypatch.setattr(skill_relevance, "embed", fake_embed)
    monkeypatch.setattr(SkillRelevance, "_vectors", type(SkillRelevance._vectors)())
    relevance = SkillRelevance("minilm")
    scores = await relevance.scores("review my code", [REVIEW, POEM])
    assert scores == {"skill:1": pytest.approx(1.0), "skill:2": pytest.approx(0.0)}
    await relevance.scores("another code question", [REVIEW, POEM])
    assert len(calls) == 4  # two questions, each skill once


@pytest.mark.asyncio
async def test_relevance_is_unknown_without_a_model_or_when_embedding_fails(monkeypatch):
    assert not SkillRelevance(None).available
    assert await SkillRelevance(None).scores("q", [REVIEW]) is None

    async def broken(_text: str, _model: str) -> list[float]:
        return []

    monkeypatch.setattr(skill_relevance, "embed", broken)
    assert await SkillRelevance("m").scores("q", [REVIEW]) is None
    assert SkillRelevance._cosine(np.zeros(2), np.zeros(2)) == 0.0
