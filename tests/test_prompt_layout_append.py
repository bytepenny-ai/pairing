"""The "append" prompt layout (app/services/prompt_layout/append.py): the system prompt stays as the chat started and
each change is added as an update to the message where it happened, until it is rebuilt."""

import pytest

from app.schemas.prompt_cache import PromptCacheSetting
from app.services.prompt_layout.append import AppendLayout
from app.services.prompt_layout.base import LayoutContext
from app.services.prompt_layout.sections import PromptSection, PromptSections
from app.services.prompt_layout.update_note import HEADER


def rules(*texts: str) -> PromptSections:
    return PromptSections(PromptSection(f"rules:{i}", "rules", "Rule", t) for i, t in enumerate(texts))


def window(*ids: str):
    async def kept(_inserts: dict[str, str]) -> set[str]:
        return set(ids)

    return kept


async def run(
    layout: AppendLayout, sections: PromptSections, saved: dict, message_id: str | None, kept=None, has_image=False
):
    ctx = LayoutContext(
        sections, dict(saved), "q?", message_id, kept or window("m1", "m2", "m3", "m4", "m5"), has_image
    )
    return await layout.layout(ctx)


@pytest.fixture
def append() -> AppendLayout:
    return AppendLayout(PromptCacheSetting(mode="append", max_updates=2, max_update_chars=2000))


@pytest.mark.asyncio
async def test_a_new_chat_starts_from_its_current_notes(append):
    layout, state = await run(append, rules("A"), {}, "m1")
    assert layout.system_prompt == rules("A").ordered_prompt() and layout.inserts == {}
    assert state["mode"] == "append" and state["updates"] == []


@pytest.mark.asyncio
async def test_a_change_is_added_to_its_message_and_the_prompt_keeps_its_start(append):
    _, state = await run(append, rules("A"), {}, "m1")
    layout, state = await run(append, rules("A", "B"), state, "m2")
    assert layout.system_prompt == rules("A").ordered_prompt()  # unchanged: the engine's cache still matches
    assert layout.inserts["m2"].startswith(HEADER) and "New rule you must always follow: B" in layout.inserts["m2"]
    # the next turn, with no change, gives the same prompt: the update stays on m2
    again, state2 = await run(append, rules("A", "B"), state, "m3")
    assert again.system_prompt == layout.system_prompt and again.inserts == layout.inserts
    assert state2 == state


@pytest.mark.asyncio
async def test_two_changes_on_one_message_are_both_kept_in_order(append):
    _, state = await run(append, rules("A"), {}, "m1")
    _, state = await run(append, rules("A", "B"), state, "m2")
    layout, _ = await run(append, rules("A", "B", "C"), state, "m2")  # the same message answered again
    assert layout.inserts["m2"].index(": B") < layout.inserts["m2"].index(": C")


@pytest.mark.asyncio
async def test_too_many_updates_rebuild_the_prompt_from_the_current_notes(append):
    _, state = await run(append, rules("A"), {}, "m1")
    _, state = await run(append, rules("A", "B"), state, "m2")
    _, state = await run(append, rules("A", "B", "C"), state, "m3")
    layout, state = await run(append, rules("A", "B", "C", "D"), state, "m4")  # a third update: over max_updates=2
    assert layout.system_prompt == rules("A", "B", "C", "D").ordered_prompt() and layout.inserts == {}
    assert state["updates"] == [] and state["base"] == state["current"]


@pytest.mark.asyncio
async def test_long_updates_rebuild_too():
    small = AppendLayout(PromptCacheSetting(mode="append", max_updates=50, max_update_chars=500))
    _, state = await run(small, rules("A"), {}, "m1")
    layout, state = await run(small, rules("A", "x" * 600), state, "m2")
    assert layout.inserts == {} and state["updates"] == []


@pytest.mark.asyncio
async def test_an_update_whose_message_left_the_window_is_carried_to_the_current_message(append):
    _, state = await run(append, rules("A"), {}, "m1")
    _, state = await run(append, rules("A", "B"), state, "m2")
    _, state = await run(append, rules("A", "B", "C"), state, "m3")
    layout, state = await run(append, rules("A", "B", "C"), state, "m5", kept=window("m3", "m4", "m5"))  # m2 gone
    assert layout.system_prompt == rules("A").ordered_prompt()  # the prompt's start kept: nothing re-read
    assert list(layout.inserts) == ["m3", "m5"]
    assert ": B" in layout.inserts["m5"] and ": C" in layout.inserts["m5"]  # every change since the start
    again, _ = await run(append, rules("A", "B", "C"), state, "m6", kept=window("m3", "m4", "m5", "m6"))
    assert again.inserts == layout.inserts  # stays on its message


@pytest.mark.asyncio
async def test_a_carried_update_that_cant_fit_rebuilds(append):
    _, state = await run(append, rules("A"), {}, "m1")
    _, state = await run(append, rules("A", "B"), state, "m2")
    layout, _ = await run(append, rules("A", "B"), state, "m5", kept=window("m4"))  # m5 itself won't fit with it
    assert layout.system_prompt == rules("A", "B").ordered_prompt() and layout.inserts == {}


@pytest.mark.asyncio
async def test_a_long_update_waits_for_a_message_without_an_image(append):
    _, state = await run(append, rules("A"), {}, "m1")
    long_rule = "x" * 700
    on_image, state = await run(append, rules("A", long_rule), state, "m2", has_image=True)
    assert on_image.inserts == {}  # would hide the image
    after, _ = await run(append, rules("A", long_rule), state, "m3")
    assert list(after.inserts) == ["m3"] and long_rule in after.inserts["m3"]
    short, _ = await run(append, rules("A", "B"), state, "m3", has_image=True)
    assert list(short.inserts) == ["m3"]  # a short one goes on an image message


@pytest.mark.asyncio
async def test_read_only_renders_what_is_saved_and_changes_nothing(append):
    _, state = await run(append, rules("A"), {}, "m1")
    _, state = await run(append, rules("A", "B"), state, "m2")
    layout, kept_state = await run(append, rules("A", "B", "C"), state, None)
    assert kept_state == state and layout.system_prompt == rules("A").ordered_prompt()
    assert list(layout.inserts) == ["m2"] and ": C" not in layout.inserts["m2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damaged",
    [
        {"mode": "index"},
        {"mode": "append", "base": "x", "current": [], "updates": []},
        {"mode": "append", "base": [], "current": [], "updates": [{"message_id": 3}]},
        {"mode": "append", "base": [], "current": [], "updates": "x"},
    ],
)
async def test_anything_unusable_saved_starts_again(append, damaged):
    layout, state = await run(append, rules("A"), damaged, "m1")
    assert layout.system_prompt == rules("A").ordered_prompt() and state["updates"] == []
