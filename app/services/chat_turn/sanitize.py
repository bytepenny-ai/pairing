"""The prepare-a-reply stage before the model runs: cleaning, adjusting, embeddings and checks, as an ordered list of
stages (pipeline.py). Each stage reads and writes a ChatTurn and says which fields it needs and sets, so a pipeline in
the wrong order fails when it is built, not mid-chat.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import ClassVar

from app.services.chat_turn.turn import GIVEN, ChatTurn
from app.services.live_workflow_bus import live_workflow


class TurnStage(ABC):
    name: ClassVar[str]  # also its node in Stats > Visual chat workflow ("turn_<name>")
    requires: ClassVar[frozenset[str]] = frozenset()
    provides: ClassVar[frozenset[str]] = frozenset()

    @abstractmethod
    async def run(self, turn: ChatTurn) -> list[str]:
        """Does this stage's part of `turn`; returns notices for the sender (things cut or left out)."""


class CleanStage(TurnStage, ABC):
    """Tidies what the user sent."""


class AdjustStage(TurnStage, ABC):
    """Fits the request to the settings, the model and the context window."""


class EnrichStage(TurnStage, ABC):
    """Adds what the question needs: skills, earlier files, knowledge (the embedding steps)."""


class AssembleStage(TurnStage, ABC):
    """Builds the messages to send to the model, before it runs."""


class CheckStage(TurnStage, ABC):
    """May stop the turn before the model runs."""


class PipelineOrderError(ValueError):
    """A stage needs a field no earlier stage sets."""


class SanitizePipeline:
    def __init__(self, stages: list[TurnStage]) -> None:
        self._stages = stages
        self._check_order()

    @property
    def stages(self) -> list[TurnStage]:
        return list(self._stages)

    def _check_order(self) -> None:
        known = ChatTurn.field_names()
        ready = set(GIVEN)
        for stage in self._stages:
            unknown = (stage.requires | stage.provides) - known
            if unknown:
                raise PipelineOrderError(f"{stage.name}: no such turn field {sorted(unknown)}")
            missing = stage.requires - ready
            if missing:
                raise PipelineOrderError(f"{stage.name} needs {sorted(missing)} before it")
            ready |= stage.provides

    async def run(self, turn: ChatTurn) -> AsyncIterator[dict]:
        """Runs the stages in order, yielding {"notice": ...} events; stops early when a stage sets `turn.stopped`."""
        for stage in self._stages:
            node = f"turn_{stage.name}"
            live_workflow.enter(node)
            try:
                notices = await stage.run(turn)
            finally:
                live_workflow.exit(node)
            for notice in notices:
                yield {"notice": notice}
            if turn.stopped:
                return
