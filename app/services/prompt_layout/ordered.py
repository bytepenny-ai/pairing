"""The "ordered" and "blocks" layouts: one system prompt, skills before notes (what changes least first)."""

from app.services.prompt_layout.base import LayoutContext, PromptLayout, PromptStrategy


class OrderedLayout(PromptStrategy):
    """Exact: a change makes the engine re-read from the changed part to the end, never what comes before it."""

    mode = "ordered"

    async def layout(self, ctx: LayoutContext) -> tuple[PromptLayout, dict]:
        return PromptLayout(ctx.sections.ordered_prompt()), {}


class BlockLayout(OrderedLayout):
    """As "ordered", and Matricxon keeps the unchanged parts after a change: it copies them to their new place
    instead of re-reading them (its `cache_reuse` option). Approximate: those parts were read next to the old text.
    Other engines ignore the option, so for them this is "ordered"."""

    mode = "blocks"

    async def layout(self, ctx: LayoutContext) -> tuple[PromptLayout, dict]:
        layout, state = await super().layout(ctx)
        layout.engine_options = {"cache_reuse": {"mode": "blocks", "min_tokens": self._setting.min_block_tokens}}
        return layout, state
