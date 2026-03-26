"""
AI Dev Team — Process lock management.

Prevents multiple orchestrator instances from running the same mode
concurrently. Uses PID-based lockfiles with stale lock detection.
"""

import os
import signal
import logging
from pathlib import Path

from orchestrator.errors import LockError

logger = logging.getLogger(__name__)


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

    def __init__(self, mode: str, lock_dir: str = "/tmp"):
        self.mode = mode
        self.lock_path = Path(lock_dir) / f"ai-team-cli-{mode}.lock"
        self._acquired = False

    def acquire(self) -> None:
        """Acquire the lock. Raises LockError if another instance is running."""
        if self.lock_path.exists():
            try:
                pid = int(self.lock_path.read_text().strip())
                # Check if process is still running
                os.kill(pid, 0)
                raise LockError(
                    f"Previous {self.mode} cycle is running (PID: {pid})"
                )
            except (ValueError, ProcessLookupError, PermissionError):
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
