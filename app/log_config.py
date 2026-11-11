"""One log format for every pAIring process (run.py applies it before anything logs): a timestamp, the level, the
logger's name and the message, the same as Matricxon's log ("2026-11-11 09:29:14,978 INFO llama_chat: ..."). Covers
pAIring's own loggers, uvicorn's start-up and error lines, and its access lines (one per request). No app imports,
so it can run before app.config logs its first warning."""

import logging.config

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# uvicorn's start-up and error lines come from "uvicorn.error", even "Application startup complete": named "server".
_SERVER_FORMAT = "%(asctime)s %(levelname)s server: %(message)s"
_ACCESS_FORMAT = '%(asctime)s %(levelname)s access: %(client_addr)s - "%(request_line)s" %(status_code)s'


class LogConfig:
    @staticmethod
    def as_dict() -> dict:
        """For logging.config.dictConfig and uvicorn.run(log_config=...)."""
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": _FORMAT},
                "server": {"format": _SERVER_FORMAT},
                "access": {"()": "uvicorn.logging.AccessFormatter", "fmt": _ACCESS_FORMAT, "use_colors": False},
            },
            "handlers": {
                "default": {"class": "logging.StreamHandler", "formatter": "default", "stream": "ext://sys.stderr"},
                "server": {"class": "logging.StreamHandler", "formatter": "server", "stream": "ext://sys.stderr"},
                "access": {"class": "logging.StreamHandler", "formatter": "access", "stream": "ext://sys.stdout"},
            },
            "root": {"handlers": ["default"], "level": "INFO"},
            "loggers": {
                "uvicorn": {"level": "INFO"},
                "uvicorn.error": {"handlers": ["server"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
                # One line per internal HTTP call (pAIring polls its engines every second): warnings only.
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
            },
        }

    @classmethod
    def apply(cls) -> None:
        logging.config.dictConfig(cls.as_dict())
