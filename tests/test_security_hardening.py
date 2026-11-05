"""Small hardening checks: .env stays owner-only, attachments stay inside their folder."""

import stat

import pytest
from fastapi import HTTPException

from app.services import chat_attachment_service
from app.services.env_file import write_env_value


def test_env_file_is_written_owner_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    env.chmod(0o644)

    write_env_value("SECRET_KEY", "x", env)

    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "SECRET_KEY=x" in env.read_text()


def test_new_env_file_is_created_owner_only(tmp_path):
    env = tmp_path / ".env"
    write_env_value("A", "1", env)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["..", "../outside", "a/../../b"])
async def test_attachments_refuse_a_folder_outside_their_root(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(chat_attachment_service, "ATTACHMENTS_DIR", tmp_path / "att")
    with pytest.raises(HTTPException) as exc_info:
        await chat_attachment_service.save_attachments([], bad)
    assert exc_info.value.status_code == 400
