"""Tests for agents/reaper.py — orphaned process cleanup."""

import os
import signal
from unittest.mock import patch, MagicMock

import pytest

from opensepia.agents.reaper import reap_orphaned_agents


class TestReaper:
    def test_no_proc_returns_zero(self):
        """Non-Linux systems without /proc return 0."""
        with patch("os.path.isdir", return_value=False):
            assert reap_orphaned_agents() == 0

    @patch("opensepia.agents.reaper._sigkill_survivors")
    @patch("opensepia.agents.reaper.time.sleep")
    @patch("os.kill")
    @patch("opensepia.agents.reaper._get_cmdline", return_value=b"python3 -m pytest tests/")
    @patch("opensepia.agents.reaper._get_ppid", return_value=1)
    @patch("os.stat")
    @patch("os.listdir", return_value=["1", "42", "100"])
    @patch("os.path.isdir", return_value=True)
    @patch("os.getpid", return_value=100)
    @patch("os.getuid", return_value=1000)
    def test_kills_orphaned_pytest(
        self, mock_uid, mock_pid, mock_isdir, mock_listdir,
        mock_stat, mock_ppid, mock_cmdline, mock_kill, mock_sleep, mock_sigkill,
    ):
        """Orphaned pytest process (PPID=1, matching cmdline) is killed."""
        mock_stat.return_value = MagicMock(st_uid=1000)
        # PID 100 is us (excluded), PID 42 should be killed
        count = reap_orphaned_agents(grace_period=0.01)
        assert count >= 1
        mock_kill.assert_called_with(42, signal.SIGTERM)

    @patch("os.kill")
    @patch("opensepia.agents.reaper._get_cmdline", return_value=b"python3 -m pytest tests/")
    @patch("opensepia.agents.reaper._get_ppid", return_value=5000)  # NOT orphaned
    @patch("os.stat")
    @patch("os.listdir", return_value=["42"])
    @patch("os.path.isdir", return_value=True)
    @patch("os.getpid", return_value=100)
    @patch("os.getuid", return_value=1000)
    def test_skips_non_orphans(
        self, mock_uid, mock_pid, mock_isdir, mock_listdir,
        mock_stat, mock_ppid, mock_cmdline, mock_kill,
    ):
        """Processes with PPID != 1 are not killed."""
        mock_stat.return_value = MagicMock(st_uid=1000)
        count = reap_orphaned_agents()
        assert count == 0
        mock_kill.assert_not_called()

    @patch("os.kill")
    @patch("opensepia.agents.reaper._get_ppid", return_value=1)
    @patch("os.stat")
    @patch("os.listdir", return_value=["42"])
    @patch("os.path.isdir", return_value=True)
    @patch("os.getpid", return_value=100)
    @patch("os.getuid", return_value=1000)
    def test_skips_other_users(
        self, mock_uid, mock_pid, mock_isdir, mock_listdir,
        mock_stat, mock_ppid, mock_kill,
    ):
        """Processes owned by different user are not killed."""
        mock_stat.return_value = MagicMock(st_uid=9999)  # Different user
        count = reap_orphaned_agents()
        assert count == 0
        mock_kill.assert_not_called()

    @patch("os.kill")
    @patch("opensepia.agents.reaper._get_cmdline", return_value=b"/usr/bin/nginx")
    @patch("opensepia.agents.reaper._get_ppid", return_value=1)
    @patch("os.stat")
    @patch("os.listdir", return_value=["42"])
    @patch("os.path.isdir", return_value=True)
    @patch("os.getpid", return_value=100)
    @patch("os.getuid", return_value=1000)
    def test_skips_non_matching_cmdline(
        self, mock_uid, mock_pid, mock_isdir, mock_listdir,
        mock_stat, mock_ppid, mock_cmdline, mock_kill,
    ):
        """Processes with non-matching cmdline are not killed."""
        mock_stat.return_value = MagicMock(st_uid=1000)
        count = reap_orphaned_agents()
        assert count == 0
        mock_kill.assert_not_called()
