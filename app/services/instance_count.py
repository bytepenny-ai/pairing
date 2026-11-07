"""Local instances per machine (Settings > System): each server sets its own, so a small server sharing the database
is not given a big one's count. Stored per machine in AppSetting ("instance_count:<host>").

The old single "instance_count" key still applies to a machine that already ran extra instances (a non-primary
server row of it), and on SQLite (one machine only), so an upgrade keeps their count; a new server starts with 1.
"""

import socket

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import SYSTEM_OWNER_ID, AppSetting
from app.models.server_coordination import Server
from app.services.db_clock import shared_database

LEGACY_KEY = "instance_count"
DEFAULT_COUNT = 1
_KEY_LEN = 100  # AppSetting.key


class InstanceCount:
    def __init__(self, db: AsyncSession, machine: str | None = None) -> None:
        self._db = db
        self._machine = machine or socket.gethostname()

    @property
    def key(self) -> str:
        return f"{LEGACY_KEY}:{self._machine}"[:_KEY_LEN]

    async def get(self) -> int:
        own = await self._read(self.key)
        if own is not None:
            return own
        legacy = await self._read(LEGACY_KEY)
        if legacy is not None and await self._ran_instances():
            return legacy
        return DEFAULT_COUNT

    async def set(self, count: int) -> None:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, self.key))
        value = {"count": count}
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=self.key, value=value))
        else:
            row.value = value
        await self._db.commit()

    async def _read(self, key: str) -> int | None:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, key))
        count = (row.value or {}).get("count") if row else None
        return count if isinstance(count, int) else None

    async def _ran_instances(self) -> bool:
        """Whether the old shared count was this machine's: SQLite, or a local instance of it is listed."""
        if not shared_database(self._db):
            return True
        rows = await self._db.execute(select(Server.server_id, Server.details).where(Server.is_primary.is_(False)))
        return any(
            ((details or {}).get("machine") or server_id.rsplit(":", 1)[0]) == self._machine
            for server_id, details in rows
        )
