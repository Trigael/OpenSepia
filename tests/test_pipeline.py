"""Tests for orchestrator/pipeline.py — step execution and error handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from opensepia.pipeline import Pipeline, PipelineContext
from opensepia.errors import OrchestratorError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(**kwargs) -> PipelineContext:
    """Create a minimal PipelineContext for testing."""
    defaults = dict(
        mode="test",
        project_dir=Path("/tmp/test"),
        agents_config={"agents": {}, "global": {}},
        project_config={"sprint": {"current_sprint": 1, "current_cycle": 0}},
        board_dir=Path("/tmp/test/board"),
        workspace_dir=Path("/tmp/test/workspace"),
        config_dir=Path("/tmp/test/config"),
        logs_dir=Path("/tmp/test/logs/runs"),
    )
    defaults.update(kwargs)
    return PipelineContext(**defaults)


class _PassStep:
    """Step that passes and records execution."""
    def __init__(self, step_name="pass", critical=False):
        self.name = step_name
        self.critical = critical
        self.executed = False

    def execute(self, ctx):
        self.executed = True
        return ctx


class _FailStep:
    """Step that raises OrchestratorError."""
    def __init__(self, step_name="fail", critical=False, message="test error"):
        self.name = step_name
        self.critical = critical
        self.message = message

    def execute(self, ctx):
        raise OrchestratorError(self.message)


class _MutateStep:
    """Step that modifies context."""
    def __init__(self, key, value):
        self.name = "mutate"
        self.critical = False
        self._key = key
        self._value = value

    def execute(self, ctx):
        setattr(ctx, self._key, self._value)
        return ctx


# ---------------------------------------------------------------------------
# Pipeline.run
# ---------------------------------------------------------------------------

def test_pipeline_runs_all_steps():
    s1 = _PassStep("step1")
    s2 = _PassStep("step2")
    s3 = _PassStep("step3")

    pipeline = Pipeline([s1, s2, s3])
    ctx = _make_ctx()
    pipeline.run(ctx)

    assert s1.executed
    assert s2.executed
    assert s3.executed


def test_pipeline_non_critical_failure_continues():
    s1 = _PassStep("step1")
    s2 = _FailStep("step2", critical=False)
    s3 = _PassStep("step3")

    pipeline = Pipeline([s1, s2, s3])
    ctx = _make_ctx()
    result = pipeline.run(ctx)

    assert s1.executed
    assert s3.executed  # Should still run after non-critical failure
    assert len(result.errors) == 1
    assert "test error" in str(result.errors[0])


def test_pipeline_critical_failure_aborts():
    s1 = _PassStep("step1")
    s2 = _FailStep("step2", critical=True)
    s3 = _PassStep("step3")

    pipeline = Pipeline([s1, s2, s3])
    ctx = _make_ctx()

    try:
        pipeline.run(ctx)
        assert False, "Should have raised OrchestratorError"
    except OrchestratorError:
        pass

    assert s1.executed
    assert not s3.executed  # Should NOT run after critical failure


def test_pipeline_context_flows_through_steps():
    s1 = _MutateStep("agents_ok", True)
    s2 = _MutateStep("cycle_num", 42)

    pipeline = Pipeline([s1, s2])
    ctx = _make_ctx()
    result = pipeline.run(ctx)

    assert result.agents_ok is True
    assert result.cycle_num == 42


def test_pipeline_empty_steps():
    pipeline = Pipeline([])
    ctx = _make_ctx()
    result = pipeline.run(ctx)
    assert result.errors == []


def test_pipeline_multiple_non_critical_failures():
    s1 = _FailStep("fail1", critical=False, message="error1")
    s2 = _FailStep("fail2", critical=False, message="error2")
    s3 = _PassStep("pass1")

    pipeline = Pipeline([s1, s2, s3])
    ctx = _make_ctx()
    result = pipeline.run(ctx)

    assert len(result.errors) == 2
    assert s3.executed


def test_pipeline_unexpected_exception_non_critical():
    """Non-OrchestratorError exceptions should be wrapped."""
    class _RaiseStep:
        name = "unexpected"
        critical = False
        def execute(self, ctx):
            raise ValueError("something unexpected")

    s1 = _RaiseStep()
    s2 = _PassStep("after")

    pipeline = Pipeline([s1, s2])
    ctx = _make_ctx()
    result = pipeline.run(ctx)

    assert len(result.errors) == 1
    assert "unexpected" in str(result.errors[0])
    assert s2.executed


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------

def test_pipeline_context_defaults():
    ctx = _make_ctx()
    assert ctx.agent_ids == []
    assert ctx.agent_results == []
    assert ctx.agents_ok is False
    assert ctx.skip_agents is False
    assert ctx.errors == []
    assert ctx.verbose is False
    assert ctx.dry_run is False
