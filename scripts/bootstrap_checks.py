"""Checks for scripts/bootstrap_join.sh: a new server joining existing pAIring servers, read from their MySQL.

Runs with the system python3 (python3-pymysql), before pAIring is installed. The connection comes from the
environment (DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME), SECRET_KEY too, so nothing secret is in argv.
Exit 0 = OK, 1 = a problem (printed), 2 = wrong use, 3 = only the version differs (db).
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

FOLDERS = ("KNOWLEDGE_DIR", "ATTACHMENTS_DIR", "AVATARS_DIR", "IMAGES_DIR")
MARKER_FILE = ".pairing_share_id"  # app/services/server_facts.py
LOCAL_MATRICXON_HOST = "http://localhost:8420"  # app/services/matricxon_pool.py
ONLINE_SECONDS = 120
VERSION_MISMATCH = 3  # db: everything else OK; the caller asks whether to go on


class SharedSetup:
    """What the existing servers wrote to the shared database."""

    def __init__(self, servers: list[dict[str, Any]], settings: dict[str, Any]) -> None:
        self.servers = sorted(servers, key=lambda s: s.get("last_seen") or 0, reverse=True)
        self.settings = settings

    @staticmethod
    def fingerprint(key: str) -> str:
        """Same as app/services/server_facts.secret_fingerprint."""
        return hmac.new(key.encode(), b"pairing-secret-fingerprint", hashlib.sha256).hexdigest()[:12]

    def online(self, now: float) -> list[dict[str, Any]]:
        return [s for s in self.servers if now - (s.get("last_seen") or 0) <= ONLINE_SECONDS]

    def reference(self) -> dict[str, Any]:
        """The most recently seen server: its folders and commit are the ones to match."""
        return self.servers[0] if self.servers else {}

    def secret_matches(self, key: str) -> bool:
        seen = {(s.get("details") or {}).get("secret") for s in self.servers} - {None}
        return bool(seen) and self.fingerprint(key) in seen

    def folders(self) -> dict[str, dict[str, Any]]:
        return (self.reference().get("details") or {}).get("folders") or {}

    def marker_ok(self, name: str, found: str | None) -> bool:
        markers = self.settings.get("shared_folder_markers") or {}
        allowed = {(markers.get("ids") or {}).get(name), (markers.get("previous") or {}).get(name)} - {None}
        return found is not None and found in allowed

    def matricxon_hosts(self) -> list[str]:
        """Same as app/services/cluster_hosts.ClusterHosts.nodes."""
        config = self.settings.get("matricxon_server_config") or {}
        base = (config.get("remote_hosts") or []) if config.get("mode") == "remote" else [LOCAL_MATRICXON_HOST]
        return base + [h for h in config.get("cluster_hosts") or [] if h not in base]


class SharedDatabase:
    """Reads the shared tables; the only part that needs MySQL."""

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env

    def url(self) -> str:
        e = self.env
        user, password = quote(e["DB_USER"], safe=""), quote(e["DB_PASS"], safe="")
        return f"mysql+pymysql://{user}:{password}@{e['DB_HOST']}:{e.get('DB_PORT') or 3306}/{e['DB_NAME']}"

    def _connect(self):  # noqa: ANN202 (pymysql is imported only here, so a missing driver is reported)
        import pymysql

        e = self.env
        return pymysql.connect(
            host=e["DB_HOST"],
            port=int(e.get("DB_PORT") or 3306),
            user=e["DB_USER"],
            password=e["DB_PASS"],
            database=e["DB_NAME"],
            connect_timeout=8,
        )

    def start_instances(self, machine: str, count: int) -> bool:
        """This machine's own local instance count (app/services/instance_count.py), only if it has none yet, so a
        joining server does not take another server's. True when written."""
        key = f"instance_count:{machine}"[:100]
        with self._connect() as conn, conn.cursor() as cur:
            written = cur.execute(
                "INSERT IGNORE INTO app_settings (owner_id, `key`, value) VALUES ('__system__', %s, %s)",
                (key, json.dumps({"count": count})),
            )
            conn.commit()
        return bool(written)

    def load(self) -> SharedSetup:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT server_id, git_commit, last_seen, details FROM servers")
            servers = [
                {"server_id": r[0], "git_commit": r[1], "last_seen": r[2], "details": json.loads(r[3] or "{}")}
                for r in cur.fetchall()
            ]
            cur.execute(
                "SELECT `key`, value FROM app_settings WHERE owner_id='__system__' "
                "AND `key` IN ('shared_folder_markers', 'matricxon_server_config')"
            )
            settings = {r[0]: json.loads(r[1]) for r in cur.fetchall()}
        return SharedSetup(servers, settings)


class JoinChecks:
    """One method per subcommand; each prints what it found."""

    def __init__(self, db: SharedDatabase) -> None:
        self.db = db

    def run(self, command: str, args: list[str]) -> int:
        if command == "url":
            print(self.db.url())
            return 0
        if command == "instances":
            return self.instances(args)
        try:
            setup = self.db.load()
        except Exception as exc:  # any driver or network error is shown as is
            print(f"Cannot read the database: {exc}")
            return 1
        handlers = {
            "db": self.database,
            "secret": self.secret,
            "folders": self.folders,
            "markers": self.markers,
            "matricxon": self.matricxon,
        }
        return handlers[command](setup, args) if command in handlers else 2

    def instances(self, args: list[str]) -> int:
        """instances <machine>: it starts with 1 local instance unless it already has its own count."""
        try:
            written = self.db.start_instances(args[0], 1)
        except Exception as exc:  # any driver or network error is shown as is
            print(f"Cannot write to the database: {exc}")
            return 1
        print(
            "    Local instances: 1 (change it on its Settings > System page)."
            if written
            else "    Local instances: its own earlier setting is kept."
        )
        return 0

    def database(self, setup: SharedSetup, args: list[str]) -> int:
        if not setup.servers:
            print("This database has no pAIring servers: it is not a running pAIring's database.")
            return 1
        online = setup.online(time.time())
        for s in setup.servers:
            print(
                f"    server {s['server_id']} (commit {s.get('git_commit') or '?'})"
                + (" online" if s in online else " offline")
            )
        if not online:
            return self._fail("No server is online (none seen in the last 2 minutes).")
        commit = setup.reference().get("git_commit")
        if args and commit and not args[0].startswith(commit) and not commit.startswith(args[0]):
            print(
                f"Version mismatch: the servers run commit {commit}, this clone is {args[0]}. pAIring migrates the"
                " database when it starts, so a newer version changes it under the older servers."
            )
            return VERSION_MISMATCH
        return 0

    def secret(self, setup: SharedSetup, args: list[str]) -> int:
        if setup.secret_matches(os.environ.get("SECRET_KEY", "")):
            return 0
        return self._fail("That is not the SECRET_KEY the other pAIring servers use (copy it from their .env).")

    def folders(self, setup: SharedSetup, args: list[str]) -> int:
        folders, bad = setup.folders(), []
        for name in FOLDERS:
            info = folders.get(name) or {}
            print(f"{name}={info.get('path', '')}")
            if not info.get("path") or not info.get("shared"):
                bad.append(name)
        if bad:
            return self._fail("Not on shared storage on the other servers yet: " + ", ".join(bad) + ".")
        return 0

    def markers(self, setup: SharedSetup, args: list[str]) -> int:
        bad = []
        for name, info in setup.folders().items():
            try:
                found = (Path(info.get("path", "")) / MARKER_FILE).read_text().strip()
            except OSError:
                found = None
            if not setup.marker_ok(name, found):
                bad.append(f"{name} ({info.get('path')})")
        return self._fail("Not the other servers' folders: " + ", ".join(bad) + ".") if bad else 0

    def matricxon(self, setup: SharedSetup, args: list[str]) -> int:
        hosts, bad = setup.matricxon_hosts(), 0
        if not hosts:
            print("    No Matricxon is set up: the engine is chosen in Settings.")
        for host in hosts:
            ok = self._reachable(host)
            print(f"    {host}: " + ("reachable" if ok else "NOT reachable from here"))
            bad += not ok
        if any("localhost" in h or "127.0.0.1" in h for h in hosts):
            print("    'localhost' is the server itself here: on the Cluster page, use an address all servers reach.")
            bad += 1
        return 1 if bad else 0

    @staticmethod
    def _reachable(host: str) -> bool:
        try:
            with urllib.request.urlopen(host.rstrip("/") + "/api/health", timeout=5) as resp:
                return resp.status == 200
        except OSError:
            return False

    @staticmethod
    def _fail(message: str) -> int:
        print(message)
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: bootstrap_checks.py url|db [commit]|secret|folders|markers|matricxon|instances <machine>")
    sys.exit(JoinChecks(SharedDatabase(dict(os.environ))).run(sys.argv[1], sys.argv[2:]))
