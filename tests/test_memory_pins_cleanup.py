"""After a model is deleted in a cluster, no node keeps it pinned or loaded (memory_pins_cleanup.py)."""

import json

import httpx
import pytest

from app.routers import settings as settings_router
from app.schemas import PullModelRequest
from app.services import engine_service, matricxon_pool, settings_service
from app.services.memory_pins_cleanup import PinCleanup

TAG = "hf.co/org/gone-GGUF:gone-Q4"
OTHER = "hf.co/org/keep-GGUF:keep-Q4"
EMBED = "hf.co/org/embed-GGUF:Q8_0"
PINNED_AND_LOADED, LOADED, DOWN, VOTER, OLD, REFUSES, SILENT = (
    f"http://{n}:8420" for n in ("pinned", "loaded", "down", "voter", "old", "refuses", "silent")
)


def _load(models: list[str], pins: list[dict] | None) -> dict:
    body = {"active": 0, "models": [{"name": m, "size_bytes": 1, "active": 0} for m in models], "threads": 4}
    return body if pins is None else body | {"pins": pins}


NODES = {
    "pinned": _load(
        [TAG, OTHER],
        [
            {"tag": TAG, "memory": "auto", "state": "loaded"},
            {"tag": OTHER, "memory": "vram", "state": "loaded"},
            {"tag": EMBED, "memory": "ram", "state": "failed"},
        ],
    ),  # fmt: skip
    "loaded": _load([TAG], []),
    "voter": _load([TAG], [{"tag": TAG, "memory": "auto", "state": "loaded"}]),  # must be left alone
    "old": _load([TAG], None),  # an older Matricxon: no pins, unload only
    "refuses": _load([], [{"tag": TAG, "memory": "auto", "state": "loading"}]),
    "silent": _load([], [{"tag": TAG, "memory": "auto", "state": "loading"}]),
}


def _transport(calls: list[tuple[str, str, dict | None]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        body = json.loads(request.content) if request.content else None
        calls.append((host, f"{request.method} {path}", body))
        if host == "down":
            raise httpx.ConnectError("down")
        if path == "/api/node/load":
            return httpx.Response(200, json=NODES[host])
        if path == "/api/runtime-settings":
            if host == "refuses":
                return httpx.Response(409, json={"detail": "no"})
            applied = [] if host == "silent" else ["pinned_models"]
            return httpx.Response(200, json={"applied_now": applied, "applied_next_load": []})
        if path == "/api/generate":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
async def cluster(db, monkeypatch):
    await engine_service.set_active_engine(db, "matricxon")
    config = await settings_service.get_matricxon_server_config(db)
    config.cluster_role = "seed"
    config.voter_hosts = [VOTER]
    await settings_service.set_matricxon_server_config(db, config)
    hosts = [PINNED_AND_LOADED, LOADED, DOWN, VOTER, OLD, REFUSES, SILENT]
    monkeypatch.setattr(matricxon_pool, "get_effective_hosts", lambda: hosts)


@pytest.mark.asyncio
async def test_every_node_drops_the_pin_and_unloads_it(db, cluster) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    problems = await PinCleanup(db, _transport(calls)).after_delete(TAG)

    puts = {h: b for h, c, b in calls if c == "PUT /api/runtime-settings"}
    unloads = sorted(h for h, c, b in calls if c == "POST /api/generate")
    # The other pins stay, each with its memory; a failed one is kept too.
    assert puts["pinned"] == {"pinned_models": [f"{OTHER}|vram", f"{EMBED}|ram"]}
    assert unloads == ["loaded", "old", "pinned"]
    assert all(b == {"model": TAG, "keep_alive": 0} for h, c, b in calls if c == "POST /api/generate")
    assert "voter" not in {h for h, _, _ in calls}  # voter-only nodes never load models
    assert "old" not in puts  # nothing to unpin on an older node
    # Each problem names its node; the others are clean.
    assert len(problems) == 3
    assert any(p.startswith("down:8420 did not answer") for p in problems)
    assert any(p.startswith("refuses:8420: refused to remove the pin") for p in problems)
    assert any(p.startswith("silent:8420: did not confirm") for p in problems)


@pytest.mark.asyncio
async def test_without_a_cluster_or_matricxon_nothing_is_called(db, cluster) -> None:
    calls: list = []
    config = await settings_service.get_matricxon_server_config(db)
    config.cluster_role = "off"  # Matricxon removed its own pin while deleting
    await settings_service.set_matricxon_server_config(db, config)
    assert await PinCleanup(db, _transport(calls)).after_delete(TAG) == [] and calls == []
    await engine_service.set_active_engine(db, "llamacpp")
    assert await PinCleanup(db, _transport(calls)).after_delete(TAG) == [] and calls == []


@pytest.mark.asyncio
async def test_the_delete_route_reports_what_was_not_cleaned(db, monkeypatch) -> None:
    async def deleted(_tag: str) -> None:
        return None

    async def problems(self, tag: str) -> list[str]:
        assert tag == TAG
        return ["down:8420 did not answer"]

    monkeypatch.setattr(settings_router, "delete_model", deleted)
    monkeypatch.setattr(settings_router.PinCleanup, "after_delete", problems)
    result = await settings_router.delete_model_endpoint(PullModelRequest(tag=TAG), db=db, _admin=None)
    assert result.deleted == TAG and result.warnings == ["down:8420 did not answer"]


@pytest.mark.asyncio
async def test_a_failed_delete_cleans_nothing(db, monkeypatch) -> None:
    from app.services.inference_client import InferenceError

    async def fails(_tag: str) -> None:
        raise InferenceError("no quorum")

    async def never(self, tag: str) -> list[str]:
        raise AssertionError("must not run after a failed delete")

    monkeypatch.setattr(settings_router, "delete_model", fails)
    monkeypatch.setattr(settings_router.PinCleanup, "after_delete", never)
    with pytest.raises(Exception, match="no quorum"):
        await settings_router.delete_model_endpoint(PullModelRequest(tag=TAG), db=db, _admin=None)
