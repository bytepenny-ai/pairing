"""Image generation in a "ring": more than one machine running pAIring on a shared database.

Its engine, stable-diffusion.cpp, in local mode runs one sd-server per machine with machine-local paths kept in
the shared settings, which does not follow the multi-server rules. So in a ring only remote mode is allowed: one
stable-diffusion.cpp server that every pAIring uses (the settings are shared, so one admin setting it covers all).
- Local mode in a ring: image generation is off on every server (pages show the link as Off, requests refused).
- Remote mode in a ring: on everywhere.
Either way, in a ring the heartbeat stops this machine's local sd-server (never uninstalls it), and starting or
installing one is refused. Saving is allowed: Remote with servers turns it on, none (saved as local) off. Local
instances on one machine are one server.
"""

import ipaddress
import logging
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import IS_PRIMARY
from app.services import image_engine_service, sdcpp_service
from app.services.db_clock import shared_database
from app.services.server_registry import ServerRegistry, server_registry

logger = logging.getLogger("llama_chat")

REASON = (
    "Image generation is off: more than one pAIring server shares this database, and there its engine "
    "(stable-diffusion.cpp) runs only in remote mode, on a server every pAIring reaches (not localhost). An admin "
    "sets it in Admin settings > Inference > Engine."
)
# What users who are not admins see: they cannot change the engine.
USER_REASON = "Image generation is off for now, ask your admin."
# The engine page in a ring while remote mode is set (image generation on).
REMOTE_NOTE = (
    "More than one pAIring server shares this database: Remote mode only, and every server uses this remote "
    "image server."
)


def off_reason(is_admin: bool) -> str:
    """Why image generation is off: how to fix it for an admin, a short note for everyone else."""
    return REASON if is_admin else USER_REASON


LOCAL_REFUSED = (
    "More than one pAIring server shares this database: the image engine runs only in remote mode here "
    "(a stable-diffusion.cpp server every pAIring uses), not locally on one of them."
)


LOOPBACK_REFUSED = (
    "More than one pAIring server shares this database: a remote image server must be an address every pAIring "
    "server reaches. localhost / 127.0.0.1 means each server's own machine."
)


def is_loopback(host: str) -> bool:
    """localhost, 127.x, ::1 or 0.0.0.0: a different machine for every server that reads it."""
    name = (urlsplit(host if "//" in host else "//" + host).hostname or "").lower()
    if name in ("localhost", ""):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return name.endswith(".localhost")
    return address.is_loopback or address.is_unspecified


class ImageGenOffError(Exception):
    """A refused image action while the ring is on (shown with REASON)."""

    def __init__(self) -> None:
        super().__init__(REASON)


class ImageGenRing:
    def __init__(self, registry: ServerRegistry = server_registry, shared=shared_database) -> None:
        self._registry = registry
        self._shared = shared

    async def in_ring(self, db: AsyncSession) -> bool:
        """More than one machine has an online pAIring server on this (shared) database."""
        if not self._shared(db):
            return False
        rows, now = await self._registry.servers(db)
        machines = {self._registry.machine_of(r) for r in rows if r.is_primary and self._registry.online(r, now)}
        return len(machines) > 1

    async def is_off(self, db: AsyncSession) -> bool:
        """In a ring, image generation is off everywhere unless Remote names a server every pAIring reaches (local
        mode, or only localhost addresses: off)."""
        if not await self.in_ring(db):
            return False
        config = await image_engine_service.get_sdcpp_config(db)
        return config.mode != "remote" or all(is_loopback(h) for h in config.remote_hosts)

    async def require_on(self, db: AsyncSession) -> None:
        if await self.is_off(db):
            raise ImageGenOffError()

    async def enforce(self, db: AsyncSession, is_primary: bool = IS_PRIMARY) -> bool:
        """On a primary in a ring: stops its local sd-server if running (installed files stay). True when stopped."""
        if not is_primary or not await self.in_ring(db):
            return False
        if not (await sdcpp_service.get_status(db)).running:
            return False
        await sdcpp_service.stop(db)
        logger.warning("Stopped the local image engine: %s", LOCAL_REFUSED)
        return True


image_gen_ring = ImageGenRing()
