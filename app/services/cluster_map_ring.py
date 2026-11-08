"""The map's pAIring box in a ring: more than one machine runs pAIring on the shared database.

The map keeps one pAIring box; in a ring it is named "pAIring (ring mode)" and its panel lists every machine.
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
        """Each machine with an online pAIring (name, addresses); empty unless it is a ring (2+)."""
        if not self._shared(db):
            return []
        rows, now = await self._registry.servers(db)
        machines: dict[str, str] = {}
        for row in rows:
            if row.is_primary and self._registry.online(row, now):
                addresses = (row.details or {}).get("addresses") or []
                machines[ServerRegistry.machine_of(row)] = ", ".join(addresses) or "no address reported"
        if len(machines) < 2:
            return []
        return [MapServer(name=name, addresses=addresses) for name, addresses in sorted(machines.items())]


pairing_ring = PairingRing()
