"""Creates pAIring's folders at start-up (app/config.py) and says in plain words why one can't be used: not creatable,
permission denied, not a folder or unreachable (a stale NFS handle). On a shared-storage setup the usual cause is the
NFS share not mounted yet (after a reboot), which used to end in a long traceback. No app imports: config.py runs it
before anything else is loaded."""

import errno
import getpass
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("llama_chat")

MOUNT_HINT = "is the shared storage (NFS) mounted, and does this user own it?"
# start.sh looks for this to show the reasons instead of the log's last lines.
FAILED = "pAIring cannot start:"


class FolderSetup:
    def __init__(self) -> None:
        self._user = getpass.getuser()
        self.problems: list[str] = []

    def ensure(self, name: str, path: Path) -> None:
        """Creates `path` when missing; a folder that can't be used is noted as one plain line."""
        try:
            path.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            self.problems.append(f"{name} {path} is not a folder")
            return
        except OSError as error:
            self.problems.append(f"{name} {self._why(path, error)}")
            return
        if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            self.problems.append(f"{name} {path} is not readable and writable by user '{self._user}'")

    def stop_if_any(self) -> None:
        """Logs every problem with the mount hint and exits without a traceback."""
        if not self.problems:
            return
        for problem in self.problems:
            logger.error("%s %s", FAILED, problem)
        logger.error("%s %s", FAILED, MOUNT_HINT)
        for handler in logging.getLogger().handlers:
            handler.flush()
        sys.exit(1)

    def _why(self, path: Path, error: OSError) -> str:
        if error.errno == errno.ESTALE:
            return f"{path} is not reachable (stale NFS handle: the share went away, remount it)"
        blocker = self._nearest_existing(path)
        if blocker is None:
            return f"{path} is not reachable ({error.strerror or type(error).__name__})"
        if not os.access(blocker, os.W_OK | os.X_OK):
            return f"{path} can't be created: {blocker} is not writable by user '{self._user}'"
        return f"{path} can't be created ({error.strerror or type(error).__name__})"

    @staticmethod
    def _nearest_existing(path: Path) -> Path | None:
        parent = path
        while True:
            try:
                if parent.exists():
                    return parent
            except OSError:
                return None
            if parent == parent.parent:
                return None
            parent = parent.parent
