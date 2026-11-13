"""The app's own tools (tool_loop_service.py runs them like MCP tools):
  - "use_skill" ("index" layout): the chat model reads a listed skill's full instructions when a request needs one,
    instead of a guess by embeddings;
  - "instruction_updates" ("append" and "index"): what the app tells a tool model about changed notes and skills
    comes as this tool's results before a message (base.ToolNote), never in the user's words. The model needn't
    call it; offered from a chat's start, so the tool list never changes.

Their definitions never change (the skill names are in the system prompt's list, not here), so they never change
the prompt's start. "use_skill" serves the chat's current skills, carried in the reply's params under `PARAM_KEY`.
A reply's tool calls aren't kept in the history, so the next message gets the call and the skill's text back
before it (`IndexLayout`, as a ToolNote), where they stay.
"""

from collections.abc import Iterable
from typing import Any

from app.models import Message
from app.services.mcp_client import McpToolResult

NAME = "use_skill"
PARAM_KEY = "skill_tool"  # reply params: {skill title: full text}
NOTICE_NAME = "instruction_updates"
NOTICE_PARAM_KEY = "notice_tool"  # reply params: True offers it
# Before every skill text the model gets: a skill it read for a request it doesn't fit costs a step, not the reply.
GUARD = "Follow this skill only if the user's request is the task it is for; otherwise ignore it and answer normally."
_DESCRIPTION = (
    "Read the full instructions of one of this conversation's skills (listed in the system prompt). Only for a "
    "request that is exactly the task a skill is for; most requests need no skill."
)


class SkillTool:
    name = NAME
    server_name = "pAIring"
    tool_name = NAME

    def __init__(self, skills: dict[str, str]) -> None:
        self._skills = skills

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> list["SkillTool"]:
        skills = params.get(PARAM_KEY)
        return [cls(skills)] if isinstance(skills, dict) and skills else []

    @staticmethod
    def definition() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": NAME,
                "description": _DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "The skill's name, as listed."}},
                    "required": ["name"],
                },
            },
        }

    async def call(self, arguments: dict[str, Any]) -> McpToolResult:
        requested = str(arguments.get("name") or "")
        title = self.match(requested, self._skills)
        if title is None:
            names = ", ".join(f'"{t}"' for t in self._skills)
            return McpToolResult(f'No skill named "{requested}". This conversation\'s skills: {names}.', True)
        return McpToolResult(self.guarded(self._skills[title]), False)

    @staticmethod
    def guarded(text: str) -> str:
        return f"{GUARD}\n\n{text}"

    @staticmethod
    def match(requested: str, titles: Iterable[str]) -> str | None:
        """The title `requested` names: exact, or ignoring case, quotes and extra spaces."""
        titles = list(titles)
        if requested in titles:
            return requested
        wanted = _plain(requested)
        return next((t for t in titles if _plain(t) == wanted), None)

    @staticmethod
    def uses(messages: Iterable[Message]) -> list[tuple[str, list[str]]]:
        """(reply id, skill names it read) for each reply that called the tool successfully, oldest first."""
        found = []
        for message in messages:
            names = [
                str((event.get("arguments") or {}).get("name") or "")
                for event in message.tool_events or []
                if isinstance(event, dict) and event.get("name") == NAME and not event.get("is_error")
            ]
            if message.role == "assistant" and names:
                found.append((message.id, names))
        return found


def _plain(name: str) -> str:
    return " ".join(name.strip().strip("\"'`").split()).casefold()


class NoticeTool:
    name = NOTICE_NAME
    server_name = "pAIring"
    tool_name = NOTICE_NAME

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> list["NoticeTool"]:
        return [cls()] if params.get(NOTICE_PARAM_KEY) else []

    @staticmethod
    def definition() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": NOTICE_NAME,
                "description": (
                    "Changes to your instructions and skills in this conversation. The app adds its results by "
                    "itself, right before the message where something changed; you never need to call it."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def call(self, _arguments: dict[str, Any]) -> McpToolResult:
        return McpToolResult("Nothing changed since the last update.", False)
