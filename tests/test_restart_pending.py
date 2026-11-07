"""A server whose checkout is newer than what it runs (pulled or committed without a restart): Update all restarts it,
and Cluster > Servers names it, instead of "up to date" while its version differs."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.server_coordination import Server
from app.services import server_registry as registry_module
from app.services.rolling_update import RollingUpdate
from app.services.server_registry import ServerRegistry
from app.services.servers_check import ServersCheck
from tests.test_rolling_update import _FakePairing


def _registry(monkeypatch: pytest.MonkeyPatch, running: str, checkout: str, db) -> ServerRegistry:
    monkeypatch.setattr(registry_module, "local_commit", lambda: running)
    registry = ServerRegistry(server_id="a:1", session_factory=async_sessionmaker(db.bind, expire_on_commit=False))
    monkeypatch.setattr(registry_module, "local_commit", lambda: checkout)
    return registry


def test_pending_when_the_checkout_moved_on(monkeypatch: pytest.MonkeyPatch, db) -> None:
    assert _registry(monkeypatch, "60dbeda", "38329b2", db).restart_pending()
    assert not _registry(monkeypatch, "38329b2", "38329b2", db).restart_pending()
    assert not _registry(monkeypatch, "38329b2", None, db).restart_pending()  # not a git checkout


@pytest.mark.asyncio
async def test_the_heartbeat_reports_the_checkout(monkeypatch: pytest.MonkeyPatch, db) -> None:
    registry = _registry(monkeypatch, "60dbeda", "38329b2", db)
    await registry.heartbeat(db, {"machine": "home"})
    row = await db.get(Server, "a:1")
    assert row.git_commit == "60dbeda" and row.details == {"machine": "home", "checkout": "38329b2"}


@pytest.mark.asyncio
async def test_update_all_restarts_a_server_with_nothing_to_pull_but_a_newer_checkout(
    monkeypatch: pytest.MonkeyPatch, db
) -> None:
    registry = _registry(monkeypatch, "60dbeda", "38329b2", db)
    await registry.heartbeat(db)
    pairing = _FakePairing(changed=False)  # git pull brings nothing new
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    rollout = RollingUpdate(registry=registry, pairing_factory=lambda _proxy, **_: pairing, session_factory=factory)
    await rollout.start(db)
    await rollout.leader_step(db)
    await rollout.server_step(db)
    if rollout._task:
        await asyncio.wait_for(asyncio.shield(rollout._task), timeout=5)
    assert pairing.restarted


def test_the_version_check_names_a_server_that_needs_a_restart() -> None:
    same = ServersCheck._versions({"a:1": "2.1.1 38329b2", "b:1": "2.1.1 38329b2"})
    assert same.ok
    stale = ServersCheck._versions({"a:1": "2.1.1 60dbeda", "b:1": "2.1.1 38329b2"}, ["a:1"])
    assert not stale.ok and "not restarted yet: a:1" in stale.detail
    # The same running version everywhere, but one checkout newer: still flagged.
    assert not ServersCheck._versions({"a:1": "2.1.1 60dbeda"}, ["a:1"]).ok
