"""image_gen_ring.py: image generation is off while more than one machine runs pAIring on a shared database."""

import time

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.server_coordination import Server
from app.routers import image_gen_guard
from app.schemas import SdCppStatus
from app.services import image_gen_ring as ring_module
from app.services.image_gen_ring import REASON, ImageGenOffError, ImageGenRing
from app.services.server_registry import ServerRegistry


def _ring(db: AsyncSession, shared: bool = True) -> ImageGenRing:
    registry = ServerRegistry(server_id="a:8000", session_factory=async_sessionmaker(db.bind, expire_on_commit=False))
    return ImageGenRing(registry=registry, shared=lambda _db: shared)


async def _servers(db: AsyncSession, *rows: tuple[str, bool, bool]) -> None:
    """(server_id, is_primary, online)"""
    now = int(time.time())
    for server_id, primary, online in rows:
        db.add(Server(server_id=server_id, version="1", is_primary=primary, last_seen=now if online else 0))
    await db.commit()


@pytest.mark.asyncio
async def test_two_machines_online_turn_it_off(db):
    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, True))
    assert await _ring(db).is_off(db)
    with pytest.raises(ImageGenOffError):
        await _ring(db).require_on(db)


@pytest.mark.asyncio
async def test_local_instances_of_one_machine_are_one_server(db):
    await _servers(db, ("home:8000", True, True), ("home:8001", False, True))
    assert not await _ring(db).is_off(db)


@pytest.mark.asyncio
async def test_an_offline_server_does_not_count(db):
    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, False))
    assert not await _ring(db).is_off(db)


@pytest.mark.asyncio
async def test_sqlite_is_never_a_ring(db):
    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, True))
    assert not await _ring(db, shared=False).is_off(db)


@pytest.mark.asyncio
async def test_enforce_stops_a_running_engine_only_in_a_ring_and_only_on_a_primary(db, monkeypatch):
    stopped = []

    async def status(_db):
        return SdCppStatus(running=True, installed=True)

    async def stop(_db):
        stopped.append(True)

    monkeypatch.setattr(ring_module.sdcpp_service, "get_status", status)
    monkeypatch.setattr(ring_module.sdcpp_service, "stop", stop)
    await _servers(db, ("home:8000", True, True))
    assert not await _ring(db).enforce(db, is_primary=True)  # one machine: left alone
    await _servers(db, ("bp-1:8000", True, True))
    assert not await _ring(db).enforce(db, is_primary=False)  # an instance never manages it
    assert await _ring(db).enforce(db, is_primary=True)
    assert stopped == [True]


@pytest.mark.asyncio
async def test_enforce_leaves_a_stopped_engine_alone(db, monkeypatch):
    async def status(_db):
        return SdCppStatus(running=False, installed=True)

    monkeypatch.setattr(ring_module.sdcpp_service, "get_status", status)
    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, True))
    assert not await _ring(db).enforce(db, is_primary=True)


@pytest.mark.asyncio
async def test_the_guard_refuses_with_409_and_the_reason(db, monkeypatch):
    async def off(_db):
        return True

    monkeypatch.setattr(image_gen_guard.image_gen_ring, "is_off", off)
    with pytest.raises(HTTPException) as exc:
        await image_gen_guard.image_gen_on(db=db)
    assert exc.value.status_code == 409 and exc.value.detail == REASON


async def _remote_mode(db: AsyncSession) -> None:
    from app.schemas import SdCppConfig
    from app.services import image_engine_service

    await image_engine_service.set_sdcpp_config(db, SdCppConfig(mode="remote", remote_hosts=["http://10.0.0.9:8189"]))


@pytest.mark.asyncio
async def test_remote_mode_turns_it_back_on_in_a_ring(db):
    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, True))
    assert await _ring(db).is_off(db)  # local mode (the default)
    await _remote_mode(db)
    assert await _ring(db).in_ring(db) and not await _ring(db).is_off(db)


@pytest.mark.asyncio
async def test_in_a_ring_the_local_engine_stops_even_in_remote_mode(db, monkeypatch):
    stopped = []

    async def status(_db):
        return SdCppStatus(running=True, installed=True)

    async def stop(_db):
        stopped.append(True)

    monkeypatch.setattr(ring_module.sdcpp_service, "get_status", status)
    monkeypatch.setattr(ring_module.sdcpp_service, "stop", stop)
    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, True))
    await _remote_mode(db)
    assert await _ring(db).enforce(db, is_primary=True) and stopped == [True]


@pytest.mark.asyncio
async def test_local_actions_are_refused_only_in_a_ring(db, monkeypatch):
    async def ring(_db):
        return True

    await image_gen_guard.no_local_in_ring(db=db)  # one server: allowed
    monkeypatch.setattr(image_gen_guard.image_gen_ring, "in_ring", ring)
    with pytest.raises(HTTPException) as exc:
        await image_gen_guard.no_local_in_ring(db=db)
    assert exc.value.status_code == 409 and exc.value.detail == ring_module.LOCAL_REFUSED


@pytest.mark.asyncio
async def test_removing_the_last_remote_server_saves_and_turns_it_off(db, monkeypatch):
    """Remote with no servers is stored as local (SdCppConfig): in a ring that is "off", and saving it is allowed."""
    from app.routers import sdcpp_admin
    from app.schemas import SdCppConfig

    async def ring(_db):
        return True

    async def saved(_db, body):
        stored.append(body)

    stored = []
    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, True))
    monkeypatch.setattr(sdcpp_admin.image_gen_ring, "in_ring", ring)
    monkeypatch.setattr(sdcpp_admin, "_save_and_broadcast", saved)
    await sdcpp_admin.apply_config(SdCppConfig(mode="remote", remote_hosts=[]), db=db, _admin=None)
    assert stored and stored[0].mode == "local"


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1:8189", True),
        ("http://localhost:8189", True),
        ("http://[::1]:8189", True),
        ("0.0.0.0:8189", True),
        ("http://192.168.122.1:8189", False),
        ("sd.example.com:8189", False),
    ],
)
def test_loopback_addresses(host: str, loopback: bool) -> None:
    assert ring_module.is_loopback(host) is loopback


@pytest.mark.asyncio
async def test_a_localhost_remote_server_is_off_in_a_ring_and_refused_on_save(db, monkeypatch):
    from app.schemas import SdCppConfig
    from app.services import image_engine_service

    await _servers(db, ("home:8000", True, True), ("bp-1:8000", True, True))
    await image_engine_service.set_sdcpp_config(db, SdCppConfig(mode="remote", remote_hosts=["127.0.0.1:8189"]))
    assert await _ring(db).is_off(db)  # each server's own machine: not shared

    async def ring(_db):
        return True

    monkeypatch.setattr(image_gen_guard.image_gen_ring, "in_ring", ring)
    with pytest.raises(HTTPException) as exc:
        await image_gen_guard.refuse_loopback_in_ring(db, "remote", ["http://localhost:8189"])
    assert exc.value.status_code == 409 and exc.value.detail == ring_module.LOOPBACK_REFUSED
    await image_gen_guard.refuse_loopback_in_ring(db, "remote", ["http://192.168.122.1:8189"])  # allowed


def test_admins_get_the_fix_and_users_a_short_note() -> None:
    assert ring_module.off_reason(True) == REASON
    assert ring_module.off_reason(False) == ring_module.USER_REASON


@pytest.mark.asyncio
@pytest.mark.parametrize(("in_ring", "off"), [(False, False), (True, False), (True, True)])
async def test_engine_status_carries_both_ring_texts(db, monkeypatch, in_ring: bool, off: bool):
    """The engine page shows status.off_reason or status.ring_note; neither text lives in settings.js."""
    from pathlib import Path

    from app.routers import sdcpp_admin

    async def status(_db):
        return SdCppStatus(running=False)

    async def ring(_db):
        return in_ring

    async def is_off(_db):
        return off

    monkeypatch.setattr(sdcpp_admin.sdcpp_service, "get_status", status)
    monkeypatch.setattr(sdcpp_admin.image_gen_ring, "in_ring", ring)
    monkeypatch.setattr(sdcpp_admin.image_gen_ring, "is_off", is_off)
    got = await sdcpp_admin.get_status(db=db, _admin=None)
    assert got.off_reason == (REASON if off else None)
    assert got.ring_note == (ring_module.REMOTE_NOTE if in_ring and not off else None)
    js = (Path(__file__).parent.parent / "app" / "static" / "js" / "settings.js").read_text()
    assert "Remote mode only" not in js and "status.ring_note" in js
