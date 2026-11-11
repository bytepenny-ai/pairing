"""app/log_config.py: every pAIring log line starts with a timestamp, also after the start-up migration (alembic.ini
used to swap in its own format without a time, the "WARNI [llama_chat] ..." lines)."""

import logging
import re

from uvicorn.logging import AccessFormatter

from app import database
from app.log_config import LogConfig

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ")


def _record(name: str, msg: str, args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(name, logging.WARNING, __file__, 1, msg, args, None)


def test_app_lines_have_a_timestamp_level_and_name():
    formatter = logging.Formatter(LogConfig.as_dict()["formatters"]["default"]["format"])
    line = formatter.format(_record("llama_chat", "Could not poll /models"))
    assert STAMP.match(line) and line.endswith("WARNING llama_chat: Could not poll /models")


def test_access_lines_have_a_timestamp():
    config = LogConfig.as_dict()["formatters"]["access"]
    formatter = AccessFormatter(fmt=config["fmt"], use_colors=False)
    record = _record("uvicorn.access", '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5", "GET", "/api/x", "1.1", 200))
    line = formatter.format(record)
    assert STAMP.match(line) and line.endswith('access: 127.0.0.1:5 - "GET /api/x HTTP/1.1" 200 OK')


def test_the_start_up_migration_keeps_the_app_format(tmp_path):
    root = logging.getLogger()
    kept = (list(root.handlers), root.level)
    try:
        LogConfig.apply()
        handler = root.handlers[0]
        database._run_migrations(f"sqlite:///{tmp_path / 'db.sqlite'}")
        assert root.handlers[0] is handler
        assert "%(asctime)s" in handler.formatter._fmt
    finally:
        root.handlers[:] = kept[0]
        root.setLevel(kept[1])
