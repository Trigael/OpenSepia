"""Tests for evolution/proposals.py — ProposalManager lifecycle."""

import yaml
import pytest
from pathlib import Path

from opensepia.evolution.proposals import ProposalManager


@pytest.fixture
def board_dir(tmp_path):
    bd = tmp_path / "board"
    bd.mkdir()
    return bd


@pytest.fixture
def agents_config():
    return {
        "agents": {
            "dev1": {"name": "Dev 1", "system_prompt": "You are Developer 1."},
            "dev2": {"name": "Dev 2", "system_prompt": "You are Developer 2."},
            "po": {"name": "Product Owner", "system_prompt": "You are PO."},
        }
    }


@pytest.fixture
def pm(board_dir, agents_config):
    return ProposalManager(board_dir, agents_config)


def _seed_pending_proposal(board_dir, proposal_type="memory", proposed_by="dev1",
                           details=None, filename=None):
    """Helper: write a proposal YAML into pending/."""
    pending = board_dir / "evolution" / "proposals" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    fname = filename or f"20260101_120000_{proposed_by}_{proposal_type}.yaml"
    path = pending / fname
    data = {
        "type": proposal_type,
        "proposed_by": proposed_by,
        "proposed_at": "2026-01-01T12:00:00",
        "sprint": 1,
        "cycle": 3,
        "status": "pending",
        "details": details or {},
    }
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return path


class TestCreateProposal:
    def test_creates_yaml_in_pending(self, pm, board_dir):
        path = pm.create_proposal("memory", "dev1", {"entry": "learned X"}, sprint=1, cycle=2)
        assert path.exists()
        assert path.parent.name == "pending"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["type"] == "memory"
        assert data["proposed_by"] == "dev1"
        assert data["status"] == "pending"
        assert data["sprint"] == 1
        assert data["cycle"] == 2
        assert data["details"] == {"entry": "learned X"}

    def test_creates_pending_dir_if_missing(self, pm, board_dir):
        pending = board_dir / "evolution" / "proposals" / "pending"
        assert not pending.exists()
        pm.create_proposal("skill", "dev2", {}, sprint=1, cycle=1)
        assert pending.exists()

    def test_filename_contains_metadata(self, pm):
        path = pm.create_proposal("prompt_refine", "po", {}, sprint=2, cycle=5)
        assert "po" in path.name
        assert "prompt_refine" in path.name
        assert path.suffix == ".yaml"


class TestGetPending:
    def test_empty_when_no_dir(self, pm):
        assert pm.get_pending() == []

    def test_empty_when_dir_exists_but_no_files(self, pm, board_dir):
        (board_dir / "evolution" / "proposals" / "pending").mkdir(parents=True)
        assert pm.get_pending() == []

    def test_returns_proposals_sorted(self, pm, board_dir):
        _seed_pending_proposal(board_dir, "memory", "dev1",
                               filename="20260101_100000_dev1_memory.yaml")
        _seed_pending_proposal(board_dir, "skill", "dev2",
                               filename="20260101_110000_dev2_skill.yaml")
        pending = pm.get_pending()
        assert len(pending) == 2
        assert pending[0]["type"] == "memory"
        assert pending[1]["type"] == "skill"

    def test_includes_path_field(self, pm, board_dir):
        _seed_pending_proposal(board_dir)
        pending = pm.get_pending()
        assert "path" in pending[0]
        assert Path(pending[0]["path"]).exists()

    def test_skips_corrupt_yaml(self, pm, board_dir):
        pending_dir = board_dir / "evolution" / "proposals" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        bad = pending_dir / "bad.yaml"
        bad.write_text(": : : invalid yaml [[[", encoding="utf-8")
        _seed_pending_proposal(board_dir, filename="good.yaml")
        result = pm.get_pending()
        assert len(result) == 1

    def test_skips_empty_yaml(self, pm, board_dir):
        pending_dir = board_dir / "evolution" / "proposals" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        empty = pending_dir / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        result = pm.get_pending()
        assert len(result) == 0


class TestApprove:
    def test_approve_memory(self, pm, board_dir):
        path = _seed_pending_proposal(board_dir, "memory", "dev1", {"entry": "test"})
        result = pm.approve(path)
        assert result.get("status") == "ok"
        # Original file is gone
        assert not path.exists()
        # Moved to approved/
        approved_dir = board_dir / "evolution" / "proposals" / "approved"
        assert (approved_dir / path.name).exists()
        data = yaml.safe_load((approved_dir / path.name).read_text(encoding="utf-8"))
        assert data["status"] == "approved"
        assert "approved_at" in data

    def test_approve_skill(self, pm, board_dir):
        path = _seed_pending_proposal(board_dir, "skill", "dev1")
        result = pm.approve(path)
        assert result.get("status") == "ok"
        assert not path.exists()

    def test_approve_nonexistent_path(self, pm):
        result = pm.approve("/tmp/does_not_exist.yaml")
        assert "error" in result

    def test_approve_empty_proposal(self, pm, board_dir):
        pending_dir = board_dir / "evolution" / "proposals" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        path = pending_dir / "empty.yaml"
        path.write_text("", encoding="utf-8")
        result = pm.approve(path)
        assert "error" in result

    def test_approve_unknown_type(self, pm, board_dir):
        path = _seed_pending_proposal(board_dir, "unknown_thing", "dev1")
        result = pm.approve(path)
        assert "error" in result
        assert "Unknown proposal type" in result["error"]


class TestReject:
    def test_reject_moves_to_rejected(self, pm, board_dir):
        path = _seed_pending_proposal(board_dir, "memory", "dev1")
        pm.reject(path, reason="Not useful")
        assert not path.exists()
        rejected_dir = board_dir / "evolution" / "proposals" / "rejected"
        rejected_path = rejected_dir / path.name
        assert rejected_path.exists()
        data = yaml.safe_load(rejected_path.read_text(encoding="utf-8"))
        assert data["status"] == "rejected"
        assert data["rejection_reason"] == "Not useful"

    def test_reject_empty_reason(self, pm, board_dir):
        path = _seed_pending_proposal(board_dir, "skill", "dev2")
        pm.reject(path, reason="")
        rejected_dir = board_dir / "evolution" / "proposals" / "rejected"
        assert (rejected_dir / path.name).exists()

    def test_reject_nonexistent_does_nothing(self, pm):
        pm.reject("/tmp/does_not_exist.yaml", reason="gone")


class TestAutoProcess:
    def test_auto_approves_memory_and_skill(self, pm, board_dir):
        _seed_pending_proposal(board_dir, "memory", "dev1",
                               filename="20260101_100000_dev1_memory.yaml",
                               details={"entry": "x"})
        _seed_pending_proposal(board_dir, "skill", "dev2",
                               filename="20260101_110000_dev2_skill.yaml")
        applied = pm.auto_process({})
        assert len(applied) == 2
        # Both should be in approved/
        approved = board_dir / "evolution" / "proposals" / "approved"
        assert len(list(approved.glob("*.yaml"))) == 2

    def test_leaves_prompt_refine_pending(self, pm, board_dir):
        _seed_pending_proposal(board_dir, "prompt_refine", "dev1",
                               details={"new_prompt": "x", "reason": "y"})
        applied = pm.auto_process({})
        assert len(applied) == 0
        assert len(pm.get_pending()) == 1

    def test_auto_approve_respects_config_override(self, pm, board_dir):
        _seed_pending_proposal(board_dir, "memory", "dev1",
                               details={"entry": "x"})
        # Explicitly disable auto-approve for memory
        applied = pm.auto_process({"memory": False})
        assert len(applied) == 0
        assert len(pm.get_pending()) == 1

    def test_auto_approve_prompt_when_configured(self, pm, board_dir):
        """If config says prompt_refine=True, it still needs execute to succeed."""
        path = _seed_pending_proposal(board_dir, "prompt_refine", "dev1",
                                      details={"new_prompt": "", "reason": "y"})
        # new_prompt is empty, so _execute_prompt_refine returns error
        applied = pm.auto_process({"prompt_refine": True})
        assert len(applied) == 0


class TestExecutePromptRefine:
    def test_creates_new_prompt_version(self, pm, board_dir, agents_config):
        new_prompt = (
            "You are dev1. " + "A" * 50 + "\n"
            "You handle backend tasks with care."
        )
        path = _seed_pending_proposal(
            board_dir, "prompt_refine", "dev1",
            details={"new_prompt": new_prompt, "reason": "improve", "diff_summary": "added detail"},
        )
        result = pm.approve(path)
        assert result.get("status") == "ok"
        assert result.get("version") == 1
        assert result.get("agent_id") == "dev1"

    def test_rejects_empty_prompt(self, pm, board_dir):
        path = _seed_pending_proposal(
            board_dir, "prompt_refine", "dev1",
            details={"new_prompt": "", "reason": "bad"},
        )
        result = pm.approve(path)
        assert "error" in result

    def test_rejects_too_short_prompt(self, pm, board_dir):
        path = _seed_pending_proposal(
            board_dir, "prompt_refine", "dev1",
            details={"new_prompt": "Short", "reason": "too short"},
        )
        result = pm.approve(path)
        assert "error" in result


class TestExecuteSpawn:
    def test_spawn_creates_agent_in_registry(self, pm, board_dir, agents_config):
        # Initialize lineage so parent exists
        from opensepia.evolution.spawning import AgentSpawner
        spawner = AgentSpawner(board_dir)
        spawner.initialize_lineage(["dev1", "dev2", "po"])

        child_prompt = (
            "You are perf_specialist. " + "B" * 50 + "\n"
            "You optimize performance."
        )
        path = _seed_pending_proposal(
            board_dir, "spawn_agent", "dev1",
            details={
                "child_id": "perf_specialist",
                "child_name": "Performance Specialist",
                "child_prompt": child_prompt,
            },
        )
        result = pm.approve(path)
        assert result.get("status") == "ok"
        assert result.get("agent_id") == "perf_specialist"

        # Verify registry
        spawned = spawner.get_spawned_agents()
        assert any(a.agent_id == "perf_specialist" for a in spawned)

    def test_spawn_missing_fields(self, pm, board_dir):
        path = _seed_pending_proposal(
            board_dir, "spawn_agent", "dev1",
            details={"child_id": "x"},  # missing child_name, child_prompt
        )
        result = pm.approve(path)
        assert "error" in result

    def test_spawn_duplicate_id(self, pm, board_dir, agents_config):
        from opensepia.evolution.spawning import AgentSpawner
        spawner = AgentSpawner(board_dir)
        spawner.initialize_lineage(["dev1", "dev2", "po"])

        child_prompt = "You are dev2. " + "C" * 50 + "\nDuplicate agent."
        path = _seed_pending_proposal(
            board_dir, "spawn_agent", "dev1",
            details={
                "child_id": "dev2",  # already exists
                "child_name": "Dup",
                "child_prompt": child_prompt,
            },
        )
        result = pm.approve(path)
        assert "error" in result


class TestEdgeCases:
    def test_approve_corrupt_yaml(self, pm, board_dir):
        pending_dir = board_dir / "evolution" / "proposals" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        path = pending_dir / "corrupt.yaml"
        path.write_text(": : : [[[bad", encoding="utf-8")
        result = pm.approve(path)
        assert "error" in result

    def test_reject_corrupt_yaml(self, pm, board_dir):
        """Reject should handle corrupt YAML gracefully without raising."""
        pending_dir = board_dir / "evolution" / "proposals" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        path = pending_dir / "corrupt.yaml"
        path.write_text(": : : [[[bad", encoding="utf-8")
        pm.reject(path, reason="corrupt")
        assert not path.exists()
        rejected_dir = board_dir / "evolution" / "proposals" / "rejected"
        assert (rejected_dir / "corrupt.yaml").exists()
