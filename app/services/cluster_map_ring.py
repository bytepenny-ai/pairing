"""The map's pAIring box in a ring: more than one machine runs pAIring on the shared database.

The map keeps one pAIring box; in a ring it is named "pAIring (ring mode)" and its panel lists every machine
(offline ones greyed, this one marked).
"""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.cluster import MapServer
from app.services.db_clock import shared_database
from app.services.server_registry import ServerRegistry, server_registry

RING_NAME = "pAIring (ring mode)"


class PairingRing:
    def __init__(
        self,
        registry: ServerRegistry = server_registry,
        shared: Callable[[AsyncSession], bool] = shared_database,
    ) -> None:
        self._registry = registry
        self._shared = shared

    async def members(self, db: AsyncSession) -> list[MapServer]:
        """Every known pAIring machine (offline ones too), when 2+ are online (a ring); else empty."""
        if not self._shared(db):
            return []
        rows, now = await self._registry.servers(db)
        own = next((r for r in rows if r.server_id == self._registry.server_id), None)
        here = ServerRegistry.machine_of(own) if own else None
        machines: dict[str, MapServer] = {}
        for row in rows:
            if not row.is_primary:
                continue
            name = ServerRegistry.machine_of(row)
            online = self._registry.online(row, now)
            if name in machines and not online:
                continue  # an older offline row of a machine that is listed
            addresses = ", ".join((row.details or {}).get("addresses") or []) or "no address reported"
            machines[name] = MapServer(name=name, addresses=addresses, online=online, this_server=name == here)
        if sum(m.online for m in machines.values()) < 2:
            return []
        return sorted(machines.values(), key=lambda m: (not m.online, m.name))


pairing_ring = PairingRing()
