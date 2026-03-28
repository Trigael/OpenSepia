"""Tests for commands/evolve.py — evolution CLI subcommands."""

import yaml
from unittest.mock import patch, MagicMock

from opensepia.commands.evolve import cmd_evolve


def _make_config(tmp_path):
    """Build a mock OrchestratorConfig pointing at tmp_path."""
    board_dir = tmp_path / "board"
    board_dir.mkdir(exist_ok=True)
    evo_dir = board_dir / "evolution"
    evo_dir.mkdir(parents=True, exist_ok=True)

    config = MagicMock()
    config.board_dir = board_dir
    config.agents = {
        "agents": {
            "dev1": {"name": "Dev 1", "system_prompt": "You are Developer 1."},
            "po": {"name": "PO", "system_prompt": "You are PO."},
        }
    }
    config.get_all_agent_ids.return_value = ["dev1", "po"]
    return config


def _seed_proposal(board_dir, ptype="memory", proposed_by="dev1",
                   details=None, filename=None):
    """Write a proposal YAML to pending/."""
    pending = board_dir / "evolution" / "proposals" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    fname = filename or f"20260101_120000_{proposed_by}_{ptype}.yaml"
    path = pending / fname
    data = {
        "type": ptype,
        "proposed_by": proposed_by,
        "proposed_at": "2026-01-01T12:00:00",
        "sprint": 1,
        "cycle": 3,
        "status": "pending",
        "details": details or {},
    }
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return path


def _seed_memory(board_dir, agent_id, content):
    mem_dir = board_dir / "evolution" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / f"{agent_id}.md").write_text(content, encoding="utf-8")


def _seed_skill(board_dir, name, scope="global", tags=None):
    scope_dir = board_dir / "evolution" / "skills" / f"_{scope}"
    scope_dir.mkdir(parents=True, exist_ok=True)
    content = f"# Skill: {name}\nscope: {scope}\ntags: [{', '.join(tags or [])}]\nlearned_by: dev1\nversion: 1\n\nSome content."
    safe = name.lower().replace(" ", "_")
    (scope_dir / f"{safe}.md").write_text(content, encoding="utf-8")


class TestListSubcommand:
    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_list_with_pending(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config
        _seed_proposal(config.board_dir, "memory", "dev1")
        _seed_proposal(config.board_dir, "skill", "po",
                       filename="20260101_130000_po_skill.yaml")

        cmd_evolve(["list"])
        out = capsys.readouterr().out
        assert "memory" in out
        assert "dev1" in out
        assert "skill" in out

    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_list_empty(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config

        cmd_evolve(["list"])
        out = capsys.readouterr().out
        assert "No pending" in out


class TestStatusSubcommand:
    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_status_shows_sections(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config

        _seed_memory(config.board_dir, "dev1", "Some memory content")
        _seed_skill(config.board_dir, "pytest tricks", tags=["pytest", "testing"])

        cmd_evolve(["status"])
        out = capsys.readouterr().out
        assert "Evolution Status" in out
        assert "memory" in out.lower() or "Agents with memory" in out
        assert "Skills" in out or "skills" in out.lower()

    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_status_empty_state(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config

        cmd_evolve(["status"])
        out = capsys.readouterr().out
        assert "Evolution Status" in out
        assert "0" in out  # zero counts


class TestApproveSubcommand:
    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_approve_by_index(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config
        _seed_proposal(config.board_dir, "memory", "dev1", details={"entry": "x"})

        cmd_evolve(["approve", "0"])
        out = capsys.readouterr().out
        assert "Approved" in out or "approved" in out.lower()
        # Pending should be empty now
        pending = config.board_dir / "evolution" / "proposals" / "pending"
        assert len(list(pending.glob("*.yaml"))) == 0

    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_approve_invalid_index(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config

        cmd_evolve(["approve", "99"])
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "not found" in captured.out.lower()


class TestRejectSubcommand:
    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_reject_by_index_with_reason(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config
        _seed_proposal(config.board_dir, "memory", "dev1")

        cmd_evolve(["reject", "0", "--reason", "not relevant"])
        out = capsys.readouterr().out
        assert "Rejected" in out or "rejected" in out.lower()
        # Should be in rejected/
        rejected = config.board_dir / "evolution" / "proposals" / "rejected"
        files = list(rejected.glob("*.yaml"))
        assert len(files) == 1
        data = yaml.safe_load(files[0].read_text(encoding="utf-8"))
        assert data["rejection_reason"] == "not relevant"

    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_reject_invalid_index(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config

        cmd_evolve(["reject", "5", "--reason", "bad"])
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "not found" in captured.out.lower()


class TestRollbackSubcommand:
    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_rollback_existing_version(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config

        # Seed a prompt version to roll back to
        from opensepia.evolution.prompts import PromptManager
        pm = PromptManager(config.board_dir)
        pm.apply_refinement("dev1", "You are dev1. " + "A" * 60, "dev1", "init", "v1")
        pm.apply_refinement("dev1", "You are dev1. " + "B" * 60, "dev1", "update", "v2")

        cmd_evolve(["rollback", "dev1", "--version", "1"])
        out = capsys.readouterr().out
        assert "Rolled back" in out or "rolled back" in out.lower()

    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_rollback_nonexistent_version(self, mock_cfg_cls, tmp_path, capsys):
        config = _make_config(tmp_path)
        mock_cfg_cls.load.return_value = config

        cmd_evolve(["rollback", "dev1", "--version", "99"])
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "not found" in captured.out.lower()


class TestNoArgs:
    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_no_args_prints_help(self, mock_cfg_cls, capsys):
        """No subcommand should print help and return without loading config."""
        cmd_evolve([])
        out = capsys.readouterr().out
        assert "usage" in out.lower() or "opensepia evolve" in out.lower()


class TestEvolutionDirMissing:
    @patch("opensepia.commands.evolve.OrchestratorConfig")
    def test_missing_evo_dir_warns(self, mock_cfg_cls, tmp_path, capsys):
        config = MagicMock()
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        # Do NOT create evolution/ dir
        config.board_dir = board_dir
        mock_cfg_cls.load.return_value = config

        cmd_evolve(["list"])
        out = capsys.readouterr().out
        assert "not initialized" in out.lower() or "init" in out.lower()
