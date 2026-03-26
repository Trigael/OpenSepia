"""Tests for orchestrator/daemon_state.py — state serialization."""

import json
import os
from pathlib import Path

import pytest
from opensepia.daemon_state import DaemonState


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "daemon_state.json"


# ---------------------------------------------------------------------------
# DaemonState basics
# ---------------------------------------------------------------------------

def test_default_state():
    state = DaemonState()
    assert state.pid == 0
    assert state.status == "stopped"
    assert state.mode == "dev-team"
    assert state.cycle_count == 0


def test_state_with_values():
    state = DaemonState(pid=123, status="running", mode="minimal", cycle_count=5)
    assert state.pid == 123
    assert state.status == "running"
    assert state.mode == "minimal"
    assert state.cycle_count == 5


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

def test_save_and_load(state_path):
    state = DaemonState(
        pid=42,
        status="running",
        mode="dev-team",
        started_at="2026-03-26T10:00:00",
        cycle_count=10,
        pause_seconds=120,
    )
    state.save(state_path)

    loaded = DaemonState.load(state_path)
    assert loaded.pid == 42
    assert loaded.status == "running"
    assert loaded.mode == "dev-team"
    assert loaded.started_at == "2026-03-26T10:00:00"
    assert loaded.cycle_count == 10
    assert loaded.pause_seconds == 120


def test_load_missing_file(state_path):
    loaded = DaemonState.load(state_path)
    assert loaded.status == "stopped"
    assert loaded.pid == 0


def test_load_corrupt_file(state_path):
    state_path.write_text("not valid json{{{", encoding="utf-8")
    loaded = DaemonState.load(state_path)
    assert loaded.status == "stopped"


def test_load_ignores_unknown_fields(state_path):
    data = {"pid": 1, "status": "running", "unknown_field": "ignored"}
    state_path.write_text(json.dumps(data), encoding="utf-8")
    loaded = DaemonState.load(state_path)
    assert loaded.pid == 1
    assert loaded.status == "running"


def test_save_creates_parent_dirs(tmp_path):
    deep_path = tmp_path / "a" / "b" / "c" / "state.json"
    state = DaemonState(pid=1)
    state.save(deep_path)
    assert deep_path.exists()


# ---------------------------------------------------------------------------
# is_process_alive
# ---------------------------------------------------------------------------

def test_is_process_alive_current_pid():
    state = DaemonState(pid=os.getpid())
    assert state.is_process_alive() is True


def test_is_process_alive_bogus_pid():
    state = DaemonState(pid=99999999)
    assert state.is_process_alive() is False


def test_is_process_alive_zero_pid():
    state = DaemonState(pid=0)
    assert state.is_process_alive() is False


# ---------------------------------------------------------------------------
# mark_stopped
# ---------------------------------------------------------------------------

def test_mark_stopped(state_path):
    state = DaemonState(
        pid=123,
        status="running",
        current_step="agent_runner",
        next_cycle_at="2026-03-26T15:00:00",
    )
    state.mark_stopped(state_path)

    assert state.status == "stopped"
    assert state.pid == 0
    assert state.current_step is None
    assert state.next_cycle_at is None

    # Verify saved to disk
    loaded = DaemonState.load(state_path)
    assert loaded.status == "stopped"
    assert loaded.pid == 0


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------

def test_save_is_atomic(state_path):
    """Verify no .tmp file is left behind after save."""
    state = DaemonState(pid=1)
    state.save(state_path)

    tmp_path = state_path.with_suffix(".tmp")
    assert not tmp_path.exists()
    assert state_path.exists()
