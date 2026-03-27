"""Comprehensive unit tests for CLI command modules.

Tests daemon, observe, interact, and run commands with mocked dependencies.
"""

import json
import os
import sys
import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, PropertyMock, call
from dataclasses import dataclass, field
from typing import Any

import pytest

from opensepia.daemon_state import DaemonState
from opensepia.errors import ConfigError, LockError, OrchestratorError
from opensepia.config import OrchestratorConfig


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_dirs(tmp_path):
    """Create a minimal project directory structure."""
    tool_dir = tmp_path / "tool"
    project_dir = tmp_path / "tool" / "project"
    board_dir = project_dir / "board"
    workspace_dir = project_dir / "workspace"
    logs_dir = project_dir / "logs" / "runs"
    config_dir = tool_dir / "config"

    for d in [board_dir / "inbox", workspace_dir, logs_dir, config_dir, tool_dir / "logs"]:
        d.mkdir(parents=True, exist_ok=True)

    # Create sprint.md
    (board_dir / "sprint.md").write_text("# Sprint 1\n## TODO\n- [ ] STORY-001 Do stuff\n")
    # Create project.yaml
    (project_dir / "project.yaml").write_text("project:\n  name: TestProject\nsprint:\n  current_sprint: 1\n  current_cycle: 3\n")

    return {
        "tool_dir": tool_dir,
        "project_dir": project_dir,
        "board_dir": board_dir,
        "workspace_dir": workspace_dir,
        "logs_dir": logs_dir,
        "config_dir": config_dir,
    }


@pytest.fixture
def mock_config(tmp_dirs):
    """Create a mock OrchestratorConfig."""
    config = MagicMock(spec=OrchestratorConfig)
    config.tool_dir = tmp_dirs["tool_dir"]
    config.project_dir = tmp_dirs["project_dir"]
    config.board_dir = tmp_dirs["board_dir"]
    config.workspace_dir = tmp_dirs["workspace_dir"]
    config.logs_dir = tmp_dirs["logs_dir"]
    config.config_dir = tmp_dirs["config_dir"]
    config.sprint_num = 1
    config.cycle_num = 3
    config.project = {
        "project": {"name": "TestProject", "tech_stack": {"language": "Python"}},
        "sprint": {"current_sprint": 1, "current_cycle": 3, "cycles_per_sprint": 10},
    }
    config.agents = {
        "agents": {
            "po": {"name": "Product Owner", "system_prompt": "You are PO."},
            "dev1": {"name": "Developer 1", "system_prompt": "You are dev."},
        },
        "modes": {
            "dev-team": {"agents": ["po", "dev1"], "default": True},
            "po": {"agents": ["po"], "aliases": ["product-owner"]},
        },
        "execution": {"timeout": 900, "max_retries": 1, "retry_delay": 30},
    }
    config.validate.return_value = []
    config.resolve_agent_ids.return_value = ["po", "dev1"]
    config.get_all_agent_ids.return_value = ["po", "dev1"]
    config.get_execution_params.return_value = {"timeout": 900, "max_retries": 1, "retry_delay": 30, "pause_between_agents": 0}
    return config


def _make_state(status="stopped", pid=0, **kwargs):
    """Helper to create a DaemonState with is_process_alive mocked."""
    state = DaemonState(pid=pid, status=status, **kwargs)
    return state


@pytest.fixture
def daemon_state_running():
    """A DaemonState representing a running daemon."""
    return _make_state(
        status="running",
        pid=12345,
        mode="dev-team",
        started_at="2026-03-27T10:00:00",
        cycle_count=5,
        pause_seconds=60,
        current_step="agent_runner",
        last_cycle_result="ok",
        last_cycle_finished_at="2026-03-27T10:05:00",
        next_cycle_at="2026-03-27T10:06:00",
    )


@pytest.fixture
def daemon_state_stopped():
    """A DaemonState representing a stopped daemon."""
    return _make_state(status="stopped", pid=0)


@pytest.fixture
def daemon_state_paused():
    """A DaemonState representing a paused daemon."""
    return _make_state(
        status="paused",
        pid=12345,
        mode="dev-team",
        started_at="2026-03-27T10:00:00",
        cycle_count=3,
        pause_seconds=60,
        paused_at="2026-03-27T10:03:00",
    )


# =============================================================================
# Daemon commands
# =============================================================================

class TestCmdStart:
    """Tests for opensepia.commands.daemon.cmd_start."""

    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_start_success(self, mock_load, mock_ready, mock_git, mock_config):
        mock_load.return_value = mock_config
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": True, "has_remote": True, "repo_url": "git@example.com"}

        with patch("opensepia.daemon.OrchestratorDaemon") as MockDaemon:
            instance = MockDaemon.return_value
            instance.start.return_value = 9999

            from opensepia.commands.daemon import cmd_start
            cmd_start([])

            MockDaemon.assert_called_once_with(
                mode="dev-team", pause=60, verbose=False,
                max_cycles=0, max_sprints=0,
            )
            instance.start.assert_called_once()

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_start_config_error(self, mock_load):
        mock_load.side_effect = ConfigError("Missing agents.yaml")

        from opensepia.commands.daemon import cmd_start
        with pytest.raises(SystemExit) as exc_info:
            cmd_start([])
        assert exc_info.value.code == 1

    @patch("opensepia.commands.daemon.check_workspace_git")
    @patch("opensepia.commands.daemon.check_project_ready")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_start_project_not_ready(self, mock_load, mock_ready, mock_git, mock_config):
        mock_load.return_value = mock_config
        mock_ready.return_value = ["Project directory does not exist"]
        mock_git.return_value = {"initialized": False}

        from opensepia.commands.daemon import cmd_start
        with pytest.raises(SystemExit) as exc_info:
            cmd_start([])
        assert exc_info.value.code == 1

    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_start_daemon_already_running(self, mock_load, mock_ready, mock_git, mock_config):
        mock_load.return_value = mock_config
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": False}

        with patch("opensepia.daemon.OrchestratorDaemon") as MockDaemon:
            instance = MockDaemon.return_value
            instance.start.side_effect = RuntimeError("Daemon already running (PID: 123)")

            from opensepia.commands.daemon import cmd_start
            with pytest.raises(SystemExit) as exc_info:
                cmd_start([])
            assert exc_info.value.code == 1

    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_start_with_options(self, mock_load, mock_ready, mock_git, mock_config):
        mock_load.return_value = mock_config
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": True, "has_remote": False}

        with patch("opensepia.daemon.OrchestratorDaemon") as MockDaemon:
            instance = MockDaemon.return_value
            instance.start.return_value = 9999

            from opensepia.commands.daemon import cmd_start
            cmd_start(["--mode", "po", "--pause", "30", "--cycles", "5", "--sprints", "2", "--verbose"])

            MockDaemon.assert_called_once_with(
                mode="po", pause=30, verbose=True,
                max_cycles=5, max_sprints=2,
            )

    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_start_no_git_note(self, mock_load, mock_ready, mock_git, mock_config, capsys):
        mock_load.return_value = mock_config
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": False}

        with patch("opensepia.daemon.OrchestratorDaemon") as MockDaemon:
            instance = MockDaemon.return_value
            instance.start.return_value = 9999

            from opensepia.commands.daemon import cmd_start
            cmd_start([])

            captured = capsys.readouterr()
            assert "git sync disabled" in captured.out


class TestCmdStop:
    """Tests for opensepia.commands.daemon.cmd_stop."""

    @patch("opensepia.daemon.get_daemon_status")
    def test_stop_not_running(self, mock_status, daemon_state_stopped, capsys):
        mock_status.return_value = daemon_state_stopped

        from opensepia.commands.daemon import cmd_stop
        cmd_stop([])

        captured = capsys.readouterr()
        assert "not running" in captured.out

    @patch("opensepia.daemon.stop_daemon")
    @patch("opensepia.daemon.get_daemon_status")
    def test_stop_running(self, mock_status, mock_stop, daemon_state_running, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_running
            mock_stop.return_value = True

            from opensepia.commands.daemon import cmd_stop
            cmd_stop([])

            mock_stop.assert_called_once()
            captured = capsys.readouterr()
            assert "stopped" in captured.out.lower()

    @patch("opensepia.daemon.get_daemon_status")
    def test_stop_already_crashed(self, mock_status):
        state = _make_state(status="crashed", pid=99999)
        with patch.object(DaemonState, "is_process_alive", return_value=False):
            mock_status.return_value = state

            from opensepia.commands.daemon import cmd_stop
            cmd_stop([])
            # Should not call stop_daemon since state is crashed and process not alive


class TestCmdStatus:
    """Tests for opensepia.commands.daemon.cmd_status."""

    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.config.OrchestratorConfig.load")
    @patch("opensepia.daemon.get_daemon_status")
    def test_status_running(self, mock_status, mock_load, mock_git, mock_config, daemon_state_running, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_running
            mock_load.return_value = mock_config
            mock_git.return_value = {"initialized": True, "has_remote": True, "repo_url": ""}

            with patch("opensepia.board_adapter.create_board_adapter") as mock_adapter_fn:
                adapter = MagicMock()
                adapter.get_board_summary.return_value = {"done": 2, "in_progress": 1, "review": 0, "todo": 3}
                mock_adapter_fn.return_value = adapter

                from opensepia.commands.daemon import cmd_status
                cmd_status([])

        captured = capsys.readouterr()
        assert "RUNNING" in captured.out
        assert "12345" in captured.out

    @patch("opensepia.config.OrchestratorConfig.load")
    @patch("opensepia.daemon.get_daemon_status")
    def test_status_stopped_no_config(self, mock_status, mock_load, daemon_state_stopped, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=False):
            mock_status.return_value = daemon_state_stopped
            mock_load.side_effect = ConfigError("no config")

            from opensepia.commands.daemon import cmd_status
            cmd_status([])

        captured = capsys.readouterr()
        assert "STOPPED" in captured.out

    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.config.OrchestratorConfig.load")
    @patch("opensepia.daemon.get_daemon_status")
    def test_status_stopped_with_last_log(self, mock_status, mock_load, mock_git, mock_config, tmp_dirs, capsys):
        state = _make_state(status="stopped", pid=0)
        with patch.object(DaemonState, "is_process_alive", return_value=False):
            mock_status.return_value = state
            mock_load.return_value = mock_config
            mock_git.return_value = {"initialized": False}

            # Create a cycle log file
            log_data = {
                "timestamp": "2026-03-27T09:00:00",
                "status": "ok",
                "mode": "dev-team",
                "agents_ok_count": 2,
                "agents_failed_count": 0,
            }
            log_file = tmp_dirs["logs_dir"] / "cycle_20260327_090000.json"
            log_file.write_text(json.dumps(log_data))

            with patch("opensepia.board_adapter.create_board_adapter") as mock_adapter_fn:
                adapter = MagicMock()
                adapter.get_board_summary.return_value = {}
                mock_adapter_fn.return_value = adapter

                from opensepia.commands.daemon import cmd_status
                cmd_status([])

        captured = capsys.readouterr()
        assert "STOPPED" in captured.out
        assert "Last run" in captured.out
        assert "2 ok" in captured.out


class TestCmdPause:
    """Tests for opensepia.commands.daemon.cmd_pause."""

    @patch("opensepia.daemon.get_daemon_status")
    def test_pause_not_running(self, mock_status, daemon_state_stopped, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=False):
            mock_status.return_value = daemon_state_stopped

            from opensepia.commands.daemon import cmd_pause
            cmd_pause([])

        captured = capsys.readouterr()
        assert "not running" in captured.out

    @patch("opensepia.daemon.get_daemon_status")
    def test_pause_already_paused(self, mock_status, daemon_state_paused, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_paused

            from opensepia.commands.daemon import cmd_pause
            cmd_pause([])

        captured = capsys.readouterr()
        assert "already paused" in captured.out

    @patch("opensepia.daemon.send_pause_command")
    @patch("opensepia.daemon.get_daemon_status")
    def test_pause_success(self, mock_status, mock_send, daemon_state_running, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_running
            mock_send.return_value = "paused"

            from opensepia.commands.daemon import cmd_pause
            cmd_pause([])

        mock_send.assert_called_once_with(pause=True)
        captured = capsys.readouterr()
        assert "paused" in captured.out.lower()

    @patch("opensepia.daemon.send_pause_command")
    @patch("opensepia.daemon.get_daemon_status")
    def test_pause_runtime_error(self, mock_status, mock_send, daemon_state_running, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_running
            mock_send.side_effect = RuntimeError("Daemon is not running")

            from opensepia.commands.daemon import cmd_pause
            cmd_pause([])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "not running" in combined.lower()


class TestCmdResume:
    """Tests for opensepia.commands.daemon.cmd_resume."""

    @patch("opensepia.daemon.get_daemon_status")
    def test_resume_not_running(self, mock_status, daemon_state_stopped, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=False):
            mock_status.return_value = daemon_state_stopped

            from opensepia.commands.daemon import cmd_resume
            cmd_resume([])

        captured = capsys.readouterr()
        assert "not running" in captured.out

    @patch("opensepia.daemon.get_daemon_status")
    def test_resume_not_paused(self, mock_status, daemon_state_running, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_running

            from opensepia.commands.daemon import cmd_resume
            cmd_resume([])

        captured = capsys.readouterr()
        assert "not paused" in captured.out

    @patch("opensepia.daemon.send_pause_command")
    @patch("opensepia.daemon.get_daemon_status")
    def test_resume_success(self, mock_status, mock_send, daemon_state_paused, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_paused
            mock_send.return_value = "running"

            from opensepia.commands.daemon import cmd_resume
            cmd_resume([])

        mock_send.assert_called_once_with(pause=False)
        captured = capsys.readouterr()
        assert "resumed" in captured.out.lower()

    @patch("opensepia.daemon.send_pause_command")
    @patch("opensepia.daemon.get_daemon_status")
    def test_resume_runtime_error(self, mock_status, mock_send, daemon_state_paused, capsys):
        with patch.object(DaemonState, "is_process_alive", return_value=True):
            mock_status.return_value = daemon_state_paused
            mock_send.side_effect = RuntimeError("Daemon is not running")

            from opensepia.commands.daemon import cmd_resume
            cmd_resume([])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "not running" in combined.lower()


# =============================================================================
# Observe commands
# =============================================================================

class TestCmdLogs:
    """Tests for opensepia.commands.observe.cmd_logs."""

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_logs_no_daemon_log(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_logs
        cmd_logs([])

        captured = capsys.readouterr()
        assert "No daemon log" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_logs_shows_tail(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        (tool_dir / "logs").mkdir(parents=True)
        daemon_log = tool_dir / "logs" / "daemon.log"
        daemon_log.write_text("line1\nline2\nline3\nline4\nline5\n")
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(exist_ok=True)
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_logs
        cmd_logs(["--lines", "3"])

        captured = capsys.readouterr()
        assert "line3" in captured.out
        assert "line5" in captured.out

    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.config.OrchestratorConfig.load")
    @patch("opensepia.commands.observe._get_project_dirs")
    def test_logs_standup(self, mock_dirs, mock_load, mock_ba, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        mock_dirs.return_value = (tool_dir, logs_dir)

        mock_config = MagicMock()
        mock_load.return_value = mock_config

        adapter = MagicMock()
        adapter.get_standup_text.return_value = "# Standup -- Sprint 1\n## Developer 1\n- **STORY-001**: Working on it\nSome detail here\n"
        mock_ba.return_value = adapter

        from opensepia.commands.observe import cmd_logs
        cmd_logs(["--standup"])

        captured = capsys.readouterr()
        assert "Standup" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_logs_standup_empty(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        mock_dirs.return_value = (tool_dir, logs_dir)

        # No config -> fallback path
        with patch("opensepia.config.OrchestratorConfig.load", side_effect=ConfigError("no")):
            from opensepia.commands.observe import cmd_logs
            cmd_logs(["--standup"])

        captured = capsys.readouterr()
        assert "No standup" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_logs_cycle(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)

        log_data = {
            "timestamp": "2026-03-27T10:00:00",
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 3,
            "status": "ok",
            "agents_ok": ["po", "dev1"],
            "agents_failed": [],
            "agents": [
                {"agent": "po", "context_chars": 1000, "response_chars": 500},
                {"agent": "dev1", "context_chars": 2000, "response_chars": 800},
            ],
        }
        (logs_dir / "cycle_20260327_100000.json").write_text(json.dumps(log_data))

        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_logs
        cmd_logs(["--cycle"])

        captured = capsys.readouterr()
        assert "Last Cycle" in captured.out
        assert "dev-team" in captured.out
        assert "2 ok" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_logs_cycle_no_logs(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "empty_logs"
        logs_dir.mkdir()
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_logs
        cmd_logs(["--cycle"])

        captured = capsys.readouterr()
        assert "No cycle logs" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_logs_cycle_with_failed_agents(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)

        log_data = {
            "timestamp": "2026-03-27T10:00:00",
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 3,
            "status": "error",
            "agents_ok": ["po"],
            "agents_failed": ["dev1"],
            "agents": [
                {"agent": "po", "context_chars": 1000, "response_chars": 500},
                {"agent": "dev1", "error": "timeout after 900s"},
            ],
        }
        (logs_dir / "cycle_20260327_100000.json").write_text(json.dumps(log_data))
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_logs
        cmd_logs(["--cycle"])

        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "dev1" in captured.out


class TestCmdMonitor:
    """Tests for opensepia.commands.observe.cmd_monitor."""

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_monitor_no_logs(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_monitor
        cmd_monitor([])

        captured = capsys.readouterr()
        assert "No logs" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_monitor_with_data(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)

        # Create a recent log file (today)
        from datetime import datetime
        now = datetime.now()
        ts_str = now.strftime("%Y%m%d_%H%M%S")
        log_data = {
            "timestamp": now.isoformat(),
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 1,
            "status": "ok",
            "agents": [
                {"agent": "po", "context_chars": 500, "response_chars": 200},
            ],
        }
        (logs_dir / f"cycle_{ts_str}.json").write_text(json.dumps(log_data))
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_monitor
        cmd_monitor(["7"])

        captured = capsys.readouterr()
        assert "Cycles:" in captured.out
        assert "1" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_monitor_last_flag(self, mock_dirs, tmp_path, capsys):
        """--last delegates to _show_last_cycle."""
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_monitor
        cmd_monitor(["--last"])

        captured = capsys.readouterr()
        assert "No cycle logs" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_monitor_nonexistent_logs_dir(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "nonexistent"
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_monitor
        cmd_monitor([])

        captured = capsys.readouterr()
        assert "No logs" in captured.out


class TestCmdConfig:
    """Tests for opensepia.commands.interact.cmd_config."""

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_show_all(self, mock_load, mock_config, capsys):
        mock_load.return_value = mock_config

        from opensepia.commands.interact import cmd_config
        cmd_config([])

        captured = capsys.readouterr()
        assert "Project Settings" in captured.out
        assert "TestProject" in captured.out

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_show_project_section(self, mock_load, mock_config, capsys):
        mock_load.return_value = mock_config

        from opensepia.commands.interact import cmd_config
        cmd_config(["project"])

        captured = capsys.readouterr()
        assert "Project Settings" in captured.out

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_show_unknown_section(self, mock_load, mock_config, capsys):
        mock_load.return_value = mock_config

        from opensepia.commands.interact import cmd_config
        cmd_config(["bogus"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Unknown section" in combined

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_show_config_error(self, mock_load, capsys):
        mock_load.side_effect = ConfigError("missing config")

        from opensepia.commands.interact import cmd_config
        cmd_config([])

        captured = capsys.readouterr()
        assert "missing config" in captured.err

    def test_config_set_no_args(self, capsys):
        """config set with no key/value shows usage."""
        from opensepia.commands.interact import cmd_config
        cmd_config(["set"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Usage" in combined or "Settable keys" in combined

    def test_config_set_unknown_key(self, capsys):
        """config set with unknown key shows error."""
        from opensepia.commands.interact import cmd_config
        cmd_config(["set", "bogus.key", "value"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Unknown config key" in combined

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_set_project_key(self, mock_load, mock_config, tmp_dirs, capsys):
        mock_load.return_value = mock_config
        # Point to real project.yaml
        mock_config.project_dir = tmp_dirs["project_dir"]

        from opensepia.commands.interact import cmd_config
        cmd_config(["set", "project.name", "NewName"])

        captured = capsys.readouterr()
        assert "NewName" in captured.out

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_set_int_key_invalid(self, mock_load, mock_config, capsys):
        mock_load.return_value = mock_config

        from opensepia.commands.interact import cmd_config
        cmd_config(["set", "execution.timeout", "not-a-number"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "must be an integer" in combined

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_show_env_section(self, mock_load, mock_config, capsys):
        mock_load.return_value = mock_config

        from opensepia.commands.interact import cmd_config
        cmd_config(["env"])

        captured = capsys.readouterr()
        assert "Provider Integration" in captured.out

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_config_show_pipeline_section(self, mock_load, mock_config, capsys):
        mock_load.return_value = mock_config

        from opensepia.commands.interact import cmd_config
        cmd_config(["pipeline"])

        captured = capsys.readouterr()
        assert "Pipeline Steps" in captured.out


# =============================================================================
# Interact commands
# =============================================================================

class TestCmdMessage:
    """Tests for opensepia.commands.interact.cmd_message."""

    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_message_success(self, mock_load, mock_ba, mock_config, capsys):
        mock_load.return_value = mock_config

        adapter = MagicMock()
        mock_ba.return_value = adapter

        from opensepia.commands.interact import cmd_message
        cmd_message(["po", "Please", "review", "STORY-001"])

        adapter.send_inbox_message.assert_called_once_with("po", "Human", "Please review STORY-001")

        captured = capsys.readouterr()
        assert "Message sent" in captured.out

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_message_unknown_agent(self, mock_load, mock_config, capsys):
        mock_load.return_value = mock_config

        from opensepia.commands.interact import cmd_message
        cmd_message(["unknown_agent", "hello"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Unknown agent" in combined

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_message_config_error(self, mock_load, capsys):
        mock_load.side_effect = ConfigError("no config")

        from opensepia.commands.interact import cmd_message
        cmd_message(["po", "hello"])

        captured = capsys.readouterr()
        assert "no config" in captured.err

    def test_message_no_args(self):
        """cmd_message with no args should exit via argparse."""
        from opensepia.commands.interact import cmd_message
        with pytest.raises(SystemExit) as exc_info:
            cmd_message([])
        assert exc_info.value.code == 2  # argparse error


class TestCmdBoard:
    """Tests for opensepia.commands.interact.cmd_board."""

    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_board_success(self, mock_load, mock_ba, mock_config, capsys):
        mock_load.return_value = mock_config

        adapter = MagicMock()
        adapter.get_sprint_text.return_value = "# Sprint 1\n## TODO\n- [ ] STORY-001 Build widget\n"
        adapter.get_board_summary.return_value = {"done": 0, "in_progress": 0, "review": 0, "todo": 1}
        adapter.get_backlog_text.return_value = "### STORY-002 Another story\n"
        mock_ba.return_value = adapter

        from opensepia.commands.interact import cmd_board
        cmd_board([])

        captured = capsys.readouterr()
        assert "Sprint Board" in captured.out

    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_board_empty(self, mock_load, mock_ba, mock_config, capsys):
        mock_load.return_value = mock_config

        adapter = MagicMock()
        adapter.get_sprint_text.return_value = ""
        mock_ba.return_value = adapter

        from opensepia.commands.interact import cmd_board
        cmd_board([])

        captured = capsys.readouterr()
        assert "No sprint board" in captured.out

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_board_config_error(self, mock_load, capsys):
        mock_load.side_effect = ConfigError("missing config")

        from opensepia.commands.interact import cmd_board
        cmd_board([])

        captured = capsys.readouterr()
        assert "missing config" in captured.err

    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_board_with_done_items(self, mock_load, mock_ba, mock_config, capsys):
        mock_load.return_value = mock_config

        adapter = MagicMock()
        adapter.get_sprint_text.return_value = "# Sprint 1\n## DONE\n- [x] STORY-001 Build widget\n"
        adapter.get_board_summary.return_value = {"done": 1, "in_progress": 0, "review": 0, "todo": 0}
        adapter.get_backlog_text.return_value = ""
        mock_ba.return_value = adapter

        from opensepia.commands.interact import cmd_board
        cmd_board([])

        captured = capsys.readouterr()
        assert "Sprint Board" in captured.out
        assert "+" in captured.out  # done marker


# =============================================================================
# Run command
# =============================================================================

class TestCheckClaudeCli:
    """Tests for check_claude_cli helper."""

    @patch("shutil.which")
    def test_claude_available(self, mock_which):
        mock_which.return_value = "/usr/bin/claude"
        from opensepia.commands.run import check_claude_cli
        assert check_claude_cli() is True

    @patch("shutil.which")
    def test_claude_not_available(self, mock_which):
        mock_which.return_value = None
        from opensepia.commands.run import check_claude_cli
        assert check_claude_cli() is False


class TestCheckProjectReady:
    """Tests for check_project_ready helper."""

    def test_project_ready(self, tmp_dirs, mock_config):
        from opensepia.commands.run import check_project_ready
        issues = check_project_ready(mock_config)
        assert issues == []

    def test_project_dir_missing(self, mock_config):
        mock_config.project_dir = Path("/nonexistent/path")
        from opensepia.commands.run import check_project_ready
        issues = check_project_ready(mock_config)
        assert any("does not exist" in i for i in issues)

    def test_project_yaml_missing(self, tmp_dirs, mock_config):
        (tmp_dirs["project_dir"] / "project.yaml").unlink()
        from opensepia.commands.run import check_project_ready
        issues = check_project_ready(mock_config)
        assert any("project.yaml" in i for i in issues)

    def test_board_not_initialized(self, tmp_dirs, mock_config):
        (tmp_dirs["board_dir"] / "sprint.md").unlink()
        from opensepia.commands.run import check_project_ready
        issues = check_project_ready(mock_config)
        assert any("Board" in i for i in issues)

    def test_workspace_missing(self, tmp_dirs, mock_config):
        import shutil
        shutil.rmtree(tmp_dirs["workspace_dir"])
        from opensepia.commands.run import check_project_ready
        issues = check_project_ready(mock_config)
        assert any("Workspace" in i for i in issues)


class TestCheckWorkspaceGit:
    """Tests for check_workspace_git helper."""

    def test_no_workspace(self, mock_config):
        mock_config.workspace_dir = Path("/nonexistent")
        from opensepia.commands.run import check_workspace_git
        result = check_workspace_git(mock_config)
        assert result["initialized"] is False

    def test_no_git_dir(self, tmp_dirs, mock_config):
        from opensepia.commands.run import check_workspace_git
        result = check_workspace_git(mock_config)
        assert result["initialized"] is False
        assert result["reason"] == "no git"

    @patch("subprocess.run")
    def test_with_git(self, mock_run, tmp_dirs, mock_config):
        (tmp_dirs["workspace_dir"] / ".git").mkdir()
        mock_run.return_value = MagicMock(stdout="origin\tgit@example.com\n")

        from opensepia.commands.run import check_workspace_git
        result = check_workspace_git(mock_config)
        assert result["initialized"] is True
        assert result["has_remote"] is True

    @patch("subprocess.run")
    def test_with_git_no_remote(self, mock_run, tmp_dirs, mock_config):
        (tmp_dirs["workspace_dir"] / ".git").mkdir()
        mock_run.return_value = MagicMock(stdout="")

        from opensepia.commands.run import check_workspace_git
        result = check_workspace_git(mock_config)
        assert result["initialized"] is True
        assert result["has_remote"] is False

    @patch("subprocess.run")
    def test_with_git_subprocess_error(self, mock_run, tmp_dirs, mock_config):
        (tmp_dirs["workspace_dir"] / ".git").mkdir()
        import subprocess
        mock_run.side_effect = subprocess.SubprocessError("git failed")

        from opensepia.commands.run import check_workspace_git
        result = check_workspace_git(mock_config)
        assert result["initialized"] is True
        assert result["has_remote"] is False


class TestBuildPipeline:
    """Tests for build_pipeline helper."""

    def test_default_pipeline(self):
        from opensepia.commands.run import build_pipeline
        pipeline = build_pipeline()
        assert len(pipeline.steps) > 0

    def test_pipeline_with_agents(self):
        from opensepia.commands.run import build_pipeline
        pipeline = build_pipeline(agent_ids=["dev1", "dev2"])
        # agent_runner expands to init_standup + 3 steps per agent
        step_names = [type(s).__name__ for s in pipeline.steps]
        assert "InitStandupStep" in step_names
        assert "AgentStep" in step_names

    def test_pipeline_custom_steps(self):
        from opensepia.commands.run import build_pipeline
        config = {"pipeline": ["board_health", "cycle_log"]}
        pipeline = build_pipeline(agents_config=config)
        step_names = [type(s).__name__ for s in pipeline.steps]
        assert "BoardHealthStep" in step_names
        assert "CycleLogStep" in step_names
        assert len(pipeline.steps) == 2

    def test_pipeline_parameterized_step(self):
        from opensepia.commands.run import build_pipeline
        config = {"pipeline": ["run_agent:dev1"]}
        pipeline = build_pipeline(agents_config=config)
        step_names = [type(s).__name__ for s in pipeline.steps]
        assert "AgentStep" in step_names

    def test_pipeline_unknown_step_skipped(self):
        from opensepia.commands.run import build_pipeline
        config = {"pipeline": ["board_health", "nonexistent_step"]}
        pipeline = build_pipeline(agents_config=config)
        assert len(pipeline.steps) == 1

    def test_pipeline_unknown_parameterized_step_skipped(self):
        from opensepia.commands.run import build_pipeline
        config = {"pipeline": ["unknown_type:param"]}
        pipeline = build_pipeline(agents_config=config)
        assert len(pipeline.steps) == 0

    def test_pipeline_empty_agents(self):
        from opensepia.commands.run import build_pipeline
        pipeline = build_pipeline(agent_ids=[])
        step_names = [type(s).__name__ for s in pipeline.steps]
        # agent_runner with no agents should still produce InitStandupStep
        assert "InitStandupStep" in step_names


class TestCmdRun:
    """Tests for opensepia.commands.run.cmd_run."""

    @patch("opensepia.cycle_state.CycleState")
    @patch("opensepia.commands.run.build_pipeline")
    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.commands.run.ProcessLock")
    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_success(self, mock_load, mock_claude, mock_ready, mock_git,
                         mock_lock_cls, mock_ba, mock_build, mock_cs, mock_config):
        mock_load.return_value = mock_config
        mock_claude.return_value = True
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": True}

        lock_instance = MagicMock()
        mock_lock_cls.return_value = lock_instance

        adapter = MagicMock()
        mock_ba.return_value = adapter

        pipeline = MagicMock()
        ctx_result = MagicMock()
        ctx_result.errors = []
        pipeline.run.return_value = ctx_result
        mock_build.return_value = pipeline

        resume_state = MagicMock()
        resume_state.is_interrupted = False
        mock_cs.load.return_value = resume_state

        from opensepia.commands.run import cmd_run
        cmd_run(["dev-team"])

        lock_instance.acquire.assert_called_once()
        lock_instance.release.assert_called_once()
        pipeline.run.assert_called_once()

    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_config_error(self, mock_load):
        mock_load.side_effect = ConfigError("Missing config")

        from opensepia.commands.run import cmd_run
        with pytest.raises(SystemExit) as exc_info:
            cmd_run([])
        assert exc_info.value.code == 1

    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_invalid_mode(self, mock_load, mock_claude, mock_ready, mock_git, mock_config):
        mock_load.return_value = mock_config
        mock_claude.return_value = True
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": False}
        mock_config.resolve_agent_ids.side_effect = ConfigError("Unknown mode 'bogus'")

        from opensepia.commands.run import cmd_run
        with pytest.raises(SystemExit) as exc_info:
            cmd_run(["bogus"])
        assert exc_info.value.code == 1

    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_project_not_ready(self, mock_load, mock_claude, mock_config):
        mock_load.return_value = mock_config
        mock_claude.return_value = True

        with patch("opensepia.commands.run.check_project_ready", return_value=["Board not initialized"]):
            from opensepia.commands.run import cmd_run
            with pytest.raises(SystemExit) as exc_info:
                cmd_run(["dev-team"])
            assert exc_info.value.code == 1

    @patch("opensepia.cycle_state.CycleState")
    @patch("opensepia.commands.run.build_pipeline")
    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.commands.run.ProcessLock")
    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_project_not_ready_dry_run(self, mock_load, mock_claude, mock_ready, mock_git,
                                           mock_lock_cls, mock_ba, mock_build, mock_cs, mock_config):
        """Dry run should warn but not exit when project not ready."""
        mock_load.return_value = mock_config
        mock_claude.return_value = True
        mock_ready.return_value = ["Board not initialized"]
        mock_git.return_value = {"initialized": False}

        lock_instance = MagicMock()
        mock_lock_cls.return_value = lock_instance

        adapter = MagicMock()
        mock_ba.return_value = adapter

        pipeline = MagicMock()
        ctx_result = MagicMock()
        ctx_result.errors = []
        pipeline.run.return_value = ctx_result
        mock_build.return_value = pipeline

        resume_state = MagicMock()
        resume_state.is_interrupted = False
        mock_cs.load.return_value = resume_state

        from opensepia.commands.run import cmd_run
        cmd_run(["dev-team", "--dry-run"])

        # Should not have exited
        pipeline.run.assert_called_once()

    @patch("opensepia.cycle_state.CycleState")
    @patch("opensepia.commands.run.build_pipeline")
    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.commands.run.ProcessLock")
    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_lock_error(self, mock_load, mock_claude, mock_ready, mock_git,
                            mock_lock_cls, mock_ba, mock_build, mock_cs, mock_config):
        mock_load.return_value = mock_config
        mock_claude.return_value = True
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": False}

        lock_instance = MagicMock()
        lock_instance.acquire.side_effect = LockError("Already locked")
        mock_lock_cls.return_value = lock_instance

        from opensepia.commands.run import cmd_run
        with pytest.raises(SystemExit) as exc_info:
            cmd_run(["dev-team"])
        assert exc_info.value.code == 0  # LockError exits with 0

    @patch("opensepia.cycle_state.CycleState")
    @patch("opensepia.commands.run.build_pipeline")
    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.commands.run.ProcessLock")
    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_pipeline_error(self, mock_load, mock_claude, mock_ready, mock_git,
                                mock_lock_cls, mock_ba, mock_build, mock_cs, mock_config):
        mock_load.return_value = mock_config
        mock_claude.return_value = True
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": False}

        lock_instance = MagicMock()
        mock_lock_cls.return_value = lock_instance

        adapter = MagicMock()
        mock_ba.return_value = adapter

        resume_state = MagicMock()
        resume_state.is_interrupted = False
        mock_cs.load.return_value = resume_state

        pipeline = MagicMock()
        pipeline.run.side_effect = OrchestratorError("Pipeline exploded")
        mock_build.return_value = pipeline

        from opensepia.commands.run import cmd_run
        with pytest.raises(SystemExit) as exc_info:
            cmd_run(["dev-team"])
        assert exc_info.value.code == 1
        lock_instance.release.assert_called_once()

    @patch("opensepia.cycle_state.CycleState")
    @patch("opensepia.commands.run.build_pipeline")
    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.commands.run.ProcessLock")
    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_with_warnings(self, mock_load, mock_claude, mock_ready, mock_git,
                               mock_lock_cls, mock_ba, mock_build, mock_cs, mock_config, capsys):
        mock_load.return_value = mock_config
        mock_claude.return_value = True
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": False}

        lock_instance = MagicMock()
        mock_lock_cls.return_value = lock_instance

        adapter = MagicMock()
        mock_ba.return_value = adapter

        resume_state = MagicMock()
        resume_state.is_interrupted = False
        mock_cs.load.return_value = resume_state

        pipeline = MagicMock()
        ctx_result = MagicMock()
        ctx_result.errors = [OrchestratorError("minor issue")]
        pipeline.run.return_value = ctx_result
        mock_build.return_value = pipeline

        from opensepia.commands.run import cmd_run
        cmd_run(["dev-team"])

        captured = capsys.readouterr()
        assert "warning" in captured.out.lower()

    @patch("opensepia.cycle_state.CycleState")
    @patch("opensepia.commands.run.build_pipeline")
    @patch("opensepia.board_adapter.create_board_adapter")
    @patch("opensepia.commands.run.ProcessLock")
    @patch("opensepia.commands.run.check_workspace_git")
    @patch("opensepia.commands.run.check_project_ready")
    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_resume_interrupted(self, mock_load, mock_claude, mock_ready, mock_git,
                                    mock_lock_cls, mock_ba, mock_build, mock_cs, mock_config, capsys):
        mock_load.return_value = mock_config
        mock_claude.return_value = True
        mock_ready.return_value = []
        mock_git.return_value = {"initialized": False}

        lock_instance = MagicMock()
        mock_lock_cls.return_value = lock_instance

        adapter = MagicMock()
        mock_ba.return_value = adapter

        resume_state = MagicMock()
        resume_state.is_interrupted = True
        resume_state.cycle_id = "s1c3"
        resume_state.completed_steps = ["board_health", "sprint_check"]
        mock_cs.load.return_value = resume_state

        pipeline = MagicMock()
        ctx_result = MagicMock()
        ctx_result.errors = []
        pipeline.run.return_value = ctx_result
        mock_build.return_value = pipeline

        from opensepia.commands.run import cmd_run
        cmd_run(["dev-team"])

        captured = capsys.readouterr()
        assert "Resuming" in captured.out
        # Pipeline should receive resume_state
        pipeline.run.assert_called_once()
        call_kwargs = pipeline.run.call_args
        assert call_kwargs[1].get("resume_state") is resume_state or (len(call_kwargs[0]) > 1 and call_kwargs[0][1] is resume_state)

    @patch("opensepia.commands.run.check_claude_cli")
    @patch("opensepia.config.OrchestratorConfig.load")
    def test_run_no_claude_cli_warns(self, mock_load, mock_claude, mock_config, capsys):
        """Missing Claude CLI should warn but not fail."""
        mock_load.return_value = mock_config
        mock_claude.return_value = False

        with patch("opensepia.commands.run.check_project_ready", return_value=[]):
            with patch("opensepia.commands.run.check_workspace_git", return_value={"initialized": False}):
                with patch("opensepia.commands.run.ProcessLock") as mock_lock_cls:
                    lock_instance = MagicMock()
                    mock_lock_cls.return_value = lock_instance

                    with patch("opensepia.board_adapter.create_board_adapter") as mock_ba:
                        with patch("opensepia.commands.run.build_pipeline") as mock_build:
                            with patch("opensepia.cycle_state.CycleState") as mock_cs:
                                pipeline = MagicMock()
                                ctx_result = MagicMock()
                                ctx_result.errors = []
                                pipeline.run.return_value = ctx_result
                                mock_build.return_value = pipeline

                                resume_state = MagicMock()
                                resume_state.is_interrupted = False
                                mock_cs.load.return_value = resume_state

                                from opensepia.commands.run import cmd_run
                                cmd_run(["dev-team"])

        captured = capsys.readouterr()
        assert "Claude Code CLI" in captured.out or "not in PATH" in captured.out


# =============================================================================
# History command
# =============================================================================

class TestCmdHistory:
    """Tests for opensepia.commands.observe.cmd_history."""

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_history_no_logs(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_history
        cmd_history([])

        captured = capsys.readouterr()
        assert "No cycle history" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_history_nonexistent_dir(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "nonexistent"
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_history
        cmd_history([])

        captured = capsys.readouterr()
        assert "No cycle history" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_history_with_entries(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)

        log_data = {
            "timestamp": "2026-03-27T10:00:00",
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 1,
            "status": "ok",
            "agents_ok_count": 2,
            "agents_failed_count": 0,
            "agents_ok": ["po", "dev1"],
            "agents_failed": [],
            "agents": [],
        }
        (logs_dir / "cycle_20260327_100000.json").write_text(json.dumps(log_data))
        mock_dirs.return_value = (tool_dir, logs_dir)

        from opensepia.commands.observe import cmd_history
        cmd_history([])

        captured = capsys.readouterr()
        assert "Cycle History" in captured.out
        assert "S1C1" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_history_with_failures(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)

        log_data = {
            "timestamp": "2026-03-27T10:00:00",
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 1,
            "status": "error",
            "agents_ok_count": 1,
            "agents_failed_count": 1,
            "agents_ok": ["po"],
            "agents_failed": ["dev1"],
            "agents": [],
        }
        (logs_dir / "cycle_20260327_100000.json").write_text(json.dumps(log_data))
        mock_dirs.return_value = (tool_dir, logs_dir)

        # Enable verbose so log.detail output is visible
        import opensepia.log
        old_verbose = opensepia.log._verbose
        opensepia.log._verbose = True
        try:
            from opensepia.commands.observe import cmd_history
            cmd_history([])
        finally:
            opensepia.log._verbose = old_verbose

        captured = capsys.readouterr()
        assert "Failed" in captured.out
        assert "dev1" in captured.out

    @patch("opensepia.commands.observe._get_project_dirs")
    def test_history_with_detail(self, mock_dirs, tmp_path, capsys):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        logs_dir = tmp_path / "logs" / "runs"
        logs_dir.mkdir(parents=True)

        log_data = {
            "timestamp": "2026-03-27T10:00:00",
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 1,
            "status": "ok",
            "agents_ok_count": 1,
            "agents_failed_count": 0,
            "agents_ok": ["po"],
            "agents_failed": [],
            "agents": [{"agent": "po", "context_chars": 100, "response_chars": 50}],
        }
        (logs_dir / "cycle_20260327_100000.json").write_text(json.dumps(log_data))
        mock_dirs.return_value = (tool_dir, logs_dir)

        # Enable verbose for detail output
        import opensepia.log
        old_verbose = opensepia.log._verbose
        opensepia.log._verbose = True
        try:
            from opensepia.commands.observe import cmd_history
            cmd_history(["--detail"])
        finally:
            opensepia.log._verbose = old_verbose

        captured = capsys.readouterr()
        assert "po" in captured.out
