"""Tests for EvolutionStep splitting analysis integration.

Verifies that EvolutionStep.execute() runs over-generalization detection
via AgentSplitter after processing proposals, and creates split proposal
YAML files in pending/ when triggered.
"""

import yaml
import pytest
from pathlib import Path
from unittest.mock import patch

from opensepia.pipeline import PipelineContext
from opensepia.steps.evolution_step import EvolutionStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path, **overrides):
    """Create a PipelineContext with evolution enabled."""
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    board_dir = project_dir / "board"
    board_dir.mkdir(exist_ok=True)
    workspace_dir = project_dir / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    logs_dir = project_dir / "logs" / "runs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)

    # Create evolution directory structure
    evo_dir = board_dir / "evolution"
    evo_dir.mkdir(exist_ok=True)
    (evo_dir / "proposals" / "pending").mkdir(parents=True, exist_ok=True)
    (evo_dir / "memory").mkdir(parents=True, exist_ok=True)

    defaults = dict(
        mode="dev-team",
        tool_dir=tmp_path,
        project_dir=project_dir,
        agents_config={
            "agents": {"dev1": {"name": "Dev1"}},
            "evolution": {"enabled": True, "auto_approve": {}},
        },
        project_config={"sprint": {"current_sprint": 1, "current_cycle": 3}},
        board_dir=board_dir,
        workspace_dir=workspace_dir,
        config_dir=config_dir,
        logs_dir=logs_dir,
        sprint_num=1,
        cycle_num=3,
        agent_ids=["dev1"],
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


def _write_diverse_memory(board_dir: Path, agent_id: str) -> None:
    """Write memory content spanning many domains for an agent."""
    memory_dir = board_dir / "evolution" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "- [S1C1] Built React component with hooks and tailwind css\n"
        "- [S1C2] Wrote SQLAlchemy migration for users table with postgresql\n"
        "- [S1C3] Fixed Docker compose networking and nginx config\n"
        "- [S1C4] Added pytest fixtures for API integration tests\n"
        "- [S2C1] Configured kubernetes deployment with ci cd pipeline\n"
        "- [S2C2] Built Vue frontend dashboard with javascript\n"
    )
    (memory_dir / f"{agent_id}.md").write_text(content, encoding="utf-8")


def _diverse_agent_result(agent_id: str) -> dict:
    """Return an agent result with diverse file paths and overload signal."""
    return {
        "agent_id": agent_id,
        "agent_name": agent_id,
        "response": (
            "I'm handling too many responsibilities.\n"
            "path: src/frontend/App.tsx\n"
            "path: src/backend/api.py\n"
            "path: docker/Dockerfile\n"
            "path: tests/test_api.py\n"
            "path: nginx/nginx.conf\n"
        ),
    }


def _focused_agent_result(agent_id: str) -> dict:
    """Return an agent result focused on a single domain."""
    return {
        "agent_id": agent_id,
        "agent_name": agent_id,
        "response": (
            "path: src/api/routes.py\n"
            "path: src/api/models.py\n"
            "Implemented FastAPI endpoint for user registration.\n"
        ),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEvolutionStepSplitting:
    """Test that EvolutionStep wires splitting analysis correctly."""

    def test_split_proposal_created_for_diverse_agent(self, tmp_path):
        """A diverse agent triggers a split proposal YAML in pending/."""
        ctx = _make_ctx(tmp_path)
        _write_diverse_memory(ctx.board_dir, "dev1")
        ctx.agent_results = [_diverse_agent_result("dev1")]

        step = EvolutionStep()
        step.execute(ctx)

        pending_dir = ctx.board_dir / "evolution" / "proposals" / "pending"
        proposals = list(pending_dir.glob("*_split.yaml"))
        assert len(proposals) >= 1, "Expected at least one split proposal"

        data = yaml.safe_load(proposals[0].read_text(encoding="utf-8"))
        assert data["type"] == "split_agent"
        assert data["details"]["original_id"] == "dev1"
        assert len(data["details"]["into"]) >= 2
        assert data["sprint"] == 1
        assert data["cycle"] == 3

    def test_no_split_for_focused_agent(self, tmp_path):
        """A focused agent does not trigger a split proposal."""
        ctx = _make_ctx(tmp_path)
        # Write focused memory (single domain)
        memory_dir = ctx.board_dir / "evolution" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "dev1.md").write_text(
            "- [S1C1] Learned FastAPI routing\n"
            "- [S1C2] Fixed API endpoint validation\n",
            encoding="utf-8",
        )
        ctx.agent_results = [_focused_agent_result("dev1")]

        step = EvolutionStep()
        step.execute(ctx)

        pending_dir = ctx.board_dir / "evolution" / "proposals" / "pending"
        proposals = list(pending_dir.glob("*_split.yaml"))
        assert len(proposals) == 0, "Focused agent should not trigger split"

    def test_no_op_when_evolution_disabled(self, tmp_path):
        """With evolution disabled, no splitting analysis runs."""
        ctx = _make_ctx(
            tmp_path,
            agents_config={
                "agents": {"dev1": {"name": "Dev1"}},
                "evolution": {"enabled": False},
            },
        )
        _write_diverse_memory(ctx.board_dir, "dev1")
        ctx.agent_results = [_diverse_agent_result("dev1")]

        step = EvolutionStep()
        step.execute(ctx)

        pending_dir = ctx.board_dir / "evolution" / "proposals" / "pending"
        proposals = list(pending_dir.glob("*_split.yaml"))
        assert len(proposals) == 0, "Evolution disabled should skip splitting"

    def test_no_op_when_no_agent_results(self, tmp_path):
        """No agent results means no splitting analysis."""
        ctx = _make_ctx(tmp_path)
        ctx.agent_results = []

        step = EvolutionStep()
        step.execute(ctx)

        pending_dir = ctx.board_dir / "evolution" / "proposals" / "pending"
        proposals = list(pending_dir.glob("*_split.yaml"))
        assert len(proposals) == 0

    def test_no_op_on_dry_run(self, tmp_path):
        """Dry run skips the entire evolution step including splitting."""
        ctx = _make_ctx(tmp_path, dry_run=True)
        _write_diverse_memory(ctx.board_dir, "dev1")
        ctx.agent_results = [_diverse_agent_result("dev1")]

        step = EvolutionStep()
        step.execute(ctx)

        pending_dir = ctx.board_dir / "evolution" / "proposals" / "pending"
        proposals = list(pending_dir.glob("*_split.yaml"))
        assert len(proposals) == 0

    def test_splitting_uses_agent_id_fallback_to_agent_name(self, tmp_path):
        """If agent_id is missing, falls back to agent_name."""
        ctx = _make_ctx(tmp_path)
        _write_diverse_memory(ctx.board_dir, "dev1")
        result = _diverse_agent_result("dev1")
        del result["agent_id"]  # Remove agent_id, keep agent_name
        ctx.agent_results = [result]

        step = EvolutionStep()
        step.execute(ctx)

        pending_dir = ctx.board_dir / "evolution" / "proposals" / "pending"
        proposals = list(pending_dir.glob("*_split.yaml"))
        assert len(proposals) >= 1

    def test_splitting_error_does_not_crash_step(self, tmp_path):
        """Errors in splitting analysis are caught, step returns normally."""
        ctx = _make_ctx(tmp_path)
        ctx.agent_results = [_diverse_agent_result("dev1")]

        with patch(
            "opensepia.evolution.splitting.AgentSplitter.analyze_generalization",
            side_effect=ValueError("test error"),
        ):
            step = EvolutionStep()
            result = step.execute(ctx)

        # Step should return ctx without raising
        assert result is ctx
