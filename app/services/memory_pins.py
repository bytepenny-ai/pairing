"""Admin settings > Inference > Memory pinning: each Matricxon node's memory and pins, read from its
GET /api/node/load and /api/tags, and pins saved on the node itself (PUT /api/runtime-settings, kept
in its .env), so every pAIring server sees the same pins. Matricxon side: ../matricxon/app/models/pins.py.
"""

import asyncio
import time
from collections.abc import Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.memory_pins import PinInstalled, PinModel, PinNode, PinOverview, PinPool, PinSlots
from app.services import engine_service, matricxon_http, matricxon_pool, settings_service
from app.services.cluster_map_consensus import short_address

_TIMEOUT = httpx.Timeout(3.0, connect=1.5)
# A node checks pins against its models folder, slow on a busy disk (seen: 37 s while a pin loads).
_SAVE_TIMEOUT = httpx.Timeout(120.0, connect=1.5)
_FANOUT = 32  # nodes read at once


class InstalledModels:
    """Each node's installed models (from /api/tags), kept for `ttl` seconds: they change rarely, and the page reads
    every node every few seconds. A failed read keeps the last list."""

    def __init__(self, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._clock = clock
        self._seen: dict[str, tuple[float, list[PinInstalled]]] = {}

    async def read(self, client: httpx.AsyncClient, host: str) -> list[PinInstalled]:
        at, models = self._seen.get(host, (-1e9, []))
        if self._clock() - at < self._ttl:
            return models
        try:
            resp = await client.get(f"{host}/api/tags")
            resp.raise_for_status()
            read = [PinInstalled.from_tags(m) for m in resp.json().get("models", [])]
            models = sorted((m for m in read if m is not None), key=lambda m: m.tag)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return models
        self._seen[host] = (self._clock(), models)
        return models

    def forget(self, host: str) -> None:
        self._seen.pop(host, None)


_installed = InstalledModels()


def pin_name(tag: str) -> str:
    """The model's file part, for messages: "hf.co/org/x-GGUF:x-Q4" -> "x-Q4"."""
    return tag.rsplit(":", 1)[-1] if tag.startswith("hf.co/") else tag


class MemoryPinsError(Exception):
    """A pin change the node refused, or a node pAIring doesn't know; `status` for the HTTP answer."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class MemoryPinsService:
    def __init__(self, db: AsyncSession, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._db = db
        self._transport = transport

    async def _hosts(self) -> tuple[list[str], str]:
        config = await settings_service.get_matricxon_server_config(self._db)
        hosts = [h for h in matricxon_pool.get_effective_hosts() if h not in config.voter_hosts]
        scope = "cluster" if config.cluster_role != "off" else "single" if len(hosts) < 2 else "servers"
        return hosts, scope

    async def overview(self) -> PinOverview:
        if await engine_service.get_active_engine(self._db) != "matricxon":
            return PinOverview(supported=False)
        hosts, scope = await self._hosts()
        gate = asyncio.Semaphore(_FANOUT)
        async with matricxon_http.client(timeout=_TIMEOUT, transport=self._transport) as client:
            nodes = await asyncio.gather(*(self._node(client, gate, host) for host in hosts))
        return PinOverview(supported=True, scope=scope, nodes=list(nodes))

    async def set_pins(self, address: str, tags: list[str]) -> PinNode:
        """Saves one node's pin list on the node; its refusal (too many chat models, not installed) is
        raised as MemoryPinsError with the node's own words."""
        if await engine_service.get_active_engine(self._db) != "matricxon":
            raise MemoryPinsError("memory pinning works only when the engine is Matricxon")
        hosts, _scope = await self._hosts()
        if address not in hosts:
            raise MemoryPinsError(f"{address} is not one of this pAIring's Matricxon servers", status=404)
        wanted = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        async with matricxon_http.client(timeout=_SAVE_TIMEOUT, transport=self._transport) as client:
            try:
                resp = await client.put(f"{address}/api/runtime-settings", json={"pinned_models": wanted})
            except httpx.HTTPError as exc:
                raise MemoryPinsError(f"could not reach {short_address(address)}: {exc}", status=502) from exc
            if resp.status_code >= 400:
                detail = self._detail(resp)
                raise MemoryPinsError(f"{short_address(address)} refused the pins: {detail}")
            # An older Matricxon ignores the field it doesn't know and answers 200: nothing was pinned.
            if "pinned_models" not in self._applied(resp):
                raise MemoryPinsError(f"{short_address(address)} has no memory pinning yet: update its Matricxon first")
            return await self._node(client, asyncio.Semaphore(1), address)

    async def unload(self, address: str, tag: str) -> PinNode:
        """Unloads a model that is not pinned on that node (a reply using it now is stopped, as Matricxon's unload
        request does). A pinned one is refused: unpin it first, or it would just load again."""
        if await engine_service.get_active_engine(self._db) != "matricxon":
            raise MemoryPinsError("memory pinning works only when the engine is Matricxon")
        hosts, _scope = await self._hosts()
        if address not in hosts:
            raise MemoryPinsError(f"{address} is not one of this pAIring's Matricxon servers", status=404)
        name = short_address(address)
        async with matricxon_http.client(timeout=_SAVE_TIMEOUT, transport=self._transport) as client:
            try:
                load = (await client.get(f"{address}/api/node/load")).json()
                if any(p.get("tag") == tag for p in load.get("pins", [])):
                    raise MemoryPinsError(f"{pin_name(tag)} is pinned on {name}: unpin it first")
                if any(m.get("name") == tag for m in load.get("models", [])):
                    resp = await client.post(f"{address}/api/generate", json={"model": tag, "keep_alive": 0})
                    if resp.status_code >= 400:
                        raise MemoryPinsError(f"{name} could not unload it: {self._detail(resp)}")
            except (httpx.HTTPError, ValueError) as exc:
                raise MemoryPinsError(f"could not reach {name}: {exc}", status=502) from exc
            return await self._node(client, asyncio.Semaphore(1), address)

    @staticmethod
    def _applied(resp: httpx.Response) -> list[str]:
        try:
            return list(resp.json().get("applied_now") or [])
        except (ValueError, AttributeError):
            return []

    @staticmethod
    def _detail(resp: httpx.Response) -> str:
        """The node's reason; a 422's list of field errors becomes their messages."""
        try:
            detail = resp.json().get("detail")
        except (ValueError, AttributeError):
            return resp.text[:200]
        if isinstance(detail, list):
            return "; ".join(str(e.get("msg", e)) if isinstance(e, dict) else str(e) for e in detail)[:300]
        return str(detail or resp.text[:200])

    async def _node(self, client: httpx.AsyncClient, gate: asyncio.Semaphore, host: str) -> PinNode:
        """Down only when /api/node/load fails; the installed list (slower) is read at most every INSTALLED_TTL."""
        async with gate:
            try:
                load = await client.get(f"{host}/api/node/load")
                load.raise_for_status()
                body = load.json()
            except (httpx.HTTPError, ValueError):
                return PinNode(
                    id=host, name=short_address(host), address=host, status="down",
                    slots=PinSlots(used=0, max=0), ram=PinPool(total=0, other=0),
                )  # fmt: skip
            installed = await _installed.read(client, host)
        return self.node_from(host, body, installed)

    @staticmethod
    def node_from(host: str, body: dict, installed: list[PinInstalled]) -> PinNode:
        """One node from its /api/node/load answer and its installed models."""
        sizes = {m.tag: m.bytes for m in installed}
        loaded = body.get("models", [])
        pins = {p["tag"]: p for p in body.get("pins", [])}
        models = [
            PinModel(
                tag=m["name"],
                bytes=int(m.get("size_bytes", 0)),
                memory=m.get("memory", "ram"),
                pinned=bool(m.get("pinned")),
                state="loaded",
                wish=pins.get(m["name"], {}).get("memory", "auto"),
                expires_in=m.get("expires_in_seconds"),
            )  # fmt: skip
            for m in loaded
        ]
        held = {m.tag for m in models}
        gpu = body.get("gpu")
        runs_on = body.get("runs_on", "gpu" if gpu else "cpu")
        for tag, pin in pins.items():
            if pin["state"] != "loaded" or tag not in held:
                state = "unloaded" if pin["state"] == "loaded" else pin["state"]
                attempt, error = int(pin.get("attempt", 0)), pin.get("error")
                wish = pin.get("memory", "auto")
                # Where it will load: its wish, or (auto) the server's own device.
                where = {"ram": "ram", "vram": "vram"}.get(wish, "vram" if runs_on == "gpu" else "ram")
                models.append(
                    PinModel(
                        tag=tag,
                        bytes=sizes.get(tag, 0),
                        memory=where,
                        pinned=True,
                        state=state,
                        attempt=attempt,
                        error=error,
                        wish=wish,
                    )  # fmt: skip
                )
        used = {"ram": 0, "vram": 0}
        for m in loaded:
            used[m.get("memory", "ram")] += int(m.get("size_bytes", 0))
        total = int(body.get("total_memory_bytes") or 0)
        free = body.get("free_memory_bytes")
        ram = PinPool(total=total, other=max(0, total - int(free) - used["ram"]) if free is not None else 0)
        vram = None
        if gpu:
            vram = PinPool(total=int(gpu["total_bytes"]), device=gpu.get("name"),
                           other=max(0, int(gpu["total_bytes"]) - int(gpu["free_bytes"]) - used["vram"]))  # fmt: skip
        return PinNode(
            id=host,
            name=short_address(host),
            address=host,
            status="up",
            slots=PinSlots(
                used=sum(1 for m in loaded if m.get("counted", True)), max=int(body.get("max_loaded_models", 0))
            ),
            ram=ram,
            vram=vram,
            models=models,
            installed=installed,
            supported="pins" in body,
            runs_on=runs_on,
        )
