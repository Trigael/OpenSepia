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
# call_claude_code
# =============================================================================

class TestCallClaudeCode:
    @patch("opensepia.agents.invoker.subprocess.run")
    def test_success(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="Hello from Claude")
        result = call_claude_code("prompt text", tmp_path)
        assert result == "Hello from Claude"

    @patch("opensepia.agents.invoker.subprocess.run")
    def test_passes_correct_cmd(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")
        call_claude_code("test", tmp_path)
        args = mock_run.call_args
        cmd = args[0][0]
        assert cmd[0] == "claude"
        assert "--print" in cmd

    @patch("opensepia.agents.invoker.subprocess.run")
    def test_passes_prompt_as_stdin(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")
        call_claude_code("my prompt", tmp_path)
        assert mock_run.call_args.kwargs["input"] == "my prompt"

    @patch("opensepia.agents.invoker.subprocess.run")
    def test_uses_cwd(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")
        call_claude_code("p", tmp_path)
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)

    @patch("opensepia.agents.invoker.subprocess.run")
    def test_removes_claudecode_env(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")
        with patch.dict("os.environ", {"CLAUDECODE": "1"}):
            call_claude_code("p", tmp_path)
        env = mock_run.call_args.kwargs["env"]
        assert "CLAUDECODE" not in env

    @patch("opensepia.agents.invoker.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stderr="error msg")
        with pytest.raises(RuntimeError, match="exit 1"):
            call_claude_code("p", tmp_path)

    @patch("opensepia.agents.invoker.subprocess.run")
    def test_custom_timeout(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")
        call_claude_code("p", tmp_path, timeout=42)
        assert mock_run.call_args.kwargs["timeout"] == 42


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
