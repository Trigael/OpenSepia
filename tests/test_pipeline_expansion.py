"""Tests for pipeline builder expansion — agent_runner → per-agent steps."""

from pathlib import Path

from opensepia.commands.run import build_pipeline
from opensepia.steps.agent_step import AgentStep, AgentCommitStep, AgentSyncStep, InitStandupStep


def _minimal_config(pipeline=None):
    """Create minimal agents.yaml-like config."""
    cfg = {
        "agents": {
            "po": {"name": "PO", "color": "P", "system_prompt": "PO"},
            "dev1": {"name": "Dev1", "color": "D", "system_prompt": "Dev1"},
            "tester": {"name": "Tester", "color": "T", "system_prompt": "Tester"},
        },
        "global": {},
    }
    if pipeline:
        cfg["pipeline"] = pipeline
    return cfg


class TestAgentRunnerExpansion:
    """agent_runner in YAML expands to per-agent triplets."""

    def test_agent_runner_expands_to_per_agent_steps(self):
        config = _minimal_config(["agent_runner"])
        pipeline = build_pipeline(config, agent_ids=["po", "dev1", "tester"])

        step_names = [s.name for s in pipeline.steps]
        assert "init_standup" in step_names
        assert "run_agent:po" in step_names
        assert "commit:po" in step_names
        assert "sync:po" in step_names
        assert "run_agent:dev1" in step_names
        assert "run_agent:tester" in step_names

    def test_expansion_preserves_agent_order(self):
        config = _minimal_config(["agent_runner"])
        pipeline = build_pipeline(config, agent_ids=["po", "dev1", "tester"])

        step_names = [s.name for s in pipeline.steps]
        po_idx = step_names.index("run_agent:po")
        dev1_idx = step_names.index("run_agent:dev1")
        tester_idx = step_names.index("run_agent:tester")
        assert po_idx < dev1_idx < tester_idx

    def test_each_agent_gets_triplet(self):
        config = _minimal_config(["agent_runner"])
        pipeline = build_pipeline(config, agent_ids=["po", "dev1"])

        step_names = [s.name for s in pipeline.steps]
        # PO triplet
        po_run = step_names.index("run_agent:po")
        po_commit = step_names.index("commit:po")
        po_sync = step_names.index("sync:po")
        assert po_run < po_commit < po_sync

        # Dev1 triplet
        dev1_run = step_names.index("run_agent:dev1")
        dev1_commit = step_names.index("commit:dev1")
        dev1_sync = step_names.index("sync:dev1")
        assert dev1_run < dev1_commit < dev1_sync

        # PO before Dev1
        assert po_sync < dev1_run

    def test_expansion_with_surrounding_steps(self):
        config = _minimal_config(["board_health", "agent_runner", "cycle_log"])
        pipeline = build_pipeline(config, agent_ids=["po"])

        step_names = [s.name for s in pipeline.steps]
        assert step_names[0] == "board_health"
        assert "init_standup" in step_names
        assert "run_agent:po" in step_names
        assert step_names[-1] == "cycle_log"


class TestParameterizedSteps:
    """Explicit parameterized step syntax: run_agent:dev1, commit:dev1, etc."""

    def test_run_agent_syntax(self):
        config = _minimal_config(["run_agent:po", "run_agent:dev1"])
        pipeline = build_pipeline(config, agent_ids=["po", "dev1"])

        step_names = [s.name for s in pipeline.steps]
        assert "run_agent:po" in step_names
        assert "run_agent:dev1" in step_names
        assert isinstance(pipeline.steps[0], AgentStep)

    def test_commit_syntax(self):
        config = _minimal_config(["commit:dev1"])
        pipeline = build_pipeline(config, agent_ids=["dev1"])
        assert isinstance(pipeline.steps[0], AgentCommitStep)

    def test_sync_syntax(self):
        config = _minimal_config(["sync:po"])
        pipeline = build_pipeline(config, agent_ids=["po"])
        assert isinstance(pipeline.steps[0], AgentSyncStep)

    def test_mixed_syntax(self):
        config = _minimal_config([
            "board_health",
            "init_standup",
            "run_agent:po",
            "sync:po",
            "run_agent:dev1",
            "commit:dev1",
            "cycle_log",
        ])
        pipeline = build_pipeline(config, agent_ids=["po", "dev1"])

        step_names = [s.name for s in pipeline.steps]
        assert step_names == [
            "board_health", "init_standup",
            "run_agent:po", "sync:po",
            "run_agent:dev1", "commit:dev1",
            "cycle_log",
        ]


class TestBackwardCompat:
    """Old configs still work identically."""

    def test_default_pipeline_still_works(self):
        config = _minimal_config()  # No pipeline key → use defaults
        pipeline = build_pipeline(config, agent_ids=["po"])
        step_names = [s.name for s in pipeline.steps]
        # Should have board_health and eventually run_agent:po
        assert "board_health" in step_names
        assert "run_agent:po" in step_names

    def test_git_sync_alias(self):
        config = _minimal_config(["git_sync"])
        pipeline = build_pipeline(config, agent_ids=[])
        assert len(pipeline.steps) == 1
