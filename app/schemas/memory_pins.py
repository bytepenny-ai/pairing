"""Admin settings > Inference > Memory pinning: every Matricxon node's memory and pinned models
(services/memory_pins.py; each node's GET /api/node/load, ../matricxon/app/models/pins.py)."""

from typing import Literal

from pydantic import BaseModel, Field


class PinPool(BaseModel):
    """One kind of memory of a node, in bytes; `other` is used by the system and other programs."""

    total: int
    other: int
    device: str | None = None  # the GPU's name (VRAM only)


class PinModel(BaseModel):
    tag: str
    bytes: int
    memory: Literal["ram", "vram"]
    pinned: bool
    state: Literal["loaded", "loading", "failed", "unloaded"]
    attempt: int = 0
    error: str | None = None
    wish: Literal["auto", "ram", "vram"] = "auto"  # a pin's chosen memory (auto: VRAM when it fits)
    expires_in: int | None = None  # seconds until its keep-alive unloads it; None while pinned or unknown


class PinInstalled(BaseModel):
    """A model installed on a node that can be pinned (Matricxon /api/tags; vision projector files left out)."""

    tag: str
    bytes: int  # the file
    ram_bytes: int = 0  # Matricxon's estimate of the memory it needs loaded (0: unknown)
    kind: Literal["chat", "embedding", "rerank"] = "chat"  # only chat models take a model slot
    capabilities: list[str] = []  # e.g. vision, tools, thinking
    family: str = ""
    context_length: int = 0

    @classmethod
    def from_tags(cls, entry: dict) -> "PinInstalled | None":
        """One /api/tags entry; None for what can't load on its own (a vision projector: no capabilities)."""
        caps = list(entry.get("capabilities") or [])
        if not caps:
            return None
        details = entry.get("details") or {}
        kind = "embedding" if "embedding" in caps else "rerank" if "rerank" in caps else "chat"
        return cls(
            tag=entry["name"],
            bytes=int(entry.get("size", 0)),
            ram_bytes=int(float(entry.get("estimated_ram_gb") or 0) * (1 << 30)),
            kind=kind,
            capabilities=[c for c in caps if c not in ("completion", "embedding", "rerank")],
            family=str(details.get("family") or ""),
            context_length=int(details.get("context_length") or 0),
        )


class PinSlots(BaseModel):
    used: int
    max: int


class PinNode(BaseModel):
    id: str
    name: str
    address: str
    status: Literal["up", "down"]
    slots: PinSlots
    ram: PinPool
    vram: PinPool | None = None
    models: list[PinModel] = []
    installed: list[PinInstalled] = []  # what can be pinned on this node
    supported: bool = True  # False: an older Matricxon without pins (update it)
    runs_on: Literal["cpu", "gpu"] = "cpu"  # where its models load unless a pin says otherwise


class PinOverview(BaseModel):
    """`scope`: "single" (one server), "servers" (several, no cluster) or "cluster"."""

    supported: bool  # Matricxon is the active engine
    scope: Literal["single", "servers", "cluster"] = "single"
    nodes: list[PinNode] = []


class PinUnload(BaseModel):
    """Unload one model that is not pinned, now (its keep-alive may be hours)."""

    address: str = Field(min_length=1, max_length=500)
    tag: str = Field(min_length=1, max_length=500)


class PinUpdate(BaseModel):
    """The whole pin list of one node; [] removes every pin."""

    address: str = Field(min_length=1, max_length=500)
    pinned_models: list[str] = Field(default_factory=list, max_length=64)
