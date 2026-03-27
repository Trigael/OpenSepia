"""Tests for daemon.py — OrchestratorDaemon and helper functions."""

import os
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from opensepia.daemon import (
    OrchestratorDaemon,
    _write_control,
    get_daemon_status,
    CONTROL_FILE,
)
from opensepia.daemon_state import DaemonState, DAEMON_STATE_FILE


# =============================================================================
# OrchestratorDaemon init
# =============================================================================

class TestDaemonInit:
    def test_defaults(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        assert d.mode == "dev-team"
        assert d.pause == 60
        assert d.verbose is False
        assert d.max_cycles == 0
        assert d.max_sprints == 0

    def test_custom_params(self, tmp_path):
        d = OrchestratorDaemon(
            mode="test-mode", pause=30, verbose=True,
            tool_dir=tmp_path, max_cycles=5, max_sprints=2,
        )
        assert d.mode == "test-mode"
        assert d.pause == 30
        assert d.verbose is True
        assert d.max_cycles == 5
        assert d.max_sprints == 2

    def test_paths(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        assert d.state_path == tmp_path / DAEMON_STATE_FILE
        assert d.log_path == tmp_path / "logs" / "daemon.log"
        assert d.control_path == tmp_path / CONTROL_FILE


# =============================================================================
# Control file
# =============================================================================

class TestControlFile:
    def test_check_stop(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        d.control_path.parent.mkdir(parents=True, exist_ok=True)
        d.control_path.write_text("stop", encoding="utf-8")
        d._check_control_file()
        assert d._stopping is True

    def test_check_pause(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        d.control_path.parent.mkdir(parents=True, exist_ok=True)
        d.control_path.write_text("pause", encoding="utf-8")
        d._check_control_file()
        assert d._paused is True

    def test_check_resume(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        d._paused = True
        d.control_path.parent.mkdir(parents=True, exist_ok=True)
        d.control_path.write_text("resume", encoding="utf-8")
        d._check_control_file()
        assert d._paused is False

    def test_no_control_file(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        d._check_control_file()  # Should not crash
        assert d._stopping is False

    def test_control_file_removed_after_read(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        d.control_path.parent.mkdir(parents=True, exist_ok=True)
        d.control_path.write_text("stop", encoding="utf-8")
        d._check_control_file()
        assert not d.control_path.exists()


# =============================================================================
# _write_control helper
# =============================================================================

class TestWriteControl:
    def test_writes_command(self, tmp_path):
        _write_control(tmp_path, "pause")
        path = tmp_path / CONTROL_FILE
        assert path.read_text(encoding="utf-8") == "pause"

    def test_creates_parent_dirs(self, tmp_path):
        _write_control(tmp_path, "stop")
        assert (tmp_path / CONTROL_FILE).exists()


# =============================================================================
# Signal handler
# =============================================================================

class TestSignalHandler:
    def test_handle_stop_sets_flag(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        d._handle_stop(signal.SIGTERM, None)
        assert d._stopping is True


# =============================================================================
# Interruptible sleep
# =============================================================================

class TestInterruptibleSleep:
    def test_stops_early_on_stopping(self, tmp_path):
        d = OrchestratorDaemon(tool_dir=tmp_path)
        d._stopping = True
        d._interruptible_sleep(100)  # Should return immediately


# =============================================================================
# start() — prevents duplicate daemon
# =============================================================================

class TestStart:
    def test_raises_if_daemon_already_running(self, tmp_path):
        state = DaemonState(
            pid=os.getpid(),  # Current process — alive
            status="running",
            mode="dev-team",
        )
        state.save(tmp_path / DAEMON_STATE_FILE)

        d = OrchestratorDaemon(tool_dir=tmp_path)
        with pytest.raises(RuntimeError, match="already running"):
            d.start()


# =============================================================================
# get_daemon_status
# =============================================================================

class TestGetDaemonStatus:
    def test_returns_stopped_when_no_state(self, tmp_path):
        status = get_daemon_status(tmp_path)
        assert status.status == "stopped"

    def test_detects_crashed_daemon(self, tmp_path):
        state = DaemonState(pid=99999999, status="running", mode="dev-team")
        state.save(tmp_path / DAEMON_STATE_FILE)
        result = get_daemon_status(tmp_path)
        assert result.status == "crashed"


# =============================================================================
# run_loop with max_cycles
# =============================================================================

class TestRunLoop:
    @patch("opensepia.daemon.OrchestratorDaemon._run_single_cycle")
    @patch("opensepia.daemon.ProcessLock")
    def test_stops_after_max_cycles(self, MockLock, mock_cycle, tmp_path):
        mock_cycle.return_value = ("ok", [])
        lock_instance = MagicMock()
        MockLock.return_value = lock_instance

        d = OrchestratorDaemon(tool_dir=tmp_path, max_cycles=2, pause=0)
        d.run_loop()
        assert mock_cycle.call_count == 2

    @patch("opensepia.daemon.OrchestratorDaemon._run_single_cycle")
    @patch("opensepia.daemon.ProcessLock")
    def test_tracks_cycle_count(self, MockLock, mock_cycle, tmp_path):
        mock_cycle.return_value = ("ok", [])
        MockLock.return_value = MagicMock()

        d = OrchestratorDaemon(tool_dir=tmp_path, max_cycles=3, pause=0)
        d.run_loop()
        assert d._state.cycle_count == 3

    @patch("opensepia.daemon.OrchestratorDaemon._run_single_cycle")
    @patch("opensepia.daemon.ProcessLock")
    def test_records_errors(self, MockLock, mock_cycle, tmp_path):
        mock_cycle.return_value = ("error", ["something failed"])
        MockLock.return_value = MagicMock()

        d = OrchestratorDaemon(tool_dir=tmp_path, max_cycles=1, pause=0)
        d.run_loop()
        assert d._state.last_cycle_result == "error"
        assert "something failed" in d._state.last_cycle_errors
