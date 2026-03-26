"""
AI Dev Team — Process lock management.

Prevents multiple orchestrator instances from running the same mode
concurrently. Uses PID-based lockfiles with stale lock detection.
Cross-platform: uses tempfile.gettempdir() instead of hardcoded /tmp/.
"""

import os
import tempfile
import logging
import platform
from pathlib import Path

from opensepia.errors import LockError

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive (cross-platform)."""
    if IS_WINDOWS:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


class ProcessLock:
    """PID-based lockfile for preventing concurrent orchestrator runs.

    Usage:
        lock = ProcessLock("dev-team")
        lock.acquire()   # Raises LockError if already locked
        try:
            ...
        finally:
            lock.release()

    Or as a context manager:
        with ProcessLock("dev-team"):
            ...
    """

    def __init__(self, mode: str, lock_dir: str | None = None):
        if lock_dir is None:
            lock_dir = tempfile.gettempdir()
        self.mode = mode
        self.lock_path = Path(lock_dir) / f"ai-team-cli-{mode}.lock"
        self._acquired = False

    def acquire(self) -> None:
        """Acquire the lock. Raises LockError if another instance is running."""
        if self.lock_path.exists():
            try:
                pid = int(self.lock_path.read_text().strip())
                if _is_pid_alive(pid):
                    raise LockError(
                        f"Previous {self.mode} cycle is running (PID: {pid})"
                    )
            except (ValueError, OSError):
                pass
            # Stale lock — remove it
            logger.info("Removing stale lockfile for mode %s", self.mode)
            self.lock_path.unlink(missing_ok=True)

        self.lock_path.write_text(str(os.getpid()))
        self._acquired = True

    def release(self) -> None:
        """Release the lock."""
        if self._acquired:
            self.lock_path.unlink(missing_ok=True)
            self._acquired = False

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
