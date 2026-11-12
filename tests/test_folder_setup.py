"""app/folder_setup.py: a folder pAIring can't create or use (the NFS share not mounted yet) stops the start with plain
reasons, not a traceback."""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

from app.folder_setup import FAILED, MOUNT_HINT, FolderSetup


@pytest.fixture
def locked(tmp_path):
    """A folder this user can't write in, like /mnt/mxshared before the share is mounted."""
    folder = tmp_path / "mnt"
    folder.mkdir()
    folder.chmod(0o500)
    yield folder
    folder.chmod(0o700)


def test_a_usable_folder_is_created(tmp_path):
    setup = FolderSetup()
    setup.ensure("KNOWLEDGE_DIR", tmp_path / "a" / "knowledge")
    assert setup.problems == [] and (tmp_path / "a" / "knowledge").is_dir()


def test_a_folder_that_cant_be_created_names_the_blocking_parent(locked):
    setup = FolderSetup()
    setup.ensure("KNOWLEDGE_DIR", locked / "pairing" / "knowledge")
    assert len(setup.problems) == 1
    assert setup.problems[0].startswith(f"KNOWLEDGE_DIR {locked}/pairing/knowledge can't be created: {locked} is not")


def test_a_file_in_the_way_is_not_a_folder(tmp_path):
    (tmp_path / "data").write_text("x")
    setup = FolderSetup()
    setup.ensure("DATA_DIR", tmp_path / "data")
    assert setup.problems == [f"DATA_DIR {tmp_path / 'data'} is not a folder"]


def test_problems_are_logged_with_the_mount_hint_and_exit_cleanly(locked, caplog):
    setup = FolderSetup()
    setup.ensure("IMAGES_DIR", locked / "images")
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as stopped:
        setup.stop_if_any()
    assert stopped.value.code == 1
    assert [r.getMessage() for r in caplog.records][-1] == f"{FAILED} {MOUNT_HINT}"


def test_starting_with_an_unmounted_share_prints_reasons_not_a_traceback(locked):
    folders = {name: str(locked / "pairing" / name.lower()) for name in ("KNOWLEDGE_DIR", "ATTACHMENTS_DIR")}
    run = subprocess.run(
        [sys.executable, "-c", "from app.log_config import LogConfig; LogConfig.apply(); import app.config"],
        cwd=Path(__file__).parent.parent,
        env={"PATH": "/usr/bin:/bin", "HOME": str(locked.parent), **folders},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 1 and "Traceback" not in run.stderr
    assert f"{FAILED} KNOWLEDGE_DIR" in run.stderr and f"{FAILED} ATTACHMENTS_DIR" in run.stderr
    assert MOUNT_HINT in run.stderr
