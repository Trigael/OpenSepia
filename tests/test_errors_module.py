"""Tests for opensepia/errors.py — Error hierarchy."""

import pytest

from opensepia.errors import (
    OrchestratorError,
    ConfigError,
    LockError,
    BoardHealthError,
    AgentError,
    AgentTimeoutError,
    AgentOutputError,
    GitSyncError,
    ProviderError,
)


class TestErrorHierarchy:
    def test_all_inherit_from_orchestrator_error(self):
        assert issubclass(ConfigError, OrchestratorError)
        assert issubclass(LockError, OrchestratorError)
        assert issubclass(BoardHealthError, OrchestratorError)
        assert issubclass(AgentError, OrchestratorError)
        assert issubclass(AgentTimeoutError, OrchestratorError)
        assert issubclass(AgentOutputError, OrchestratorError)
        assert issubclass(GitSyncError, OrchestratorError)
        assert issubclass(ProviderError, OrchestratorError)

    def test_agent_timeout_inherits_agent_error(self):
        assert issubclass(AgentTimeoutError, AgentError)

    def test_agent_output_inherits_agent_error(self):
        assert issubclass(AgentOutputError, AgentError)


class TestAgentError:
    def test_stores_agent_id(self):
        err = AgentError("dev1", "something broke")
        assert err.agent_id == "dev1"

    def test_stores_retryable(self):
        err = AgentError("dev1", "msg", retryable=False)
        assert err.retryable is False

    def test_default_retryable_true(self):
        err = AgentError("dev1", "msg")
        assert err.retryable is True

    def test_message_format(self):
        err = AgentError("dev1", "something broke")
        assert str(err) == "Agent dev1: something broke"


class TestAgentTimeoutError:
    def test_stores_timeout(self):
        err = AgentTimeoutError("dev1", 900)
        assert "timeout" in str(err)
        assert "900s" in str(err)
        assert err.agent_id == "dev1"
        assert err.retryable is True


class TestAgentOutputError:
    def test_stores_detail(self):
        err = AgentOutputError("dev1", "missing FILES section")
        assert "output parse error" in str(err)
        assert "missing FILES section" in str(err)
        assert err.agent_id == "dev1"
        assert err.retryable is False


class TestSimpleErrors:
    def test_config_error(self):
        err = ConfigError("missing agents.yaml")
        assert str(err) == "missing agents.yaml"

    def test_lock_error(self):
        err = LockError("already running")
        assert str(err) == "already running"

    def test_board_health_error(self):
        err = BoardHealthError("sprint.md missing")
        assert str(err) == "sprint.md missing"

    def test_git_sync_error(self):
        err = GitSyncError("push failed")
        assert str(err) == "push failed"

    def test_provider_error(self):
        err = ProviderError("API returned 500")
        assert str(err) == "API returned 500"

    def test_catchable_as_base(self):
        with pytest.raises(OrchestratorError):
            raise ConfigError("test")
