"""Each MCP server's last good tool list, saved in the database (AppSetting "mcp_known_tools"), so the chat page's
Tools menu can show them without contacting the server, also after a restart (chat_tools_view.py). Written by
mcp_tool_catalog.py when a server lists its tools; a list saved under other server settings (URL, headers) is ignored.
"""

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting, McpServer
from app.services.mcp_client import McpToolInfo

_KEY = "mcp_known_tools"


class McpKnownTools:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def fingerprint(server: McpServer) -> str:
        return hashlib.sha256(f"{server.url}\n{server.headers_encrypted or ''}".encode()).hexdigest()

    async def load(self, servers: list[McpServer]) -> dict[str, list[McpToolInfo]]:
        """The saved list of each server that has one for its current settings, by server id."""
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, _KEY))
        saved = dict(row.value) if row else {}
        found = {}
        for server in servers:
            entry = saved.get(server.id)
            if entry and entry.get("fingerprint") == self.fingerprint(server):
                found[server.id] = [McpToolInfo(t["name"], t["description"], t["schema"]) for t in entry["tools"]]
        return found

    async def save(self, server: McpServer, listing: list[McpToolInfo]) -> None:
        """Stores `server`'s list if it changed."""
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, _KEY))
        saved = dict(row.value) if row else {}
        entry = {
            "fingerprint": self.fingerprint(server),
            "tools": [{"name": t.name, "description": t.description, "schema": t.input_schema} for t in listing],
        }
        if saved.get(server.id) == entry:
            return
        saved[server.id] = entry
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=_KEY, value=saved))
        else:
            row.value = saved
        await self._db.commit()
