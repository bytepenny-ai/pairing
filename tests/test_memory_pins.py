"""Admin settings > Inference > Memory pinning: nodes' reports become the page's data, pins are saved on the node."""

import httpx
import pytest

from app.routers import memory_pins_admin
from app.schemas.memory_pins import PinInstalled
from app.services import engine_service, matricxon_pool, memory_pins, settings_service
from app.services.memory_pins import InstalledModels, MemoryPinsError, MemoryPinsService

GB = 1 << 30
A, B = "http://a:8420", "http://b:8420"


def _load(models: list[dict], pins: list[dict], gpu: dict | None = None) -> dict:
    return {
        "active": 0, "models": models, "threads": 8, "free_memory_bytes": 20 * GB, "node_kind": "compute",
        "total_memory_bytes": 32 * GB, "gpu": gpu, "max_loaded_models": 3, "pins": pins,
    }  # fmt: skip


_TAGS = {"qwen": "qwen3:8b", "big": "big:70b", "embed": "embed", "p": "p"}


def _inst(**sizes: int) -> list[PinInstalled]:
    return [PinInstalled(tag=_TAGS[k], bytes=v) for k, v in sizes.items()]


def test_a_node_report_becomes_the_page_record() -> None:
    models = [
        {"name": "qwen3:8b", "size_bytes": 5 * GB, "active": 0, "pinned": True, "memory": "ram", "counted": True},
        {"name": "embed", "size_bytes": GB, "active": 0, "pinned": False, "memory": "ram", "counted": False},
    ]
    pins = [
        {"tag": "qwen3:8b", "state": "loaded", "attempt": 1, "error": None},
        {"tag": "big:70b", "state": "failed", "attempt": 3, "error": "not enough memory"},
    ]
    node = MemoryPinsService.node_from(A, _load(models, pins), _inst(qwen=5 * GB, big=40 * GB, embed=GB))
    assert (node.status, node.slots.used, node.slots.max, node.supported) == ("up", 1, 3, True)
    assert node.ram.total == 32 * GB and node.ram.other == 32 * GB - 20 * GB - 6 * GB and node.vram is None
    got = [(m.tag, m.pinned, m.state, m.bytes) for m in node.models]
    assert got == [
        ("qwen3:8b", True, "loaded", 5 * GB),
        ("embed", False, "loaded", GB),
        ("big:70b", True, "failed", 40 * GB),
    ]
    assert node.models[-1].error == "not enough memory" and [m.tag for m in node.installed] == [
        "qwen3:8b",
        "big:70b",
        "embed",
    ]


def test_a_gpu_node_reports_vram_and_an_unloaded_pin() -> None:
    gpu = {"name": "NVIDIA RTX 4070", "total_bytes": 12 * GB, "free_bytes": 4 * GB}
    models = [{"name": "m", "size_bytes": 7 * GB, "active": 0, "pinned": False, "memory": "vram"}]
    pins = [{"tag": "p", "state": "unloaded", "attempt": 1, "error": None}]
    node = MemoryPinsService.node_from(A, _load(models, pins, gpu), _inst(p=2 * GB))
    assert node.vram.total == 12 * GB and node.vram.other == GB and node.vram.device == "NVIDIA RTX 4070"
    assert [(m.tag, m.memory, m.state) for m in node.models] == [("m", "vram", "loaded"), ("p", "vram", "unloaded")]


def test_an_older_matricxon_is_marked() -> None:
    body = _load([], [])
    del body["pins"]
    assert MemoryPinsService.node_from(A, body, []).supported is False


def _transport(seen: list[tuple[str, str, bytes]], refuse: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, f"{request.url.host}{request.url.path}", request.content))
        if request.url.host == "b":
            raise httpx.ConnectError("down")
        if request.url.path == "/api/runtime-settings":
            if refuse:
                return httpx.Response(409, json={"detail": "3 chat models pinned, but this node keeps at most 2"})
            return httpx.Response(200, json={"applied_now": ["pinned_models"], "applied_next_load": []})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3:8b", "size": 5 * GB, "capabilities": ["completion"]}]}
            )
        pins = [{"tag": "qwen3:8b", "state": "loading", "attempt": 0, "error": None}]
        return httpx.Response(200, json=_load([], pins))

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _fresh_installed_cache(monkeypatch):
    monkeypatch.setattr(memory_pins, "_installed", InstalledModels())


@pytest.fixture
async def matricxon(db, monkeypatch):
    await engine_service.set_active_engine(db, "matricxon")
    monkeypatch.setattr(matricxon_pool, "get_effective_hosts", lambda: [A, B])


@pytest.mark.asyncio
async def test_the_overview_reads_every_node_and_marks_a_silent_one_down(db, matricxon) -> None:
    overview = await MemoryPinsService(db, _transport([])).overview()
    assert overview.supported and overview.scope == "servers"
    assert [(n.name, n.status) for n in overview.nodes] == [("a:8420", "up"), ("b:8420", "down")]
    assert overview.nodes[0].models[0].state == "loading"


@pytest.mark.asyncio
async def test_saving_sends_the_whole_list_to_that_node(db, matricxon) -> None:
    seen: list[tuple[str, str, bytes]] = []
    node = await MemoryPinsService(db, _transport(seen)).set_pins(A, ["qwen3:8b", " qwen3:8b", ""])
    assert ("PUT", "a/api/runtime-settings", b'{"pinned_models":["qwen3:8b"]}') in seen
    assert node.id == A


@pytest.mark.asyncio
async def test_a_refusal_carries_the_nodes_reason_and_unknown_nodes_are_404(db, matricxon) -> None:
    with pytest.raises(MemoryPinsError, match="at most 2") as refused:
        await MemoryPinsService(db, _transport([], refuse=True)).set_pins(A, ["x", "y", "z"])
    assert refused.value.status == 409
    with pytest.raises(MemoryPinsError) as unknown:
        await MemoryPinsService(db, _transport([])).set_pins("http://elsewhere:8420", [])
    assert unknown.value.status == 404


@pytest.mark.asyncio
async def test_without_matricxon_the_page_says_so(db) -> None:
    await engine_service.set_active_engine(db, "llamacpp")
    assert (await memory_pins_admin.get_memory_pins(db=db, _admin=None)).supported is False


@pytest.mark.asyncio
async def test_a_cluster_is_shown_as_one(db, matricxon) -> None:
    config = await settings_service.get_matricxon_server_config(db)
    config.cluster_role = "seed"
    await settings_service.set_matricxon_server_config(db, config)
    assert (await MemoryPinsService(db, _transport([])).overview()).scope == "cluster"


@pytest.mark.asyncio
async def test_installed_models_are_read_once_a_minute_and_a_failed_read_keeps_the_last() -> None:
    now = [0.0]
    calls: list[str] = []
    fail = [False]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if fail[0]:
            return httpx.Response(500)
        return httpx.Response(200, json={"models": [{"name": "m", "size": GB, "capabilities": ["completion"]}]})

    cache = InstalledModels(ttl=60, clock=lambda: now[0])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert [m.tag for m in await cache.read(client, A)] == ["m"]
        now[0] = 30
        assert len(await cache.read(client, A)) == 1 and len(calls) == 1
        now[0], fail[0] = 61, True
        assert len(await cache.read(client, A)) == 1 and len(calls) == 2


def test_each_pin_keeps_its_memory_choice() -> None:
    gpu = {"name": "NVIDIA A100", "total_bytes": 80 * GB, "free_bytes": 70 * GB}
    models = [{"name": "chat", "size_bytes": 5 * GB, "active": 0, "pinned": True, "memory": "ram"}]
    pins = [
        {"tag": "chat", "memory": "ram", "state": "loaded", "attempt": 1, "error": None},
        {"tag": "auto", "memory": "auto", "state": "loading", "attempt": 0, "error": None},
    ]
    body = _load(models, pins, gpu) | {"runs_on": "cpu"}  # a CPU server that also has a GPU
    node = MemoryPinsService.node_from(A, body, [PinInstalled(tag="auto", bytes=GB)])
    assert node.runs_on == "cpu"
    assert [(m.tag, m.wish, m.memory) for m in node.models] == [("chat", "ram", "ram"), ("auto", "auto", "ram")]


def test_tags_entries_become_pinnable_models() -> None:
    gemma = {
        "name": "hf.co/u/g:Q4",
        "size": 3 * GB,
        "estimated_ram_gb": 3.5,
        "capabilities": ["completion", "tools", "thinking"],
        "details": {"family": "gemma4", "context_length": 131072},
    }
    model = PinInstalled.from_tags(gemma)
    assert (model.kind, model.capabilities, model.family, model.context_length) == (
        "chat",
        ["tools", "thinking"],
        "gemma4",
        131072,
    )
    assert model.ram_bytes == int(3.5 * GB)
    assert PinInstalled.from_tags({"name": "e", "size": 1, "capabilities": ["embedding"]}).kind == "embedding"
    assert PinInstalled.from_tags({"name": "r", "size": 1, "capabilities": ["rerank"]}).kind == "rerank"
    assert PinInstalled.from_tags({"name": "mmproj", "size": 1, "capabilities": []}) is None  # a vision projector


def _answer(status: int, body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/runtime-settings":
            return httpx.Response(status, json=body)
        return httpx.Response(200, json=_load([], []) if request.url.path == "/api/node/load" else {"models": []})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_an_older_matricxon_that_ignores_pins_is_not_called_saved(db, matricxon) -> None:
    old = _answer(200, {"applied_now": [], "applied_next_load": []})  # it dropped the unknown field
    with pytest.raises(MemoryPinsError, match="no memory pinning yet"):
        await MemoryPinsService(db, old).set_pins(A, ["qwen3:8b"])


@pytest.mark.asyncio
async def test_a_422_shows_the_nodes_own_reasons(db, matricxon) -> None:
    invalid = _answer(422, {"detail": [{"msg": "List should have at most 64 items"}]})
    with pytest.raises(MemoryPinsError, match="at most 64 items"):
        await MemoryPinsService(db, invalid).set_pins(A, ["x"])


@pytest.mark.asyncio
async def test_no_saving_while_the_engine_is_not_matricxon(db, matricxon) -> None:
    await engine_service.set_active_engine(db, "llamacpp")
    with pytest.raises(MemoryPinsError, match="only when the engine is Matricxon"):
        await MemoryPinsService(db, _transport([])).set_pins(A, ["qwen3:8b"])


def _node_with(models: list[dict], pins: list[dict], seen: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if request.url.path == "/api/node/load":
            return httpx.Response(200, json=_load(models, pins))
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"models": []})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_unload_frees_a_model_loaded_on_demand(db, matricxon) -> None:
    seen: list = []
    loaded = [{"name": "embed", "size_bytes": GB, "active": 0, "pinned": False, "expires_in_seconds": 86000}]
    await MemoryPinsService(db, _node_with(loaded, [], seen)).unload(A, "embed")
    assert ("POST", "/api/generate", b'{"model":"embed","keep_alive":0}') in seen


@pytest.mark.asyncio
async def test_unload_refuses_a_pinned_model_and_skips_one_not_loaded(db, matricxon) -> None:
    seen: list = []
    pinned = [{"name": "chat", "size_bytes": GB, "active": 0, "pinned": True}]
    with pytest.raises(MemoryPinsError, match="unpin it first"):
        await MemoryPinsService(db, _node_with(pinned, [{"tag": "chat", "state": "loaded"}], seen)).unload(A, "chat")
    await MemoryPinsService(db, _node_with([], [], seen)).unload(A, "gone")
    assert not any(path == "/api/generate" for _, path, _ in seen)


def test_the_page_gets_when_a_model_unloads() -> None:
    loaded = [{"name": "embed", "size_bytes": GB, "active": 0, "pinned": False, "expires_in_seconds": 3600}]
    node = MemoryPinsService.node_from(A, _load(loaded, []), [])
    assert node.models[0].expires_in == 3600
