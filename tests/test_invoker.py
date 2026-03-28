"""Tests for agents/invoker.py — Claude Code CLI invocation."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from opensepia.agents.invoker import (
    call_claude_code,
    invoke_agent,
    AgentResult,
    AGENT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
)
from opensepia.config import DEFAULT_EXECUTION


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
    @patch("opensepia.agents.invoker.subprocess.Popen")
    def test_success(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.communicate.return_value = ("Hello from Claude", "")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc
        result = call_claude_code("prompt text", tmp_path)
        assert result == "Hello from Claude"

    @patch("opensepia.agents.invoker.subprocess.Popen")
    def test_passes_correct_cmd(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.communicate.return_value = ("ok", "")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc
        call_claude_code("test", tmp_path)
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "claude"
        assert "--print" in cmd

    @patch("opensepia.agents.invoker.subprocess.Popen")
    def test_passes_allowed_tools(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.communicate.return_value = ("ok", "")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc
        call_claude_code("test", tmp_path, allowed_tools="Read,Grep")
        cmd = mock_popen.call_args[0][0]
        assert "Read,Grep" in cmd

    @patch("opensepia.agents.invoker.subprocess.Popen")
    def test_uses_cwd(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.communicate.return_value = ("ok", "")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc
        call_claude_code("p", tmp_path)
        assert mock_popen.call_args.kwargs["cwd"] == str(tmp_path)

    @patch("opensepia.agents.invoker.subprocess.Popen")
    def test_removes_claudecode_env(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.communicate.return_value = ("ok", "")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc
        with patch.dict("os.environ", {"CLAUDECODE": "1"}):
            call_claude_code("p", tmp_path)
        env = mock_popen.call_args.kwargs["env"]
        assert "CLAUDECODE" not in env

    @patch("opensepia.agents.invoker.subprocess.Popen")
    def test_nonzero_exit_raises(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.communicate.return_value = ("", "error msg")
        proc.returncode = 1
        proc.pid = 12345
        mock_popen.return_value = proc
        with pytest.raises(RuntimeError, match="exit 1"):
            call_claude_code("p", tmp_path)

    @patch("opensepia.agents.invoker.subprocess.Popen")
    def test_start_new_session(self, mock_popen, tmp_path):
        """Process group isolation — start_new_session enables killpg on timeout."""
        proc = MagicMock()
        proc.communicate.return_value = ("ok", "")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc
        call_claude_code("p", tmp_path)
        assert mock_popen.call_args.kwargs["start_new_session"] is True


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
        assert result.context_size == len("context")
        assert result.response_size == len("agent response text")

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_uses_agent_name(self, mock_call, tmp_path):
        mock_call.return_value = "ok"
        result = invoke_agent("dev1", "ctx", tmp_path, agent_name="Developer 1")
        assert result.agent_name == "Developer 1"

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_defaults_agent_name_to_id(self, mock_call, tmp_path):
        mock_call.return_value = "ok"
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert result.agent_name == "dev1"

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_timeout_returns_error_result(self, mock_call, tmp_path):
        mock_call.side_effect = subprocess.TimeoutExpired("claude", 900)
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert result.error is not None
        assert "Timeout" in result.error
        assert result.response_size == 0

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_file_not_found_returns_error_result(self, mock_call, tmp_path):
        mock_call.side_effect = FileNotFoundError()
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert result.error is not None
        assert "not installed" in result.error

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_generic_exception_returns_error_result(self, mock_call, tmp_path):
        mock_call.side_effect = RuntimeError("something broke")
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert result.error == "something broke"

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_timestamp_is_set(self, mock_call, tmp_path):
        mock_call.return_value = "ok"
        result = invoke_agent("dev1", "ctx", tmp_path)
        assert result.timestamp  # Non-empty ISO string

    @patch("opensepia.agents.invoker.call_claude_code")
    def test_passes_allowed_tools(self, mock_call, tmp_path):
        mock_call.return_value = "ok"
        invoke_agent("dev1", "ctx", tmp_path, allowed_tools="Read,Grep")
        assert mock_call.call_args.kwargs["allowed_tools"] == "Read,Grep"
