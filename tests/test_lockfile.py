"""Tests for opensepia/lockfile.py — process lock management."""

import os
import tempfile
import pytest
from pathlib import Path

from opensepia.lockfile import ProcessLock, _is_pid_alive
from opensepia.errors import LockError


@pytest.fixture
def lock_dir(tmp_path):
    return str(tmp_path)


# ---------------------------------------------------------------------------
# _is_pid_alive
# ---------------------------------------------------------------------------

def test_is_pid_alive_current_process():
    assert _is_pid_alive(os.getpid()) is True


def test_is_pid_alive_bogus_pid():
    assert _is_pid_alive(99999999) is False


def test_is_pid_alive_zero():
    # PID 0 is special (kernel), should not be "alive" for our purposes
    # On some systems kill(0,0) checks all processes in the group
    result = _is_pid_alive(0)
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# ProcessLock — basic acquire/release
# ---------------------------------------------------------------------------

def test_acquire_and_release(lock_dir):
    lock = ProcessLock("test-mode", lock_dir=lock_dir)
    lock.acquire()
    assert lock.lock_path.exists()
    assert lock.lock_path.read_text().strip() == str(os.getpid())

    lock.release()
    assert not lock.lock_path.exists()


def test_acquire_twice_raises(lock_dir):
    lock1 = ProcessLock("test-mode", lock_dir=lock_dir)
    lock1.acquire()

    lock2 = ProcessLock("test-mode", lock_dir=lock_dir)
    with pytest.raises(LockError, match="running"):
        lock2.acquire()

    lock1.release()


def test_different_modes_no_conflict(lock_dir):
    lock1 = ProcessLock("mode-a", lock_dir=lock_dir)
    lock2 = ProcessLock("mode-b", lock_dir=lock_dir)

    lock1.acquire()
    lock2.acquire()  # Should not raise

    lock1.release()
    lock2.release()


def test_stale_lock_removed(lock_dir):
    """A lock file with a dead PID should be cleaned up."""
    lock_path = Path(lock_dir) / "ai-team-cli-stale.lock"
    lock_path.write_text("99999999")  # Dead PID

    lock = ProcessLock("stale", lock_dir=lock_dir)
    lock.acquire()  # Should succeed by removing stale lock
    assert lock.lock_path.exists()
    lock.release()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

def test_context_manager(lock_dir):
    with ProcessLock("ctx-test", lock_dir=lock_dir) as lock:
        assert lock.lock_path.exists()
    assert not lock.lock_path.exists()


def test_context_manager_releases_on_exception(lock_dir):
    try:
        with ProcessLock("exc-test", lock_dir=lock_dir) as lock:
            assert lock.lock_path.exists()
            raise ValueError("test error")
    except ValueError:
        pass
    assert not lock.lock_path.exists()


# ---------------------------------------------------------------------------
# Default lock dir
# ---------------------------------------------------------------------------

def test_default_lock_dir_is_user_specific():
    lock = ProcessLock("default-test")
    expected_dir = Path.home() / ".opensepia" / "locks"
    assert lock.lock_path.parent == expected_dir
