"""
AI Dev Team — Orchestrator error hierarchy.

All orchestrator errors inherit from OrchestratorError, allowing
the pipeline to distinguish critical from non-critical failures.
"""


class OrchestratorError(Exception):
    """Base error for all orchestrator operations."""
    pass


class ConfigError(OrchestratorError):
    """Missing or invalid configuration. Critical — aborts pipeline."""
    pass


class LockError(OrchestratorError):
    """Another orchestrator instance is already running."""
    pass


class BoardHealthError(OrchestratorError):
    """Board files missing or corrupt, restoration may have failed."""
    pass


class AgentError(OrchestratorError):
    """Agent invocation or output processing failure."""

    def __init__(self, agent_id: str, message: str, retryable: bool = True):
        self.agent_id = agent_id
        self.retryable = retryable
        super().__init__(f"Agent {agent_id}: {message}")


class AgentTimeoutError(AgentError):
    """Agent exceeded time limit."""

    def __init__(self, agent_id: str, timeout_seconds: int):
        super().__init__(agent_id, f"timeout after {timeout_seconds}s", retryable=True)


class AgentOutputError(AgentError):
    """Agent response could not be parsed."""

    def __init__(self, agent_id: str, detail: str):
        super().__init__(agent_id, f"output parse error: {detail}", retryable=False)


class GitSyncError(OrchestratorError):
    """Git operations (fetch, push, MR creation) failed."""
    pass


class ProviderError(OrchestratorError):
    """Board provider API call failed."""
    pass
