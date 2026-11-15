"""The chat's Reasoning setting (GenerationParams.think, the chat header's Reasoning chip) and what each engine gets.

- True ("on"): reason before answering.
- False ("off", the default; None from chats saved before counts as off): never reason. Matricxon also blocks the
  tokens that open reasoning, so a small model can't reason anyway.
- "auto" (the model's choice): no switch sent; the model's own default applies and it may reason when it wants to.
  Its reasoning shows as progress like "on" (reasoning_ticks).
"""

from typing import Literal

ThinkValue = bool | Literal["auto"] | None
AUTO = "auto"


class ThinkMode:
    @staticmethod
    def engine_switch(params: dict) -> bool | None:
        """The engine's thinking switch: True, False, or None to leave it to the model."""
        think = params.get("think")
        return None if think == AUTO else think is True
