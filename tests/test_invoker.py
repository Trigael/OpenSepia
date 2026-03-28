"""Tests for agents/invoker.py — Claude Code CLI invocation."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from opensepia.agents.invoker import (
    call_claude_code,
    invoke_agent,
    _kill_process_group,
    AgentResult,
    AGENT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
)
from opensepia.config import DEFAULT_EXECUTION


# Helper: create a mock Popen process
def _mock_proc(stdout="ok", stderr="", returncode=0, pid=12345):
    proc = MagicMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.pid = pid
    return proc


# All call_claude_code tests need os.getpgid mocked (fake PID)
_POPEN_PATCH = "opensepia.agents.invoker.subprocess.Popen"
_GETPGID_PATCH = "opensepia.agents.invoker.os.getpgid"
_KILLPG_PATCH = "opensepia.agents.invoker._kill_process_group"


# =============================================================================
# Defaults are sourced from config.py
# =============================================================================

class TestDefaultsFromConfig:
    def test_timeout_matches_config(self):
        assert AGENT_TIMEOUT_SECONDS == DEFAULT_EXECUTION["timeout"]

    def test_max_retries_matches_config(self):
        assert DEFAULT_MAX_RETRIES == DEFAULT_EXECUTION["max_retries"]

    def test_retry_delay_matches_config(self):
        assert DEFAULT_RETRY_DELAY == DEFAULT_EXECUTION["retry_delay"]


# =============================================================================
# call_claude_code (uses subprocess.Popen with process groups)
# =============================================================================

class TestCallClaudeCode:
    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=12345)
    @patch(_POPEN_PATCH)
    def test_success(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        mock_popen.return_value = _mock_proc("Hello from Claude")
        result = call_claude_code("prompt text", tmp_path)
        assert result == "Hello from Claude"

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=12345)
    @patch(_POPEN_PATCH)
    def test_passes_correct_cmd(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        mock_popen.return_value = _mock_proc()
        call_claude_code("test", tmp_path)
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "claude"
        assert "--print" in cmd

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=12345)
    @patch(_POPEN_PATCH)
    def test_passes_allowed_tools(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        mock_popen.return_value = _mock_proc()
        call_claude_code("test", tmp_path, allowed_tools="Read,Grep")
        cmd = mock_popen.call_args[0][0]
        assert "Read,Grep" in cmd

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=12345)
    @patch(_POPEN_PATCH)
    def test_uses_cwd(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        mock_popen.return_value = _mock_proc()
        call_claude_code("p", tmp_path)
        assert mock_popen.call_args.kwargs["cwd"] == str(tmp_path)

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=12345)
    @patch(_POPEN_PATCH)
    def test_removes_claudecode_env(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        mock_popen.return_value = _mock_proc()
        with patch.dict("os.environ", {"CLAUDECODE": "1"}):
            call_claude_code("p", tmp_path)
        env = mock_popen.call_args.kwargs["env"]
        assert "CLAUDECODE" not in env

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=12345)
    @patch(_POPEN_PATCH)
    def test_nonzero_exit_raises(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        mock_popen.return_value = _mock_proc(returncode=1, stderr="error msg")
        with pytest.raises(RuntimeError, match="exit 1"):
            call_claude_code("p", tmp_path)

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=12345)
    @patch(_POPEN_PATCH)
    def test_start_new_session(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        mock_popen.return_value = _mock_proc()
        call_claude_code("p", tmp_path)
        assert mock_popen.call_args.kwargs["start_new_session"] is True

    # --- Process cleanup tests ---

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=99999)
    @patch(_POPEN_PATCH)
    def test_cleanup_on_success(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        """Process group is killed even on successful completion."""
        mock_popen.return_value = _mock_proc()
        call_claude_code("p", tmp_path)
        mock_killpg.assert_called_once_with(99999)

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=99999)
    @patch(_POPEN_PATCH)
    def test_cleanup_on_timeout(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        """Process group is killed on timeout."""
        proc = _mock_proc()
        proc.communicate.side_effect = subprocess.TimeoutExpired("claude", 900)
        mock_popen.return_value = proc
        with pytest.raises(subprocess.TimeoutExpired):
            call_claude_code("p", tmp_path)
        mock_killpg.assert_called_once_with(99999)

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, return_value=99999)
    @patch(_POPEN_PATCH)
    def test_cleanup_on_nonzero_exit(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        """Process group killed even when RuntimeError raised for non-zero exit."""
        mock_popen.return_value = _mock_proc(returncode=1, stderr="error")
        with pytest.raises(RuntimeError):
            call_claude_code("p", tmp_path)
        mock_killpg.assert_called_once_with(99999)

    @patch(_KILLPG_PATCH)
    @patch(_GETPGID_PATCH, side_effect=ProcessLookupError)
    @patch(_POPEN_PATCH)
    def test_cleanup_skipped_if_pgid_unavailable(self, mock_popen, mock_getpgid, mock_killpg, tmp_path):
        """If getpgid fails (process already dead), cleanup is skipped gracefully."""
        mock_popen.return_value = _mock_proc()
        call_claude_code("p", tmp_path)
        mock_killpg.assert_not_called()


# =============================================================================
# _kill_process_group
# =============================================================================

class TestKillProcessGroup:
    @patch("opensepia.agents.invoker.os.killpg")
    def test_sigterm_sufficient(self, mock_killpg):
        """If all processes die after SIGTERM, SIGKILL is not sent."""
        import signal
        # First call (SIGTERM) succeeds, probe raises (all dead)
        mock_killpg.side_effect = [None, ProcessLookupError]
        _kill_process_group(99999, grace_period=0.1)
        calls = mock_killpg.call_args_list
        assert calls[0] == call(99999, signal.SIGTERM)
        assert calls[1] == call(99999, 0)  # Probe

    @patch("opensepia.agents.invoker.time.monotonic")
    @patch("opensepia.agents.invoker.time.sleep")
    @patch("opensepia.agents.invoker.os.killpg")
    def test_sigkill_on_survivors(self, mock_killpg, mock_sleep, mock_monotonic):
        """If processes survive SIGTERM, SIGKILL is sent."""
        import signal
        # SIGTERM succeeds, probes succeed (alive), time advances past deadline
        mock_killpg.side_effect = [None, None, None]  # SIGTERM, probe, SIGKILL
        mock_monotonic.side_effect = [0.0, 0.0, 10.0]  # start, check, past deadline
        _kill_process_group(99999, grace_period=1.0)
        sigkill_calls = [c for c in mock_killpg.call_args_list if c == call(99999, signal.SIGKILL)]
        assert len(sigkill_calls) == 1

    @patch("opensepia.agents.invoker.os.killpg")
    def test_already_dead(self, mock_killpg):
        """If process group is already dead, returns immediately."""
        mock_killpg.side_effect = ProcessLookupError
        _kill_process_group(99999)  # Should not raise


# =============================================================================
# invoke_agent
# =============================================================================

class TestInvokeAgent:
    @patch("opensepia.agents.invoker.call_claude_code")
    def test_success_returns_result(self, mock_call, tmp_path):
        mock_call.return_value = "agent response text"
        result = invoke_agent("dev1", "context", tmp_path)
        assert isinstance(result, AgentResult)
        assert result.agent_id == "dev1"
        assert result.response == "agent response text"
        assert result.error is None

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_timeout_returns_error_result(self, mock_call, tmp_path):
        mock_call.side_effect = subprocess.TimeoutExpired("claude", 900)
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert result.error is not None
        assert "Timeout" in result.error

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_file_not_found_returns_error_result(self, mock_call, tmp_path):
        mock_call.side_effect = FileNotFoundError()
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert "not installed" in result.error

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_generic_exception_returns_error_result(self, mock_call, tmp_path):
        mock_call.side_effect = RuntimeError("something broke")
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert result.error == "something broke"

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_passes_allowed_tools(self, mock_call, tmp_path):
        mock_call.return_value = "ok"
        invoke_agent("dev1", "ctx", tmp_path, allowed_tools="Read,Grep")
        assert mock_call.call_args.kwargs["allowed_tools"] == "Read,Grep"
