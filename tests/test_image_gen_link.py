"""image_gen_link.py: the sidebar's Images Gen link shows only while an image engine can take a job."""

import pytest

from app.schemas.sdcpp_config import SdCppConfig
from app.services import image_gen_link as link_module
from app.services.image_gen_link import ImageGenLink


def _setup(monkeypatch, config: SdCppConfig, tracked: dict | None = None, alive: bool = False, off: bool = False):
    async def get_config(_db):
        return config

    async def is_off(_db):
        return off

    monkeypatch.setattr(link_module.image_engine_service, "get_sdcpp_config", get_config)
    monkeypatch.setattr(link_module.image_gen_ring, "is_off", is_off)
    monkeypatch.setattr(link_module.sdcpp_process, "read_tracking", lambda: tracked)
    monkeypatch.setattr(link_module.sdcpp_process, "is_alive", lambda pid, path: alive)


@pytest.mark.asyncio
async def test_hidden_when_local_engine_not_running(monkeypatch):
    _setup(monkeypatch, SdCppConfig(binary_path="/opt/sd-server"))
    assert not await ImageGenLink(None).shown()


@pytest.mark.asyncio
async def test_hidden_when_tracked_process_is_dead(monkeypatch):
    _setup(monkeypatch, SdCppConfig(binary_path="/opt/sd-server"), tracked={"pid": 42}, alive=False)
    assert not await ImageGenLink(None).shown()


@pytest.mark.asyncio
async def test_shown_while_local_engine_runs(monkeypatch):
    _setup(monkeypatch, SdCppConfig(binary_path="/opt/sd-server"), tracked={"pid": 42}, alive=True)
    assert await ImageGenLink(None).shown()


@pytest.mark.asyncio
async def test_remote_mode_needs_a_host(monkeypatch):
    _setup(monkeypatch, SdCppConfig(mode="remote"))
    assert not await ImageGenLink(None).shown()
    _setup(monkeypatch, SdCppConfig(mode="remote", remote_hosts=["http://gpu-box:7860"]))
    assert await ImageGenLink(None).shown()


@pytest.mark.asyncio
async def test_hidden_when_off_in_a_ring(monkeypatch):
    _setup(monkeypatch, SdCppConfig(binary_path="/opt/sd-server"), tracked={"pid": 42}, alive=True, off=True)
    assert not await ImageGenLink(None).shown()
