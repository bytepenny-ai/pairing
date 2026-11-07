"""Cluster > Servers shows each machine's IP addresses: server_facts.machine_addresses and the heartbeat report."""

import socket
from types import SimpleNamespace

import pytest

from app.schemas.servers import ServerOut
from app.services import server_facts


def _addr(family: int, address: str) -> SimpleNamespace:
    return SimpleNamespace(family=family, address=address)


@pytest.fixture
def interfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = {
        "lo": [_addr(socket.AF_INET, "127.0.0.1"), _addr(socket.AF_INET6, "::1")],
        "wlan0": [_addr(socket.AF_INET, "172.20.10.14"), _addr(socket.AF_INET6, "fe80::1")],
        "virbr0": [_addr(socket.AF_INET, "192.168.122.1")],
        "eth9": [_addr(socket.AF_INET, "169.254.3.4")],  # link-local: no DHCP answer
        "eth0": [_addr(socket.AF_INET, "10.0.0.5")],
    }
    monkeypatch.setattr(server_facts.psutil, "net_if_addrs", lambda: fake)


def test_lists_ipv4_without_loopback_or_link_local_in_order(interfaces: None) -> None:
    assert server_facts.machine_addresses() == ["10.0.0.5", "172.20.10.14", "192.168.122.1"]


def test_the_heartbeat_report_carries_them(interfaces: None, tmp_path) -> None:
    report = server_facts.ServerFacts(folders={"KNOWLEDGE_DIR": tmp_path}).report()
    assert report["addresses"] == ["10.0.0.5", "172.20.10.14", "192.168.122.1"]


def test_a_server_without_the_field_shows_none() -> None:
    old = ServerOut(
        server_id="old:8000",
        version="2.1",
        is_primary=True,
        online=True,
        leader=False,
        seconds_since_seen=0,
        this_server=False,
    )
    assert old.addresses == []
