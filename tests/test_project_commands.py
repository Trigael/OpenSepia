"""Comprehensive unit tests for opensepia/commands/project.py (cmd_init, cmd_reset)."""

import yaml
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_tool_dir(tmp_path: Path) -> Path:
    """Return a tmp_path that mimics the tool_dir layout."""
    (tmp_path / "project").mkdir(exist_ok=True)
    return tmp_path


def _patch_tool_dir(tmp_path: Path):
    """Patch get_tool_dir() to return tmp_path."""
    return patch("opensepia.dirs.get_tool_dir", return_value=tmp_path)


# ---------------------------------------------------------------------------
# cmd_init tests
# ---------------------------------------------------------------------------

class TestCmdInit:
    """Tests for the cmd_init function."""

    def test_creates_board_directories(self, tmp_path):
        """cmd_init creates inbox, archive, .snapshot under board/."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            mock_cfg.load.side_effect = Exception("no config")
            # Force fallback via ConfigError
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("no config")
            cmd_init(["TestProject"])

        board = tmp_path / "project" / "board"
        assert (board / "inbox").is_dir()
        assert (board / "archive").is_dir()
        assert (board / ".snapshot").is_dir()

    def test_creates_workspace_directories(self, tmp_path):
        """cmd_init creates src, tests, docs, config under workspace/."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["TestProject"])

        ws = tmp_path / "project" / "workspace"
        for d in ["src", "tests", "docs", "config"]:
            assert (ws / d).is_dir()

    def test_creates_board_files(self, tmp_path):
        """cmd_init creates project.md, backlog.md, sprint.md, architecture.md, decisions.md."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["MyApp", "A cool app"])

        board = tmp_path / "project" / "board"
        for fname in ["project.md", "backlog.md", "sprint.md", "architecture.md", "decisions.md"]:
            f = board / fname
            assert f.exists(), f"{fname} was not created"

        # Verify content includes project name
        assert "MyApp" in (board / "project.md").read_text()
        assert "MyApp" in (board / "backlog.md").read_text()
        assert "MyApp" in (board / "architecture.md").read_text()
        assert "MyApp" in (board / "decisions.md").read_text()
        assert "A cool app" in (board / "project.md").read_text()

    def test_creates_agent_inbox_files(self, tmp_path):
        """cmd_init creates inbox files for all agents."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["TestProject"])

        inbox = tmp_path / "project" / "board" / "inbox"
        # Default fallback agent list
        expected_agents = ["po", "pm", "dev1", "dev2", "devops", "tester",
                           "sec_analyst", "sec_engineer", "sec_pentester"]
        for aid in expected_agents:
            assert (inbox / f"{aid}.md").exists(), f"Inbox for {aid} missing"

    def test_seeds_po_inbox(self, tmp_path):
        """cmd_init seeds the PO inbox with initialization message."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["GreatApp", "Build something great"])

        po_inbox = tmp_path / "project" / "board" / "inbox" / "po.md"
        content = po_inbox.read_text()
        assert "GreatApp" in content
        assert "Build something great" in content
        assert "Initialization" in content
        assert "Define the product vision" in content

    def test_creates_project_yaml_from_scratch(self, tmp_path):
        """cmd_init creates project.yaml when it doesn't exist."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["FreshProject", "Brand new"])

        pf = tmp_path / "project" / "project.yaml"
        assert pf.exists()
        cfg = yaml.safe_load(pf.read_text())
        assert cfg["project"]["name"] == "FreshProject"
        assert cfg["project"]["description"] == "Brand new"
        assert cfg["sprint"]["current_sprint"] == 1
        assert cfg["sprint"]["current_cycle"] == 0

    def test_updates_existing_project_yaml(self, tmp_path):
        """cmd_init updates project.yaml when it already exists."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        pf = tmp_path / "project" / "project.yaml"
        pf.write_text(yaml.dump({
            "project": {"name": "OldName"},
            "sprint": {"current_sprint": 5, "current_cycle": 10},
            "limits": {"max_cycles": 50},
        }))

        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["NewName", "Updated desc"])

        cfg = yaml.safe_load(pf.read_text())
        assert cfg["project"]["name"] == "NewName"
        assert cfg["project"]["description"] == "Updated desc"
        assert cfg["sprint"]["current_sprint"] == 1
        assert cfg["sprint"]["current_cycle"] == 0
        # Preserved limits from existing file
        assert cfg["limits"]["max_cycles"] == 50

    def test_creates_workspace_gitignore(self, tmp_path):
        """cmd_init creates .gitignore in workspace."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["TestProject"])

        gi = tmp_path / "project" / "workspace" / ".gitignore"
        assert gi.exists()
        content = gi.read_text()
        assert "__pycache__/" in content
        assert "node_modules/" in content

    def test_does_not_overwrite_existing_gitignore(self, tmp_path):
        """cmd_init doesn't overwrite an existing .gitignore."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        ws = tmp_path / "project" / "workspace"
        ws.mkdir(parents=True)
        gi = ws / ".gitignore"
        gi.write_text("custom-ignore\n")

        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["TestProject"])

        assert gi.read_text() == "custom-ignore\n"

    def test_uses_agents_from_config(self, tmp_path):
        """cmd_init uses agent IDs from OrchestratorConfig when available."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        mock_config = MagicMock()
        mock_config.get_all_agent_ids.return_value = ["alpha", "beta"]

        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            mock_cfg.load.return_value = mock_config
            cmd_init(["TestProject"])

        inbox = tmp_path / "project" / "board" / "inbox"
        assert (inbox / "alpha.md").exists()
        assert (inbox / "beta.md").exists()
        # PO inbox is always written (overwrites empty file)
        assert (inbox / "po.md").exists()

    def test_fallback_agents_on_config_error(self, tmp_path):
        """cmd_init falls back to default agent list when config fails (lines 86-87)."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("broken config")
            cmd_init(["TestProject"])

        inbox = tmp_path / "project" / "board" / "inbox"
        fallback = ["po", "pm", "dev1", "dev2", "devops", "tester",
                     "sec_analyst", "sec_engineer", "sec_pentester"]
        for aid in fallback:
            assert (inbox / f"{aid}.md").exists()

    def test_default_description(self, tmp_path):
        """cmd_init uses 'New project' as default description."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["TestProject"])

        pf = tmp_path / "project" / "project.yaml"
        cfg = yaml.safe_load(pf.read_text())
        assert cfg["project"]["description"] == "New project"

    def test_initializes_lineage_with_all_agents(self, tmp_path):
        """cmd_init creates lineage.yaml with all agents as type: original."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["TestProject"])

        lineage_file = tmp_path / "project" / "board" / "evolution" / "lineage" / "lineage.yaml"
        assert lineage_file.exists(), "lineage.yaml was not created"
        data = yaml.safe_load(lineage_file.read_text())
        agents = data["agents"]

        expected = ["po", "pm", "dev1", "dev2", "devops", "tester",
                    "sec_analyst", "sec_engineer", "sec_pentester"]
        for aid in expected:
            assert aid in agents, f"Agent {aid} missing from lineage"
            assert agents[aid]["type"] == "original"

    def test_lineage_init_idempotent(self, tmp_path):
        """Calling cmd_init twice does not duplicate agents in lineage."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["TestProject"])
            cmd_init(["TestProject"])

        lineage_file = tmp_path / "project" / "board" / "evolution" / "lineage" / "lineage.yaml"
        data = yaml.safe_load(lineage_file.read_text())
        agents = data["agents"]

        # Each agent appears exactly once (dict keys are unique by nature)
        expected = ["po", "pm", "dev1", "dev2", "devops", "tester",
                    "sec_analyst", "sec_engineer", "sec_pentester"]
        assert len(agents) == len(expected)
        for aid in expected:
            assert agents[aid]["type"] == "original"

    def test_fresh_project_yaml_has_all_sections(self, tmp_path):
        """When no project.yaml exists, the created one has project, sprint, limits keys (line 114)."""
        from opensepia.commands.project import cmd_init

        _fake_tool_dir(tmp_path)
        with _patch_tool_dir(tmp_path), \
             patch("opensepia.commands.project.OrchestratorConfig") as mock_cfg:
            from opensepia.errors import ConfigError
            mock_cfg.load.side_effect = ConfigError("x")
            cmd_init(["FreshProject"])

        pf = tmp_path / "project" / "project.yaml"
        cfg = yaml.safe_load(pf.read_text())
        assert "project" in cfg
        assert "sprint" in cfg
        assert "limits" in cfg


# ---------------------------------------------------------------------------
# cmd_reset tests
# ---------------------------------------------------------------------------

class TestCmdReset:
    """Tests for the cmd_reset function."""

    def _setup_project(self, tmp_path: Path) -> Path:
        """Create a minimal project layout for reset tests."""
        project = tmp_path / "project"
        board = project / "board"
        ws = project / "workspace"
        logs = project / "logs"

        (board / "inbox").mkdir(parents=True)
        (board / "archive").mkdir(parents=True)
        (board / "sprint.md").write_text("sprint data")
        (board / "backlog.md").write_text("backlog data")
        (board / "inbox" / "po.md").write_text("po data")
        (ws / "src").mkdir(parents=True)
        (ws / "src" / "main.py").write_text("code")
        logs.mkdir(parents=True)
        (logs / "cycle_001.log").write_text("log data")

        pf = project / "project.yaml"
        pf.write_text(yaml.dump({
            "project": {"name": "TestProject", "description": "Test"},
            "sprint": {"current_sprint": 5, "current_cycle": 42},
            "limits": {"max_cycles": 100},
        }))
        return tmp_path

    def test_reset_with_yes_flag(self, tmp_path):
        """cmd_reset with --yes skips confirmation and clears everything."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        with _patch_tool_dir(root), \
             patch("opensepia.commands.project.stop_daemon", create=True), \
             patch("opensepia.commands.project.get_daemon_status", create=True) as mock_status:
            # Patch daemon imports inside the function
            with patch.dict("sys.modules", {
                "opensepia.daemon": MagicMock(
                    stop_daemon=MagicMock(),
                    get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                ),
            }):
                cmd_reset(["--yes"])

        project = root / "project"
        # Board cleared and recreated empty
        assert (project / "board").is_dir()
        assert not (project / "board" / "sprint.md").exists()
        assert not (project / "board" / "inbox").exists()

        # Workspace cleared
        assert (project / "workspace").is_dir()
        assert not (project / "workspace" / "src").exists()

        # Logs cleared
        assert (project / "logs").is_dir()
        assert not (project / "logs" / "cycle_001.log").exists()

    def test_reset_resets_project_yaml(self, tmp_path):
        """cmd_reset resets sprint counters in project.yaml."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=MagicMock(),
                     get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                 ),
             }):
            cmd_reset(["--yes"])

        pf = root / "project" / "project.yaml"
        cfg = yaml.safe_load(pf.read_text())
        assert cfg["sprint"]["current_sprint"] == 1
        assert cfg["sprint"]["current_cycle"] == 0
        assert cfg["project"] == {}

    def test_reset_without_yes_confirms(self, tmp_path):
        """cmd_reset without --yes prompts for confirmation."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        with _patch_tool_dir(root), \
             patch("builtins.input", return_value="yes"), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=MagicMock(),
                     get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                 ),
             }):
            cmd_reset([])

        # Should have proceeded with reset
        assert not (root / "project" / "board" / "sprint.md").exists()

    def test_reset_aborts_on_no(self, tmp_path):
        """cmd_reset aborts when user types 'no' (lines 159-168)."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        with _patch_tool_dir(root), \
             patch("builtins.input", return_value="no"), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=MagicMock(),
                     get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                 ),
             }):
            cmd_reset([])

        # Board should still be intact
        assert (root / "project" / "board" / "sprint.md").exists()

    def test_reset_handles_missing_project_yaml(self, tmp_path):
        """cmd_reset works when project.yaml doesn't exist."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        (root / "project" / "project.yaml").unlink()

        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=MagicMock(),
                     get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                 ),
             }):
            cmd_reset(["--yes"])

        # Should not raise, board/workspace/logs still cleared
        assert (root / "project" / "board").is_dir()
        assert (root / "project" / "workspace").is_dir()

    def test_reset_stops_running_daemon(self, tmp_path):
        """cmd_reset stops the daemon if it's running (lines 174-176)."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        mock_stop = MagicMock()
        mock_state = MagicMock()
        mock_state.is_process_alive.return_value = True

        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=mock_stop,
                     get_daemon_status=MagicMock(return_value=mock_state),
                 ),
             }):
            cmd_reset(["--yes"])

        mock_stop.assert_called_once()

    def test_reset_handles_daemon_stop_error(self, tmp_path):
        """cmd_reset handles errors when stopping daemon gracefully."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)

        daemon_mod = MagicMock()
        daemon_mod.get_daemon_status.side_effect = RuntimeError("daemon broken")

        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {"opensepia.daemon": daemon_mod}):
            # Should not raise
            cmd_reset(["--yes"])

        # Reset should still proceed
        assert not (root / "project" / "board" / "sprint.md").exists()

    def test_reset_cleans_lockfiles(self, tmp_path):
        """cmd_reset removes lockfiles from project/logs and tool/logs (lines 185, 188)."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        # Create lockfiles in project/logs
        proj_logs = root / "project" / "logs"
        (proj_logs / "daemon.lock").write_text("lock")
        (proj_logs / "dev-team.lock").write_text("lock")

        # Create lockfiles in tool_dir/logs
        tool_logs = root / "logs"
        tool_logs.mkdir(exist_ok=True)
        (tool_logs / "daemon.lock").write_text("lock")
        (tool_logs / "cycle_state.json").write_text("{}")

        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=MagicMock(),
                     get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                 ),
             }):
            cmd_reset(["--yes"])

        # tool_dir/logs lockfiles should be cleaned
        assert not (tool_logs / "daemon.lock").exists()
        assert not (tool_logs / "cycle_state.json").exists()

    def test_reset_handles_corrupt_project_yaml(self, tmp_path):
        """cmd_reset handles corrupt project.yaml gracefully (lines 223-224)."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        # Write invalid YAML
        pf = root / "project" / "project.yaml"
        pf.write_text(": invalid: yaml: [[[")

        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=MagicMock(),
                     get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                 ),
             }):
            # Should not raise
            cmd_reset(["--yes"])

        # Board should still be cleared
        assert (root / "project" / "board").is_dir()

    def test_reset_with_no_existing_directories(self, tmp_path):
        """cmd_reset works even if board/workspace/logs don't exist."""
        from opensepia.commands.project import cmd_reset

        root = tmp_path
        (root / "project").mkdir()

        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=MagicMock(),
                     get_daemon_status=MagicMock(return_value=MagicMock(is_process_alive=lambda: False)),
                 ),
             }):
            cmd_reset(["--yes"])

        # Directories should be created empty
        assert (root / "project" / "board").is_dir()
        assert (root / "project" / "workspace").is_dir()
        assert (root / "project" / "logs").is_dir()

    def test_reset_daemon_not_alive_skips_stop(self, tmp_path):
        """cmd_reset doesn't call stop_daemon when daemon is not alive."""
        from opensepia.commands.project import cmd_reset

        root = self._setup_project(tmp_path)
        mock_stop = MagicMock()
        mock_state = MagicMock()
        mock_state.is_process_alive.return_value = False

        with _patch_tool_dir(root), \
             patch.dict("sys.modules", {
                 "opensepia.daemon": MagicMock(
                     stop_daemon=mock_stop,
                     get_daemon_status=MagicMock(return_value=mock_state),
                 ),
             }):
            cmd_reset(["--yes"])

        mock_stop.assert_not_called()
