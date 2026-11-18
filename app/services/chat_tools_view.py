"""What the chat page's Tools button shows for one chat (GET /api/mcp/conversations/{id}/tools).

Built without contacting any tool server: opening a chat must not make outside calls the user didn't ask for, and a
free or rate-limited server would pay for each one. It shows the chat's saved tools, the tools fetched before
(saved by mcp_known_tools.py) and the enabled servers with their last error. Servers are contacted only to run a reply
with tools on, or on "Update tools" (refresh).
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import McpServer
from app.schemas.mcp import McpChatServer, McpChatTool, McpChatTools, McpToolOut
from app.services import mcp_settings_service
from app.services.chat_tool_set import ChatToolSet
from app.services.engines.registry import registry
from app.services.mcp_server_service import McpServerService
from app.services.mcp_tool_catalog import ExposedTool, McpToolCatalog
from app.services.prompt_cache_setting import PromptCacheSettings


class ChatToolsView:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def enabled(self) -> bool:
        """Off when MCP is off, or when the active engine can't pass tools to its models (e.g. a connector)."""
        return registry.active().capabilities.tools and await mcp_settings_service.get_enabled(self._db)

    async def of(self, params: dict[str, Any] | None) -> McpChatTools:
        enabled = await self.enabled()
        servers = await McpServerService(self._db).list(only_enabled=True) if enabled else []
        catalog = McpToolCatalog(self._db)
        known = await catalog.known(servers)
        notes = [McpChatServer(name=s.name, error=McpToolCatalog.last_error(s)) for s in servers]
        saved = (params or {}).get("tool_snapshot") or []
        # Options 2 and 3 (tool index): the chat follows the current tools, so nothing to offer as new.
        if not saved or (await PromptCacheSettings(self._db).get()).mode in ("append", "index"):
            tools = [McpChatTool(name=t.name, description=t.description) for t in known]
            return McpChatTools(enabled=enabled, frozen=False, tools=tools, servers=notes)
        return McpChatTools(
            enabled=enabled,
            frozen=True,
            tools=self._saved(saved, known, servers, await catalog.listed(servers)),
            new_tools=[McpToolOut(name=t.name, description=t.description) for t in ChatToolSet.new_tools(saved, known)],
            servers=notes,
        )

    @staticmethod
    def _saved(
        saved: list[dict[str, Any]], known: list[ExposedTool], servers: list[McpServer], listed: set[str]
    ) -> list[McpChatTool]:
        """The chat's saved tools. One is unavailable when its server is gone, or when its server's last listing
        lacked it; a server not contacted yet is taken at its word."""
        enabled = {s.name for s in servers}
        return [
            McpChatTool(
                name=t.name,
                description=t.spec["function"].get("description", ""),
                available=t.available or (t.server_name in enabled and t.server_name not in listed),
            )
            for t in ChatToolSet.tools(saved, known)
        ]
