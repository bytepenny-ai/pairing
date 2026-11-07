"""scripts/bootstrap_checks.py: the join checks of a new server, against the shared database's contents."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from app.services.server_facts import MARKER_FILE, secret_fingerprint

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap_checks.py"
_spec = importlib.util.spec_from_file_location("bootstrap_checks", _PATH)
checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checks)


def _server(last_seen: int, secret: str = "k", folders: dict[str, Any] | None = None, commit: str = "abc1234") -> dict:
    details = {"secret": secret_fingerprint(secret), "folders": folders or {}}
    return {"server_id": f"s{last_seen}", "git_commit": commit, "last_seen": last_seen, "details": details}


class _FakeDb:
    def __init__(self, setup: Any) -> None:
        self.setup = setup

    def load(self) -> Any:
        return self.setup

    def url(self) -> str:
        return "url"


def test_fingerprint_matches_the_app() -> None:
    assert checks.SharedSetup.fingerprint("a-key") == secret_fingerprint("a-key")
    assert checks.MARKER_FILE == MARKER_FILE


def test_secret_matches_only_the_servers_key() -> None:
    setup = checks.SharedSetup([_server(1, secret="right")], {})
    assert setup.secret_matches("right")
    assert not setup.secret_matches("wrong")
    assert not checks.SharedSetup([], {}).secret_matches("right")


def test_url_quotes_user_and_password() -> None:
    env = {"DB_USER": "pa ir", "DB_PASS": "p@ss/:word", "DB_HOST": "10.0.0.2", "DB_PORT": "", "DB_NAME": "db"}
    assert checks.SharedDatabase(env).url() == "mysql+pymysql://pa%20ir:p%40ss%2F%3Aword@10.0.0.2:3306/db"


@pytest.mark.parametrize(
    ("config", "hosts"),
    [
        (
            {"mode": "remote", "remote_hosts": ["http://a:8420"], "cluster_hosts": ["http://b:8420", "http://a:8420"]},
            ["http://a:8420", "http://b:8420"],
        ),
        ({"mode": "local", "cluster_hosts": ["http://b:8420"]}, ["http://localhost:8420", "http://b:8420"]),
        ({"mode": "remote", "remote_hosts": []}, []),
    ],
)
def test_matricxon_hosts_follow_the_app(config: dict, hosts: list[str]) -> None:
    assert checks.SharedSetup([], {"matricxon_server_config": config}).matricxon_hosts() == hosts


def test_marker_accepts_current_and_previous_ids() -> None:
    markers = {"ids": {"AVATARS_DIR": "new"}, "previous": {"AVATARS_DIR": "old"}}
    setup = checks.SharedSetup([], {"shared_folder_markers": markers})
    assert setup.marker_ok("AVATARS_DIR", "new") and setup.marker_ok("AVATARS_DIR", "old")
    assert not setup.marker_ok("AVATARS_DIR", "other") and not setup.marker_ok("AVATARS_DIR", None)


def test_markers_reads_the_mounted_folders(tmp_path: Path) -> None:
    (tmp_path / MARKER_FILE).write_text("id1\n")
    folders = {"KNOWLEDGE_DIR": {"path": str(tmp_path), "shared": True}}
    markers = {"shared_folder_markers": {"ids": {"KNOWLEDGE_DIR": "id1"}}}
    setup = checks.SharedSetup([_server(5, folders=folders)], markers)
    assert checks.JoinChecks(_FakeDb(setup)).markers(setup, []) == 0
    (tmp_path / MARKER_FILE).write_text("elsewhere")
    assert checks.JoinChecks(_FakeDb(setup)).markers(setup, []) == 1


def test_folders_must_be_shared_on_the_newest_server(capsys: pytest.CaptureFixture[str]) -> None:
    names = checks.FOLDERS
    shared = {n: {"path": f"/mnt/s/{n}", "shared": True} for n in names}
    local = {n: {"path": f"/opt/p/{n}", "shared": False} for n in names}
    setup = checks.SharedSetup([_server(1, folders=local), _server(9, folders=shared)], {})
    assert checks.JoinChecks(_FakeDb(setup)).folders(setup, []) == 0
    assert "KNOWLEDGE_DIR=/mnt/s/KNOWLEDGE_DIR" in capsys.readouterr().out
    setup = checks.SharedSetup([_server(9, folders=local)], {})
    assert checks.JoinChecks(_FakeDb(setup)).folders(setup, []) == 1


def test_database_needs_an_online_server_of_the_same_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.time, "time", lambda: 1000.0)
    setup = checks.SharedSetup([_server(990, commit="abc1234")], {})
    run = checks.JoinChecks(_FakeDb(setup))
    assert run.database(setup, ["abc1234"]) == 0
    assert run.database(setup, ["fff9999"]) == checks.VERSION_MISMATCH
    assert run.database(checks.SharedSetup([_server(10)], {}), []) == 1
    assert run.database(checks.SharedSetup([], {}), []) == 1


def test_run_reports_a_database_error(capsys: pytest.CaptureFixture[str]) -> None:
    class _Broken(_FakeDb):
        def load(self) -> Any:
            raise OSError("refused")

    assert checks.JoinChecks(_Broken(None)).run("db", []) == 1
    assert "refused" in capsys.readouterr().out
    assert checks.JoinChecks(_FakeDb(None)).run("url", []) == 0


def test_instances_starts_a_new_server_with_one_and_keeps_its_own(capsys: pytest.CaptureFixture[str]) -> None:
    class _Db(_FakeDb):
        def __init__(self, written: bool) -> None:
            super().__init__(None)
            self.calls: list[tuple[str, int]] = []
            self.written = written

        def start_instances(self, machine: str, count: int) -> bool:
            self.calls.append((machine, count))
            return self.written

    new = _Db(written=True)
    assert checks.JoinChecks(new).run("instances", ["bp-1"]) == 0
    assert new.calls == [("bp-1", 1)] and "Local instances: 1" in capsys.readouterr().out
    assert checks.JoinChecks(_Db(written=False)).run("instances", ["bp-1"]) == 0
    assert "earlier setting is kept" in capsys.readouterr().out


def test_the_instance_key_matches_the_app() -> None:
    from app.services.instance_count import InstanceCount

    assert InstanceCount(None, "bp-1").key == "instance_count:bp-1"  # type: ignore[arg-type]
