"""After a model is deleted in a Matricxon cluster: no node keeps it pinned or loaded.

The models folder is shared, so one node deletes the files (matricxon_admin.delete_model) and removes its own pin.
The other nodes would keep a pinned copy in memory (their open file stays readable) and keep getting chats for it,
then fail the pin at their next start. So every node is read, the pin removed where it is (the rest of its pins
kept, each with its memory), and the model unloaded where it is loaded. A node that can't be reached or refuses is
named in the result; the delete itself stays done.
"""

import asyncio

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import engine_service, matricxon_http, matricxon_pool, settings_service
from app.services.cluster_map_consensus import short_address

_TIMEOUT = httpx.Timeout(120.0, connect=2.0)  # a node checks pins against its models folder: slow on a busy disk
_FANOUT = 16


class PinCleanup:
    def __init__(self, db: AsyncSession, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._db = db
        self._transport = transport

    async def after_delete(self, tag: str) -> list[str]:
        """Cleans every cluster node; returns what could not be done ([] when all went well, or no cluster)."""
        if await engine_service.get_active_engine(self._db) != "matricxon":
            return []
        config = await settings_service.get_matricxon_server_config(self._db)
        if config.cluster_role == "off":
            return []  # one server, or separate ones with their own folders: Matricxon removed its own pin
        hosts = [h for h in matricxon_pool.get_effective_hosts() if h not in config.voter_hosts]
        gate = asyncio.Semaphore(_FANOUT)
        async with matricxon_http.client(timeout=_TIMEOUT, transport=self._transport) as client:
            results = await asyncio.gather(*(self._clean(client, gate, host, tag) for host in hosts))
        return [problem for problem in results if problem]

    async def _clean(self, client: httpx.AsyncClient, gate: asyncio.Semaphore, host: str, tag: str) -> str | None:
        name = short_address(host)
        async with gate:
            try:
                resp = await client.get(f"{host}/api/node/load")
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                return f"{name} did not answer ({type(exc).__name__}): if it pins the model, remove the pin there"
            try:
                problem = await self._unpin(client, host, tag, body.get("pins"))
                if problem:
                    return f"{name}: {problem}"
                if any(m.get("name") == tag for m in body.get("models", [])):
                    resp = await client.post(f"{host}/api/generate", json={"model": tag, "keep_alive": 0})
                    if resp.status_code >= 400:
                        return f"{name} could not unload it ({resp.status_code})"
            except (httpx.HTTPError, ValueError) as exc:
                return f"{name} stopped answering ({type(exc).__name__}): check its pins there"
        return None

    @staticmethod
    async def _unpin(client: httpx.AsyncClient, host: str, tag: str, pins: list[dict] | None) -> str | None:
        """Saves the node's pins without `tag`; None when done or nothing to do (an older node has no pins)."""
        if not pins or not any(p.get("tag") == tag for p in pins):
            return None
        kept = [
            p["tag"] if p.get("memory", "auto") == "auto" else f"{p['tag']}|{p['memory']}"
            for p in pins
            if p.get("tag") != tag
        ]
        resp = await client.put(f"{host}/api/runtime-settings", json={"pinned_models": kept})
        if resp.status_code >= 400:
            return f"refused to remove the pin ({resp.status_code}): remove it on its Memory pinning panel"
        if "pinned_models" not in (resp.json().get("applied_now") or []):
            return "did not confirm removing the pin: check its Memory pinning panel"
        return None
