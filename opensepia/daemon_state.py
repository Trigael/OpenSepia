"""
AI Dev Team — Daemon state management.

Persists daemon state to a JSON file for CLI introspection.
Uses atomic writes (temp file + os.replace) to prevent corruption.
"""

import json
import os
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DAEMON_STATE_FILE = "logs/daemon_state.json"


@dataclass
class DaemonState:
    """Persistent daemon state, written as JSON."""

    pid: int = 0
    status: str = "stopped"  # running | paused | stopping | stopped
    mode: str = "dev-team"
    started_at: Optional[str] = None
    cycle_count: int = 0
    current_cycle_started_at: Optional[str] = None
    current_step: Optional[str] = None
    last_cycle_finished_at: Optional[str] = None
    last_cycle_result: Optional[str] = None  # ok | error | None
    last_cycle_errors: list[str] = field(default_factory=list)
    next_cycle_at: Optional[str] = None
    pause_seconds: int = 60
    paused_at: Optional[str] = None

    def save(self, state_path: Path) -> None:
        """Atomically write state to JSON file."""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(state_path))
        except OSError as e:
            logger.warning("Failed to write daemon state: %s", e)
            tmp_path.unlink(missing_ok=True)

    @classmethod
    def load(cls, state_path: Path) -> "DaemonState":
        """Load state from JSON file. Returns default stopped state if missing/corrupt."""
        if not state_path.exists():
            return cls()
        try:
            data = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, dict):
                return cls()
            known = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError, UnicodeDecodeError) as e:
            logger.warning("Corrupt daemon state file, using defaults: %s", e)
            return cls()

    def is_process_alive(self) -> bool:
        """Check if the stored PID corresponds to a running Python process.

        Uses /proc/{pid}/cmdline on Linux to verify the PID isn't a recycled
        non-Python process (e.g., a system daemon that reused the PID).
        Falls back to a plain kill-0 check on platforms without procfs.
        """
        if self.pid <= 0:
            return False
        from opensepia.lockfile import _is_pid_alive
        if not _is_pid_alive(self.pid):
            return False
        # Verify it's a Python process (not a recycled system PID)
        try:
            cmdline = Path(f"/proc/{self.pid}/cmdline").read_bytes()
            return b"python" in cmdline
        except (OSError, ValueError):
            # No procfs (macOS/Windows) — fall back to PID-only check
            return True

    def mark_stopped(self, state_path: Path) -> None:
        """Mark daemon as stopped and clear transient fields."""
        self.status = "stopped"
        self.pid = 0
        self.current_step = None
        self.current_cycle_started_at = None
        self.next_cycle_at = None
        self.paused_at = None
        self.save(state_path)
