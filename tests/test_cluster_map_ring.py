"""The map's pAIring box in a ring: one box, named "pAIring (ring mode)", every machine in its details."""

from pathlib import Path
from types import SimpleNamespace

from app.services.cluster_map import ClusterMapBuilder
from app.services.cluster_map_ring import RING_NAME, PairingRing
from app.services.cluster_service import ClusterService


def _row(server_id: str, machine: str, addresses: list[str], primary: bool = True, seen: int = 100):
    details = {"machine": machine, "addresses": addresses}
    return SimpleNamespace(server_id=server_id, is_primary=primary, last_seen=seen, details=details)


class _Registry:
    def __init__(self, rows: list, server_id: str = "main:8000") -> None:
        self.rows = rows
        self.server_id = server_id

    async def servers(self, _db) -> tuple[list, int]:
        return self.rows, 100

    def online(self, row, now: int) -> bool:
        return now - row.last_seen < 60


def _ring(rows: list, shared: bool = True) -> PairingRing:
    return PairingRing(_Registry(rows), lambda _db: shared)


async def test_two_machines_make_a_ring() -> None:
    rows = [
        _row("bp-1:8000", "bp-1", ["10.0.0.2"]),
        _row("main:8000", "main", ["10.0.0.1", "192.168.1.5"]),
        _row("main:8001", "main", ["10.0.0.1"], primary=False),  # a local instance: same machine
        _row("old:8000", "old", ["10.0.0.9"], seen=0),  # offline
    ]
    members = await _ring(rows).members(None)
    got = [(m.name, m.addresses, m.online, m.this_server) for m in members]
    assert got == [  # online first, offline kept (greyed in the panel), this machine marked
        ("bp-1", "10.0.0.2", True, False),
        ("main", "10.0.0.1, 192.168.1.5", True, True),
        ("old", "10.0.0.9", False, False),
    ]


async def test_one_online_with_offline_is_no_ring() -> None:
    rows = [_row("main:8000", "main", ["10.0.0.1"]), _row("old:8000", "old", ["10.0.0.9"], seen=0)]
    assert await _ring(rows).members(None) == []


async def test_one_machine_or_sqlite_is_no_ring() -> None:
    rows = [_row("main:8000", "main", ["10.0.0.1"]), _row("main:8001", "main", [], primary=False)]
    assert await _ring(rows).members(None) == []
    two = [_row("a:8000", "a", ["1.1.1.1"]), _row("b:8000", "b", ["2.2.2.2"])]
    assert await _ring(two, shared=False).members(None) == []


async def test_map_box_named_ring_with_list(db) -> None:
    ring = _ring([_row("a:8000", "a", ["10.0.0.1"]), _row("b:8000", "b", [])])
    builder = ClusterMapBuilder(db, ClusterService(db, []), ring=ring)
    app = next(n for n in (await builder.build()).nodes if n.id == "app")
    assert app.name == RING_NAME and "ring" in app.badges
    assert [(s.name, s.addresses) for s in app.servers] == [("a", "10.0.0.1"), ("b", "no address reported")]
    assert app.details["Ring"] == "2 pAIring servers online"
    compact = next(n for n in (await builder.build(compact=True)).nodes if n.id == "app")
    assert compact.name == RING_NAME and compact.servers == []  # the list loads on click


def test_panel_lists_servers_under_checklist() -> None:
    js = Path(__file__).parent.parent / "app" / "static" / "js"
    panel = (js / "cluster_node_panel.js").read_text()
    assert panel.index("${checks}") < panel.index("${clusterServersList(node.servers)}")
    assert "function clusterServersList" in (js / "cluster_map_common.js").read_text()


async def test_map_box_plain_without_ring(db) -> None:
    builder = ClusterMapBuilder(db, ClusterService(db, []), ring=_ring([_row("a:8000", "a", ["10.0.0.1"])]))
    app = next(n for n in (await builder.build()).nodes if n.id == "app")
    assert app.name == "pAIring" and app.servers == [] and "Ring" not in app.details
