"""Tests can't reach real servers (conftest._tests_never_reach_real_servers), only the ones they start."""

import httpx
import pytest

from tests.network_guard import LocalTestServers


@pytest.mark.asyncio
async def test_a_live_local_engine_port_is_refused_without_a_connection() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError, match="tests may not reach real servers"):
            await client.delete("http://127.0.0.1:8420/api/cache/persistence/chats/x")


def test_sync_requests_and_outside_hosts_are_refused_too() -> None:
    with pytest.raises(httpx.ConnectError, match="tests may not reach real servers"):
        httpx.get("https://huggingface.co/api/models")


def test_only_ports_a_test_server_registered_are_allowed() -> None:
    LocalTestServers.allow(54321)
    assert LocalTestServers.allowed("127.0.0.1", 54321)
    assert not LocalTestServers.allowed("127.0.0.1", 8420)
    assert not LocalTestServers.allowed("example.com", 54321)
