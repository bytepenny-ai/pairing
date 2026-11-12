"""A reply's speed, shown under it: time to first token, total time, and tokens/sec. Also kept for the read-speed
estimate (read_speed.py): the prompt tokens read (not reused from the cache), how long that took, the model and the
engine host that served it.

Times are measured here, so every engine has them. Token counts come from the engine's final
{"usage": ...} chunk (llama.cpp timings, Matricxon's done line); cloud connectors send none.
A tool loop makes several model calls, so usage chunks add up.
"""

import time
from collections.abc import Callable


class ReplyStats:
    def __init__(self, clock: Callable[[], float] = time.monotonic, model: str | None = None) -> None:
        self._clock = clock
        self._model = model
        self._read_tokens: int | None = None
        self._read_ms = 0.0
        self._host: str | None = None
        self._started = clock()
        self._first_text: float | None = None
        self._output_tokens = 0
        self._output_ms = 0.0
        self._prompt_tokens = 0
        self._has_usage = False

    def text(self) -> None:
        """Call on every text chunk; only the first one counts."""
        if self._first_text is None:
            self._first_text = self._clock()

    def usage(self, usage: dict) -> None:
        self._has_usage = True
        self._output_tokens += int(usage.get("output_tokens") or 0)
        self._output_ms += float(usage.get("output_ms") or 0)
        self._prompt_tokens += int(usage.get("prompt_tokens") or 0)
        if usage.get("read_tokens") is not None:
            self._read_tokens = (self._read_tokens or 0) + int(usage["read_tokens"])
            self._read_ms += float(usage.get("read_ms") or 0)
        self._host = usage.get("host") or self._host

    def result(self) -> dict | None:
        """None when no text came (nothing to time)."""
        if self._first_text is None:
            return None
        now = self._clock()
        stats: dict = {
            "first_token_ms": round((self._first_text - self._started) * 1000),
            "total_ms": round((now - self._started) * 1000),
        }
        if self._has_usage and self._output_tokens:
            # The engine's own generation time if given, else from the first token to the end.
            seconds = self._output_ms / 1000 or (now - self._first_text)
            stats["output_tokens"] = self._output_tokens
            stats["prompt_tokens"] = self._prompt_tokens or None
            stats["tokens_per_second"] = round(self._output_tokens / seconds, 1) if seconds > 0 else None
        if self._read_tokens is not None:
            stats["read_tokens"], stats["read_ms"] = self._read_tokens, round(self._read_ms)
        stats.update({k: v for k, v in (("model", self._model), ("host", self._host)) if v})
        return stats

    @staticmethod
    def from_llamacpp(timings: dict) -> dict:
        return {
            "output_tokens": timings.get("predicted_n"),
            "output_ms": timings.get("predicted_ms"),
            "prompt_tokens": timings.get("prompt_n"),
            # prompt_n counts only what was evaluated: the cache's part is in "cache_n".
            "read_tokens": timings.get("prompt_n"),
            "read_ms": timings.get("prompt_ms"),
        }

    @staticmethod
    def from_matricxon(done: dict) -> dict:
        # Its eval_duration starts with the prompt read (prompt_eval_duration): only the rest is generation.
        eval_ns = max((done.get("eval_duration") or 0) - (done.get("prompt_eval_duration") or 0), 0)
        return {
            "output_tokens": done.get("eval_count"),
            "output_ms": eval_ns / 1_000_000,
            "prompt_tokens": done.get("prompt_eval_count"),
            # An older Matricxon doesn't say how much came from its cache: no read sample then.
            "read_tokens": (
                (done.get("prompt_eval_count") or 0) - done["prompt_cached_count"]
                if done.get("prompt_cached_count") is not None
                else None
            ),
            "read_ms": (done.get("prompt_eval_duration") or 0) / 1_000_000,
        }
