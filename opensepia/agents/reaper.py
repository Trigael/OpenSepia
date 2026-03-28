"""
AI Dev Team — Process Reaper.

Kills orphaned agent child processes between cycles.
Scans /proc (Linux) for processes that look like agent children
(claude, pytest, bash wrappers) that have been reparented to init (PPID=1).

This is Layer 2 defense — the primary fix in invoker.py should prevent
most orphans, but this catches any that slip through.
"""

import os
import signal
import logging
import time

logger = logging.getLogger(__name__)

# Command patterns that identify agent child processes
_AGENT_CHILD_PATTERNS = (b"claude", b"pytest", b"python3 -m pytest")


def reap_orphaned_agents(grace_period: float = 2.0) -> int:
    """Find and kill orphaned processes that look like agent children.

    Only kills processes that:
    1. Are owned by the current user
    2. Have PPID == 1 (orphaned — reparented to init)
    3. Have cmdline matching known agent subprocess patterns
    4. Are NOT the current process or its ancestors

    Returns count of processes killed.
    """
    if not os.path.isdir("/proc"):
        return 0  # Not Linux

    my_uid = os.getuid()
    my_pid = os.getpid()
    killed = 0

    # Build set of ancestor PIDs to avoid killing ourselves
    ancestors = _get_ancestor_pids(my_pid)

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in ancestors:
            continue

        try:
            # Check ownership
            stat = os.stat(f"/proc/{pid}")
            if stat.st_uid != my_uid:
                continue

            # Check PPID == 1 (orphaned)
            ppid = _get_ppid(pid)
            if ppid != 1:
                continue

            # Check cmdline matches agent child patterns
            cmdline = _get_cmdline(pid)
            if not any(pat in cmdline for pat in _AGENT_CHILD_PATTERNS):
                continue

            # Kill it
            logger.info("Reaping orphaned process %d: %s", pid, cmdline[:200])
            os.kill(pid, signal.SIGTERM)
            killed += 1

        except (OSError, ValueError):
            continue  # Process disappeared during scan

    # SIGKILL survivors after grace period
    if killed:
        time.sleep(grace_period)
        _sigkill_survivors(my_uid)

    return killed


def _get_ancestor_pids(pid: int) -> set[int]:
    """Build set of ancestor PIDs from pid up to init."""
    ancestors = set()
    current = pid
    while current > 1:
        ancestors.add(current)
        try:
            current = _get_ppid(current)
        except (OSError, ValueError):
            break
    return ancestors


def _get_ppid(pid: int) -> int:
    """Read PPID from /proc/pid/stat."""
    with open(f"/proc/{pid}/stat", "rb") as f:
        content = f.read()
    # Format: "pid (comm) state ppid ..."
    # PPID is after the closing paren
    after_comm = content.split(b")")[-1].split()
    return int(after_comm[1])  # index 0=state, 1=ppid


def _get_cmdline(pid: int) -> bytes:
    """Read /proc/pid/cmdline."""
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        return f.read()


def _sigkill_survivors(uid: int) -> None:
    """SIGKILL any remaining orphaned agent children."""
    if not os.path.isdir("/proc"):
        return

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            stat = os.stat(f"/proc/{pid}")
            if stat.st_uid != uid:
                continue
            ppid = _get_ppid(pid)
            if ppid != 1:
                continue
            cmdline = _get_cmdline(pid)
            if any(pat in cmdline for pat in _AGENT_CHILD_PATTERNS):
                os.kill(pid, signal.SIGKILL)
                logger.info("SIGKILL sent to survivor %d", pid)
        except (OSError, ValueError):
            continue
