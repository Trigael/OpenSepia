"""Tests for spawned agent pipeline integration."""

import yaml

from opensepia.config import OrchestratorConfig
from opensepia.commands.run import build_pipeline
from opensepia.steps.agent_step import AgentStep, AgentCommitStep, AgentSyncStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_AGENTS = {
    "agents": {
        "dev1": {"name": "Dev 1", "color": "blue", "system_prompt": "You are dev1."},
    },
    "modes": {
        "dev-team": {"agents": ["dev1"]},
    },
}


def _write_config(tmp_path, agents=None):
    """Write minimal config files and return an OrchestratorConfig."""
    # tool_dir layout: tmp_path/config/agents.yaml
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    agents_yaml = agents or MINIMAL_AGENTS
    (config_dir / "agents.yaml").write_text(yaml.dump(agents_yaml))

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    board_dir = project_dir / "board"
    board_dir.mkdir()
    (board_dir / "sprint.md").write_text("# Sprint 1\n")
    (project_dir / "workspace").mkdir()
    (project_dir / "project.yaml").write_text(
        yaml.dump({"name": "test", "sprint": {"current": 1, "cycle": 1}})
    )

    return OrchestratorConfig.load(
        tool_dir=tmp_path, project_dir=project_dir
    )


def _write_registry(board_dir, agents_dict):
    """Write an evolution registry.yaml under board_dir."""
    evo_dir = board_dir / "evolution"
    evo_dir.mkdir(parents=True, exist_ok=True)
    (evo_dir / "registry.yaml").write_text(yaml.dump({"agents": agents_dict}))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetSpawnedAgentIds:
    """Unit tests for OrchestratorConfig.get_spawned_agent_ids()."""

    def test_no_registry_returns_empty(self, tmp_path):
        config = _write_config(tmp_path)
        assert config.get_spawned_agent_ids() == []

    def test_active_agent_returned(self, tmp_path):
        config = _write_config(tmp_path)
        _write_registry(config.board_dir, {
            "specialist-1": {"name": "Spec", "status": "active"},
        })
        assert config.get_spawned_agent_ids() == ["specialist-1"]

    def test_inactive_agent_excluded(self, tmp_path):
        config = _write_config(tmp_path)
        _write_registry(config.board_dir, {
            "spec-a": {"name": "A", "status": "active"},
            "spec-b": {"name": "B", "status": "inactive"},
        })
        ids = config.get_spawned_agent_ids()
        assert "spec-a" in ids
        assert "spec-b" not in ids

    def test_empty_registry(self, tmp_path):
        config = _write_config(tmp_path)
        _write_registry(config.board_dir, {})
        assert config.get_spawned_agent_ids() == []

    def test_malformed_registry_returns_empty(self, tmp_path):
        config = _write_config(tmp_path)
        evo_dir = config.board_dir / "evolution"
        evo_dir.mkdir(parents=True)
        (evo_dir / "registry.yaml").write_text("not: [valid: yaml: {{")
        assert config.get_spawned_agent_ids() == []


class TestBuildPipelineWithSpawnedAgents:
    """Tests that build_pipeline includes steps for spawned agents."""

    def test_spawned_agent_in_pipeline(self):
        """Pipeline includes steps for both base and spawned agents."""
        agent_ids = ["dev1", "specialist-1"]
        pipeline = build_pipeline(agent_ids=agent_ids)

        agent_step_ids = [
            s.agent_id for s in pipeline.steps if isinstance(s, AgentStep)
        ]
        assert "dev1" in agent_step_ids
        assert "specialist-1" in agent_step_ids

    def test_no_spawned_agents_backward_compat(self):
        """Without spawned agents, pipeline has only base agent steps."""
        agent_ids = ["dev1"]
        pipeline = build_pipeline(agent_ids=agent_ids)

        agent_step_ids = [
            s.agent_id for s in pipeline.steps if isinstance(s, AgentStep)
        ]
        assert agent_step_ids == ["dev1"]

    def test_spawned_agent_gets_full_triplet(self):
        """Each agent (including spawned) gets run/commit/sync steps."""
        agent_ids = ["dev1", "specialist-1"]
        pipeline = build_pipeline(agent_ids=agent_ids)

        for aid in agent_ids:
            run_steps = [s for s in pipeline.steps if isinstance(s, AgentStep) and s.agent_id == aid]
            commit_steps = [s for s in pipeline.steps if isinstance(s, AgentCommitStep) and s.agent_id == aid]
            sync_steps = [s for s in pipeline.steps if isinstance(s, AgentSyncStep) and s.agent_id == aid]
            assert len(run_steps) == 1, f"Expected 1 AgentStep for {aid}"
            assert len(commit_steps) == 1, f"Expected 1 AgentCommitStep for {aid}"
            assert len(sync_steps) == 1, f"Expected 1 AgentSyncStep for {aid}"


class TestSpawnedAgentIntegration:
    """Integration: config.get_spawned_agent_ids() feeds into the pipeline."""

    def test_end_to_end_spawned_wiring(self, tmp_path):
        """Active spawned agent from registry ends up in resolved agent_ids."""
        config = _write_config(tmp_path)
        _write_registry(config.board_dir, {
            "specialist-1": {"name": "Specialist", "status": "active"},
        })

        agent_ids = config.resolve_agent_ids("dev-team")
        spawned = config.get_spawned_agent_ids()
        agent_ids = agent_ids + [aid for aid in spawned if aid not in agent_ids]

        assert "dev1" in agent_ids
        assert "specialist-1" in agent_ids

        pipeline = build_pipeline(config.agents, agent_ids=agent_ids)
        agent_step_ids = [
            s.agent_id for s in pipeline.steps if isinstance(s, AgentStep)
        ]
        assert "specialist-1" in agent_step_ids

    def test_no_registry_no_change(self, tmp_path):
        """Without a registry, resolved agent_ids are unchanged."""
        config = _write_config(tmp_path)

        agent_ids = config.resolve_agent_ids("dev-team")
        spawned = config.get_spawned_agent_ids()
        agent_ids = agent_ids + [aid for aid in spawned if aid not in agent_ids]

        assert agent_ids == ["dev1"]

    def test_duplicate_not_added_twice(self, tmp_path):
        """If a spawned agent ID matches an existing one, no duplicate."""
        config = _write_config(tmp_path)
        _write_registry(config.board_dir, {
            "dev1": {"name": "Dev 1 clone", "status": "active"},
        })

        agent_ids = config.resolve_agent_ids("dev-team")
        spawned = config.get_spawned_agent_ids()
        agent_ids = agent_ids + [aid for aid in spawned if aid not in agent_ids]

        assert agent_ids.count("dev1") == 1
