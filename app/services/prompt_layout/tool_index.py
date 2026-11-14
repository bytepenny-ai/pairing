"""The tool index of options 2 and 3 ("append" and "index" layouts, a model that can call tools): the chat's MCP
tools never enter the prompt's tool list. It always holds the same app tools, one of them "use_tool"; the tools
themselves are told as an
instruction_updates note (one line each, with their arguments), so turning tools on or off, or a changed tool list,
costs a short note instead of re-reading the whole chat.

  - tools turned on (or the chat starts with them on): a note lists them, one line each, descriptions cut to their
    first sentence;
  - the list changes (a tool an admin adds or removes): a note with only what changed;
  - tools turned off: a note says so, and use_tool refuses while they are off;
  - the note's message leaves the history window: the list is told again.
"""

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from app.services.mcp_client import McpToolResult

if TYPE_CHECKING:  # a type only: importing base here would loop back through tool_loop_service
    from app.services.prompt_layout.base import LayoutContext

NAME = "use_tool"
_OFF = "off"
_NAME_KEYS = ("name", "tool", "tool_name")
_DESCRIPTION_CHARS = 120


class UseTool:
    """Runs one of the chat's MCP tools by name. tool_loop_service shows the call as that tool's (`route`)."""

    name = NAME
    server_name = "pAIring"
    tool_name = NAME

    def __init__(self, tools: list) -> None:
        self._tools = {t.name: t for t in tools}  # the chat's MCP tools; none while its tools are off

    @staticmethod
    def definition() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": NAME,
                "description": (
                    "Run one of this conversation's tools, as listed by the app when tools are on. Give the tool's "
                    "name and its arguments as an object."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The tool's name, as listed."},
                        "arguments": {"type": "object", "description": "The tool's arguments."},
                    },
                    "required": ["name"],
                },
            },
        }

    @property
    def off(self) -> bool:
        """The chat's tools are turned off: every call is refused (and tool_loop_service doesn't show it)."""
        return not self._tools

    def route(self, arguments: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        """(the tool to run, its arguments), or (this one, the arguments) to refuse (`call`). Takes what models send,
        not only the exact form: seen on Gemma 4, {"arguments": {"query": ...}} with no name. So: the name also as
        "tool" or "tool_name", a short form of it ("WolframAlpha" for "Wolfram__WolframAlpha"), the arguments also
        as "args" or flat; with no name, the one tool the arguments fit. Never a guess between two tools."""
        name = str(next((arguments[k] for k in _NAME_KEYS if arguments.get(k)), ""))
        inner = next((arguments[k] for k in ("arguments", "args") if isinstance(arguments.get(k), dict)), None)
        if inner is None:
            inner = {k: v for k, v in arguments.items() if k not in (*_NAME_KEYS, "arguments", "args")}
        tool = self._named(name) if name else self._only_fit(inner)
        return (tool, inner) if tool is not None else (self, arguments)

    def _named(self, name: str) -> Any:
        if name in self._tools:
            return self._tools[name]
        wanted = _plain(name)
        found = [t for n, t in self._tools.items() if wanted in (_plain(n), _plain(n.split("__")[-1]))]
        return found[0] if len(found) == 1 else None

    def _only_fit(self, inner: dict[str, Any]) -> Any:
        """The one tool whose arguments `inner` gives: no unknown ones, every required one."""
        fits = []
        for tool in self._tools.values():
            schema = (tool.definition().get("function") or {}).get("parameters") or {}
            known, required = set(schema.get("properties") or {}), set(schema.get("required") or [])
            if inner and set(inner) <= known and required <= set(inner):
                fits.append(tool)
        return fits[0] if len(fits) == 1 else None

    async def call(self, arguments: dict[str, Any]) -> McpToolResult:
        if not self._tools:
            return McpToolResult("Tools are turned off in this conversation. Answer without them.", True)
        names = ", ".join(self._tools)
        example = f'{{"name": "{next(iter(self._tools))}", "arguments": {{...}}}}'
        return McpToolResult(
            f"Which tool? Call {NAME} again with the tool's name and its arguments, like {example}. "
            f"The tools: {names}.",
            True,
        )


class ToolIndexNotes:
    """Each note says only what changed since what the model holds: what the "tools" entries still in the window
    told it, starting from the last full list. A full list again when that chain is gone (the first time, after
    tools were off, or when the full list left the window). An entry keeps `known` ({name: digest}) and `full`."""

    @staticmethod
    def notes(ctx: "LayoutContext", entries: list[dict]) -> list[dict]:
        told = [e for e in entries if e["type"] == "tools"]
        latest = told[-1] if told else None
        if not (ctx.tools_on and ctx.tool_specs):
            if latest is None or latest["digest"] == _OFF:
                return []
            return [
                ToolIndexNotes._entry(
                    ctx, {}, f"Tools are now off: don't call {NAME}; answer from what you know.", full=True, off=True
                )
            ]
        current = {ToolIndexNotes._name(s): ToolIndexNotes._digest(s) for s in ctx.tool_specs}
        known = ToolIndexNotes._known(told)
        if known == current:
            return []
        if known is None:
            return [ToolIndexNotes._entry(ctx, current, ToolIndexNotes.listing(ctx.tool_specs), full=True)]
        changed = [s for s in ctx.tool_specs if known.get(ToolIndexNotes._name(s)) != current[ToolIndexNotes._name(s)]]
        gone = [name for name in known if name not in current]
        parts = []
        if changed:
            lines = "\n".join(ToolIndexNotes._line(s.get("function") or s) for s in changed)
            parts.append(f"New or changed tools (call with {NAME}, giving the name and its arguments):\n{lines}")
        if gone:
            parts.append("No longer available: " + ", ".join(gone) + ".")
        return [ToolIndexNotes._entry(ctx, current, "\n".join(parts), full=False)]

    @staticmethod
    def listing(specs: list[dict]) -> str:
        lines = [ToolIndexNotes._line(spec.get("function") or spec) for spec in specs]
        return f"Tools are on. Call one with {NAME}, giving its name and its arguments:\n" + "\n".join(lines)

    @staticmethod
    def _known(told: list[dict]) -> dict[str, str] | None:
        """What the model holds now, or None when no full list is left to build on."""
        if not told or told[-1]["digest"] == _OFF or not isinstance(told[-1].get("known"), dict):
            return None
        return told[-1]["known"] if any(e.get("full") and e["digest"] != _OFF for e in told) else None

    @staticmethod
    def _line(function: dict) -> str:
        """`- name(arg: type, required; ...): description`, the description cut to its first sentence."""
        schema = function.get("parameters") or {}
        required = set(schema.get("required") or [])
        args = "; ".join(
            f"{name}: {prop.get('type', 'any')}{', required' if name in required else ''}"
            for name, prop in (schema.get("properties") or {}).items()
            if isinstance(prop, dict)
        )
        about = " ".join(str(function.get("description") or "").split())
        about = re.split(r"(?<=[.!?])\s", about, maxsplit=1)[0]
        about = about if len(about) <= _DESCRIPTION_CHARS else about[: _DESCRIPTION_CHARS - 1].rstrip() + "…"
        return f"- {function.get('name', '')}({args}){f': {about}' if about else ''}"

    @staticmethod
    def _name(spec: dict) -> str:
        return str((spec.get("function") or spec).get("name", ""))

    @staticmethod
    def _digest(value: object) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]

    @staticmethod
    def _entry(ctx: "LayoutContext", known: dict, text: str, full: bool, off: bool = False) -> dict:
        digest = _OFF if off else ToolIndexNotes._digest(known)
        entry = {"type": "tools", "key": "tools", "digest": digest, "message_id": ctx.message_id, "text": text}
        return {**entry, "known": known, "full": full}


def _plain(name: str) -> str:
    return "".join(c for c in name.casefold() if c.isalnum())
