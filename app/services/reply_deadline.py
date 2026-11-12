"""The reply timeout (Admin settings > System > Chat > Reply timeout), counted so that a slow but working prompt read
doesn't fail: while the engine reports read progress ({"read_progress": ...} chunks, before any text) the deadline
moves on, so only a read stuck for the whole timeout fails; from the first word, the reply gets the full timeout to
be written. A CPU can need many minutes to read a long file, and that used to end as "Reply timed out"."""

import asyncio


class ReplyDeadline:
    def __init__(self, timeout: asyncio.Timeout, seconds: float | None) -> None:
        self._timeout = timeout
        self._seconds = seconds  # None: no timeout
        self._writing = False

    def progress(self) -> None:
        """The engine read more of the prompt."""
        if not self._writing:
            self._move()

    def text(self) -> None:
        """A text chunk arrived; the first one starts the writing's own timeout."""
        if not self._writing:
            self._writing = True
            self._move()

    def _move(self) -> None:
        if self._seconds is not None:
            self._timeout.reschedule(asyncio.get_running_loop().time() + self._seconds)
