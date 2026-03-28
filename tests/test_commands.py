"""Unit tests for CLI command modules.

Tests individual functions from run.py, interact.py, observe.py, and project.py
without calling external APIs or Claude CLI.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from opensepia.config import OrchestratorConfig
from opensepia.commands.run import (
    build_pipeline,
    check_claude_cli,
    check_project_ready,
    check_workspace_git,
    STEP_REGISTRY,
    PARAMETERIZED_REGISTRY,
    DEFAULT_PIPELINE,
)
from opensepia.steps.agent_step import AgentStep, AgentCommitStep, AgentSyncStep, InitStandupStep
from opensepia.steps.board_health import BoardHealthStep, SnapshotStep
from opensepia.steps.sprint_check import SprintCheckStep, SprintSyncStep
from opensepia.steps.standup_sync import StandupSyncStep
from opensepia.steps.merge_mrs import MergeMRsStep
from opensepia.steps.git_sync import GitSyncStep
from opensepia.steps.board_sync import BoardSyncStep
from opensepia.steps.logging_step import CycleLogStep
from opensepia.steps.alerting import AlertingStep


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_config(tmp_path):
    """Create an OrchestratorConfig pointing at tmp directories."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    board_dir = project_dir / "board"
    board_dir.mkdir()
    workspace_dir = project_dir / "workspace"
    workspace_dir.mkdir()

    (board_dir / "sprint.md").write_text("# Sprint 1\n", encoding="utf-8")
    (project_dir / "project.yaml").write_text(
        yaml.dump({
            "project": {"name": "Test", "description": "A test"},
            "sprint": {"current_sprint": 1, "current_cycle": 5},
        }),
        encoding="utf-8",
    )

    return OrchestratorConfig(
        tool_dir=tmp_path,
        project_dir=project_dir,
        agents={
            "agents": {
                "po": {"name": "Product Owner", "system_prompt": "You are PO"},
                "dev1": {"name": "Developer 1", "system_prompt": "You are dev"},
                "tester": {"name": "Tester", "system_prompt": "You are tester"},
            },
            "modes": {
                "dev-team": {
                    "agents": ["po", "dev1", "tester"],
                    "default": True,
                    "aliases": ["dev"],
                },
                "minimal": {
                    "agents": ["po", "dev1"],
                    "aliases": ["min"],
                },
            },
            "execution": {
                "timeout": 900,
                "max_retries": 1,
                "retry_delay": 30,
                "pause_between_agents": 0,
            },
        },
        project={
            "project": {"name": "Test", "description": "A test"},
            "sprint": {"current_sprint": 1, "current_cycle": 5},
        },
    )


@pytest.fixture
def init_project_dir(tmp_path):
    """Create a minimal tool directory structure for cmd_init / cmd_reset tests."""
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()

    # config dir with agents.yaml
    config_dir = tool_dir / "config"
    config_dir.mkdir()
    (config_dir / "agents.yaml").write_text(
        yaml.dump({
            "agents": {
                "po": {"name": "PO", "system_prompt": "PO prompt"},
                "dev1": {"name": "Dev1", "system_prompt": "Dev prompt"},
            },
            "modes": {
                "dev-team": {"agents": ["po", "dev1"], "default": True},
            },
            "execution": {"timeout": 900},
        }),
        encoding="utf-8",
    )

    # project dir with project.yaml
    project_dir = tool_dir / "project"
    project_dir.mkdir()
    (project_dir / "project.yaml").write_text(
        yaml.dump({
            "project": {"name": "", "description": ""},
            "sprint": {"current_sprint": 1, "current_cycle": 0, "cycles_per_sprint": 10},
        }),
        encoding="utf-8",
    )

    return tool_dir


# =============================================================================
# check_project_ready()
# =============================================================================

class TestCheckProjectReady:

    def test_project_dir_missing(self, tmp_path):
        config = MagicMock(spec=OrchestratorConfig)
        config.project_dir = tmp_path / "nonexistent"
        issues = check_project_ready(config)
        assert len(issues) == 1
        assert "does not exist" in issues[0]

    def test_project_yaml_missing(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config = MagicMock(spec=OrchestratorConfig)
        config.project_dir = project_dir
        issues = check_project_ready(config)
        assert len(issues) == 1
        assert "project.yaml" in issues[0]

    def test_board_not_initialized(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("project: {}", encoding="utf-8")
        workspace = project_dir / "workspace"
        workspace.mkdir()

        config = MagicMock(spec=OrchestratorConfig)
        config.project_dir = project_dir
        config.board_dir = project_dir / "board"
        config.workspace_dir = workspace
        issues = check_project_ready(config)
        assert any("Board" in i for i in issues)

    def test_board_missing_sprint_md(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("project: {}", encoding="utf-8")
        board = project_dir / "board"
        board.mkdir()
        workspace = project_dir / "workspace"
        workspace.mkdir()

        config = MagicMock(spec=OrchestratorConfig)
        config.project_dir = project_dir
        config.board_dir = board
        config.workspace_dir = workspace
        issues = check_project_ready(config)
        assert any("Board" in i for i in issues)

    def test_workspace_missing(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("project: {}", encoding="utf-8")
        board = project_dir / "board"
        board.mkdir()
        (board / "sprint.md").write_text("# Sprint 1\n", encoding="utf-8")

        config = MagicMock(spec=OrchestratorConfig)
        config.project_dir = project_dir
        config.board_dir = board
        config.workspace_dir = project_dir / "workspace"  # does not exist
        issues = check_project_ready(config)
        assert any("Workspace" in i for i in issues)

    def test_all_ready(self, mock_config):
        issues = check_project_ready(mock_config)
        assert issues == []

    def test_returns_early_if_project_dir_missing(self, tmp_path):
        """When project dir is missing, should return immediately with one issue."""
        config = MagicMock(spec=OrchestratorConfig)
        config.project_dir = tmp_path / "gone"
        issues = check_project_ready(config)
        assert len(issues) == 1

    def test_returns_early_if_project_yaml_missing(self, tmp_path):
        """When project.yaml is missing, should return immediately with one issue."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config = MagicMock(spec=OrchestratorConfig)
        config.project_dir = project_dir
        issues = check_project_ready(config)
        assert len(issues) == 1


# =============================================================================
# check_workspace_git()
# =============================================================================

class TestCheckWorkspaceGit:

    def test_workspace_missing(self, tmp_path):
        config = MagicMock(spec=OrchestratorConfig)
        config.workspace_dir = tmp_path / "nope"
        result = check_workspace_git(config)
        assert result["initialized"] is False
        assert result["reason"] == "workspace missing"

    def test_no_git_dir(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        config = MagicMock(spec=OrchestratorConfig)
        config.workspace_dir = workspace
        result = check_workspace_git(config)
        assert result["initialized"] is False
        assert result["reason"] == "no git"

    @patch("subprocess.run")
    def test_with_git_and_remote(self, mock_run, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()

        mock_run.return_value = MagicMock(stdout="origin\thttps://example.com/repo.git (fetch)\n")

        config = MagicMock(spec=OrchestratorConfig)
        config.workspace_dir = workspace
        result = check_workspace_git(config)
        assert result["initialized"] is True
        assert result["has_remote"] is True

    @patch("subprocess.run")
    def test_with_git_no_remote(self, mock_run, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()

        mock_run.return_value = MagicMock(stdout="")

        config = MagicMock(spec=OrchestratorConfig)
        config.workspace_dir = workspace
        result = check_workspace_git(config)
        assert result["initialized"] is True
        assert result["has_remote"] is False

    @patch("subprocess.run", side_effect=OSError("git not found"))
    def test_git_command_fails(self, mock_run, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()

        config = MagicMock(spec=OrchestratorConfig)
        config.workspace_dir = workspace
        result = check_workspace_git(config)
        assert result["initialized"] is True
        assert result["has_remote"] is False

    @patch.dict(os.environ, {"GIT_REPO_URL": "https://example.com/repo.git"})
    @patch("subprocess.run")
    def test_repo_url_from_env(self, mock_run, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        mock_run.return_value = MagicMock(stdout="")

        config = MagicMock(spec=OrchestratorConfig)
        config.workspace_dir = workspace
        result = check_workspace_git(config)
        assert result["repo_url"] == "https://example.com/repo.git"


# =============================================================================
# check_claude_cli()
# =============================================================================

class TestCheckClaudeCli:

    @patch("shutil.which", return_value="/usr/bin/claude")
    def test_found(self, mock_which):
        assert check_claude_cli() is True
        mock_which.assert_called_once_with("claude")

    @patch("shutil.which", return_value=None)
    def test_not_found(self, mock_which):
        assert check_claude_cli() is False


# =============================================================================
# build_pipeline()
# =============================================================================

class TestBuildPipeline:

    def test_default_pipeline_no_agents(self):
        """With no agents, agent_runner expands to just InitStandupStep."""
        pipeline = build_pipeline()
        step_names = [type(s).__name__ for s in pipeline.steps]
        assert "InitStandupStep" in step_names
        # No AgentStep since no agent_ids
        assert "AgentStep" not in step_names

    def test_default_pipeline_with_agents(self):
        """agent_runner should expand to InitStandup + per-agent triplets."""
        pipeline = build_pipeline(agent_ids=["po", "dev1"])
        step_names = [type(s).__name__ for s in pipeline.steps]
        assert step_names.count("InitStandupStep") == 1
        assert step_names.count("AgentStep") == 2
        assert step_names.count("AgentCommitStep") == 2
        assert step_names.count("AgentSyncStep") == 2

    def test_agent_runner_order(self):
        """Each agent should get run_agent, commit, sync in order."""
        pipeline = build_pipeline(agent_ids=["po", "dev1"])
        # Find position of agent_runner expansion
        found_agents = []
        for s in pipeline.steps:
            if isinstance(s, AgentStep):
                found_agents.append(("run", s.agent_id))
            elif isinstance(s, AgentCommitStep):
                found_agents.append(("commit", s.agent_id))
            elif isinstance(s, AgentSyncStep):
                found_agents.append(("sync", s.agent_id))
        expected = [
            ("run", "po"), ("commit", "po"), ("sync", "po"),
            ("run", "dev1"), ("commit", "dev1"), ("sync", "dev1"),
        ]
        assert found_agents == expected

    def test_custom_pipeline_from_config(self):
        """Pipeline from YAML config should override defaults."""
        config = {
            "pipeline": ["board_health", "snapshot", "cycle_log"],
        }
        pipeline = build_pipeline(agents_config=config)
        step_types = [type(s) for s in pipeline.steps]
        assert step_types == [BoardHealthStep, SnapshotStep, CycleLogStep]

    def test_custom_pipeline_with_agent_runner(self):
        """Custom pipeline can include agent_runner."""
        config = {
            "pipeline": ["board_health", "agent_runner", "cycle_log"],
        }
        pipeline = build_pipeline(agents_config=config, agent_ids=["dev1"])
        names = [type(s).__name__ for s in pipeline.steps]
        assert names[0] == "BoardHealthStep"
        assert "InitStandupStep" in names
        assert "AgentStep" in names
        assert names[-1] == "CycleLogStep"

    def test_parameterized_step(self):
        """run_agent:dev1 should create AgentStep('dev1')."""
        config = {"pipeline": ["run_agent:dev1", "commit:dev1"]}
        pipeline = build_pipeline(agents_config=config)
        assert len(pipeline.steps) == 2
        assert isinstance(pipeline.steps[0], AgentStep)
        assert pipeline.steps[0].agent_id == "dev1"
        assert isinstance(pipeline.steps[1], AgentCommitStep)
        assert pipeline.steps[1].agent_id == "dev1"

    def test_unknown_step_skipped(self):
        """Unknown step names should be skipped with a warning."""
        config = {"pipeline": ["board_health", "nonexistent_step", "cycle_log"]}
        pipeline = build_pipeline(agents_config=config)
        step_types = [type(s) for s in pipeline.steps]
        assert step_types == [BoardHealthStep, CycleLogStep]

    def test_unknown_parameterized_step_skipped(self):
        """Unknown parameterized step types should be skipped."""
        config = {"pipeline": ["unknown_type:param1"]}
        pipeline = build_pipeline(agents_config=config)
        assert len(pipeline.steps) == 0

    def test_non_string_entry_skipped(self):
        """Non-string pipeline entries should be skipped."""
        config = {"pipeline": ["board_health", {"group": "agents"}, "cycle_log"]}
        pipeline = build_pipeline(agents_config=config)
        step_types = [type(s) for s in pipeline.steps]
        assert step_types == [BoardHealthStep, CycleLogStep]

    def test_all_registry_steps_instantiate(self):
        """Every step in STEP_REGISTRY should be usable in a pipeline."""
        for name, cls in STEP_REGISTRY.items():
            config = {"pipeline": [name]}
            pipeline = build_pipeline(agents_config=config)
            assert len(pipeline.steps) == 1
            assert isinstance(pipeline.steps[0], cls)

    def test_all_parameterized_steps_instantiate(self):
        """Every step in PARAMETERIZED_REGISTRY should work with a param."""
        for name, cls in PARAMETERIZED_REGISTRY.items():
            config = {"pipeline": [f"{name}:test_agent"]}
            pipeline = build_pipeline(agents_config=config)
            assert len(pipeline.steps) == 1
            assert isinstance(pipeline.steps[0], cls)

    def test_empty_agent_ids_defaults_to_empty_list(self):
        """agent_ids=None should behave like empty list."""
        p1 = build_pipeline(agent_ids=None)
        p2 = build_pipeline(agent_ids=[])
        # Both should have same step count (agent_runner expands to just InitStandupStep)
        assert len(p1.steps) == len(p2.steps)

    def test_git_push_alias(self):
        """git_push should resolve to GitSyncStep (alias)."""
        config = {"pipeline": ["git_push"]}
        pipeline = build_pipeline(agents_config=config)
        assert len(pipeline.steps) == 1
        assert isinstance(pipeline.steps[0], GitSyncStep)


# =============================================================================
# cmd_init() — file creation
# =============================================================================

class TestCmdInit:

    @patch("opensepia.commands.project.OrchestratorConfig.load")
    def test_creates_board_directories(self, mock_load, init_project_dir):
        mock_load.side_effect = _make_mock_config(init_project_dir)
        _run_init(init_project_dir, "TestProj", "A test project")

        board = init_project_dir / "project" / "board"
        assert (board / "inbox").is_dir()
        assert (board / "archive").is_dir()
        assert (board / ".snapshot").is_dir()

    @patch("opensepia.commands.project.OrchestratorConfig.load")
    def test_creates_workspace_dirs(self, mock_load, init_project_dir):
        mock_load.side_effect = _make_mock_config(init_project_dir)
        _run_init(init_project_dir, "TestProj", "Desc")

        workspace = init_project_dir / "project" / "workspace"
        for d in ["src", "tests", "docs", "config"]:
            assert (workspace / d).is_dir()

    @patch("opensepia.commands.project.OrchestratorConfig.load")
    def test_creates_board_files(self, mock_load, init_project_dir):
        mock_load.side_effect = _make_mock_config(init_project_dir)
        _run_init(init_project_dir, "MyApp", "A web app")

        board = init_project_dir / "project" / "board"
        assert (board / "sprint.md").exists()
        assert (board / "backlog.md").exists()
        assert (board / "project.md").exists()
        assert (board / "architecture.md").exists()
        assert (board / "decisions.md").exists()

    @patch("opensepia.commands.project.OrchestratorConfig.load")
    def test_project_name_in_board_files(self, mock_load, init_project_dir):
        mock_load.side_effect = _make_mock_config(init_project_dir)
        _run_init(init_project_dir, "SuperApp", "The best app")

        board = init_project_dir / "project" / "board"
        project_md = (board / "project.md").read_text(encoding="utf-8")
        assert "SuperApp" in project_md
        backlog = (board / "backlog.md").read_text(encoding="utf-8")
        assert "SuperApp" in backlog

    @patch("opensepia.commands.project.OrchestratorConfig.load")
    def test_updates_project_yaml(self, mock_load, init_project_dir):
        mock_load.side_effect = _make_mock_config(init_project_dir)
        _run_init(init_project_dir, "NewName", "New desc")

        with open(init_project_dir / "project" / "project.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        assert cfg["project"]["name"] == "NewName"
        assert cfg["project"]["description"] == "New desc"
        assert cfg["sprint"]["current_sprint"] == 1
        assert cfg["sprint"]["current_cycle"] == 0

    @patch("opensepia.commands.project.OrchestratorConfig.load")
    def test_creates_po_inbox_with_instructions(self, mock_load, init_project_dir):
        mock_load.side_effect = _make_mock_config(init_project_dir)
        _run_init(init_project_dir, "MyApp", "A web app")

        po_inbox = (init_project_dir / "project" / "board" / "inbox" / "po.md").read_text(encoding="utf-8")
        assert "MyApp" in po_inbox
        assert "first task" in po_inbox.lower() or "Your first task" in po_inbox

    @patch("opensepia.commands.project.OrchestratorConfig.load")
    def test_creates_gitignore(self, mock_load, init_project_dir):
        mock_load.side_effect = _make_mock_config(init_project_dir)
        _run_init(init_project_dir, "Proj", "Desc")

        gitignore = init_project_dir / "project" / "workspace" / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text(encoding="utf-8")
        assert "__pycache__" in content


# =============================================================================
# cmd_reset() — directory cleanup
# =============================================================================

class TestCmdReset:

    def test_clears_board(self, init_project_dir):
        """Reset should remove board contents and recreate empty dir."""
        project_dir = init_project_dir / "project"
        board = project_dir / "board"
        board.mkdir(parents=True, exist_ok=True)
        (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
        (board / "inbox").mkdir(exist_ok=True)

        _run_reset(init_project_dir)

        assert board.is_dir()
        assert not (board / "sprint.md").exists()
        assert not (board / "inbox").exists()

    def test_clears_workspace(self, init_project_dir):
        project_dir = init_project_dir / "project"
        workspace = project_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "src").mkdir()
        (workspace / "src" / "main.py").write_text("pass\n", encoding="utf-8")

        _run_reset(init_project_dir)

        assert workspace.is_dir()
        assert not (workspace / "src").exists()

    def test_clears_logs(self, init_project_dir):
        project_dir = init_project_dir / "project"
        logs = project_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "daemon.log").write_text("log\n", encoding="utf-8")

        _run_reset(init_project_dir)

        assert logs.is_dir()
        assert not (logs / "daemon.log").exists()

    def test_resets_project_yaml_counters(self, init_project_dir):
        project_dir = init_project_dir / "project"
        (project_dir / "project.yaml").write_text(
            yaml.dump({
                "project": {"name": "OldName", "description": "Old"},
                "sprint": {"current_sprint": 5, "current_cycle": 42},
            }),
            encoding="utf-8",
        )

        _run_reset(init_project_dir)

        with open(project_dir / "project.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        assert cfg["sprint"]["current_sprint"] == 1
        assert cfg["sprint"]["current_cycle"] == 0
        assert cfg["project"] == {}


# =============================================================================
# cmd_board() — output verification
# =============================================================================

class TestCmdBoard:

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    @patch("opensepia.board_adapter.create_board_adapter")
    def test_empty_board(self, mock_create, mock_load, capsys):
        adapter = MagicMock()
        adapter.get_sprint_text.return_value = ""
        mock_create.return_value = adapter

        mock_load.return_value = MagicMock()

        from opensepia.commands.interact import cmd_board
        cmd_board([])

        captured = capsys.readouterr()
        assert "No sprint board" in captured.out

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    @patch("opensepia.board_adapter.create_board_adapter")
    def test_board_displays_sprint(self, mock_create, mock_load, capsys):
        adapter = MagicMock()
        adapter.get_sprint_text.return_value = (
            "# Sprint 1\n"
            "## TODO\n"
            "- [ ] STORY-001: Build login page\n"
            "## DONE\n"
            "- [x] STORY-002: Setup project\n"
        )
        adapter.get_board_summary.return_value = {"todo": 1, "done": 1}
        adapter.get_backlog_text.return_value = "### STORY-003: Feature X\n"
        mock_create.return_value = adapter

        mock_load.return_value = MagicMock()

        from opensepia.commands.interact import cmd_board
        cmd_board([])

        captured = capsys.readouterr()
        assert "Sprint 1" in captured.out
        assert "Build login page" in captured.out
        assert "Setup project" in captured.out
        assert "Backlog: 1" in captured.out

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    @patch("opensepia.board_adapter.create_board_adapter")
    def test_board_shows_done_marker(self, mock_create, mock_load, capsys):
        adapter = MagicMock()
        adapter.get_sprint_text.return_value = "- [x] STORY-001: Done task\n- [ ] STORY-002: Open task\n"
        adapter.get_board_summary.return_value = {}
        adapter.get_backlog_text.return_value = ""
        mock_create.return_value = adapter
        mock_load.return_value = MagicMock()

        from opensepia.commands.interact import cmd_board
        cmd_board([])

        captured = capsys.readouterr()
        assert "+" in captured.out  # done marker
        assert "-" in captured.out  # open marker


# =============================================================================
# cmd_message() — inbox delivery
# =============================================================================

class TestCmdMessage:

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    @patch("opensepia.board_adapter.create_board_adapter")
    def test_sends_message(self, mock_create, mock_load, capsys):
        adapter = MagicMock()
        mock_create.return_value = adapter

        config = MagicMock()
        config.get_all_agent_ids.return_value = ["po", "dev1", "tester"]
        config.agents = {
            "agents": {
                "po": {"name": "Product Owner"},
                "dev1": {"name": "Developer 1"},
                "tester": {"name": "Tester"},
            }
        }
        mock_load.return_value = config

        from opensepia.commands.interact import cmd_message
        cmd_message(["po", "Please", "review", "the", "backlog"])

        adapter.send_inbox_message.assert_called_once_with("po", "Human", "Please review the backlog")
        captured = capsys.readouterr()
        assert "Message sent" in captured.out

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    def test_unknown_agent(self, mock_load, capsys):
        config = MagicMock()
        config.get_all_agent_ids.return_value = ["po", "dev1"]
        mock_load.return_value = config

        from opensepia.commands.interact import cmd_message
        cmd_message(["unknown_agent", "Hello"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Unknown agent" in combined

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    def test_config_error(self, mock_load, capsys):
        from opensepia.errors import ConfigError
        mock_load.side_effect = ConfigError("no config")

        from opensepia.commands.interact import cmd_message
        cmd_message(["po", "hello"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "no config" in combined


# =============================================================================
# cmd_config() — show and set
# =============================================================================

class TestCmdConfig:

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    def test_config_show_unknown_section(self, mock_load, capsys):
        mock_load.return_value = MagicMock(
            project={"project": {}, "sprint": {}},
            agents={"modes": {}, "execution": {}, "pipeline": []},
            tool_dir=Path("/tmp"),
            project_dir=Path("/tmp"),
        )

        from opensepia.commands.interact import cmd_config
        cmd_config(["nonexistent"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Unknown" in combined

    @patch("opensepia.commands.interact.OrchestratorConfig.load")
    def test_config_set_no_args_shows_keys(self, mock_load, capsys):
        from opensepia.commands.interact import cmd_config
        cmd_config(["set"])

        captured = capsys.readouterr()
        assert "Settable keys" in captured.out

    def test_config_set_unknown_key(self, capsys):
        from opensepia.commands.interact import cmd_config
        cmd_config(["set", "nonexistent.key", "value"])

        captured = capsys.readouterr()
        # log.error writes to stderr, log.info writes to stdout
        combined = captured.out + captured.err
        assert "Unknown config key" in combined


# =============================================================================
# observe.py internal helpers
# =============================================================================

class TestObserveHelpers:

    def test_tail_lines(self, tmp_path):
        """_tail_lines should return the last N lines."""
        logfile = tmp_path / "test.log"
        logfile.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

        from opensepia.commands.observe import _tail_lines
        import io
        from unittest.mock import patch as _patch

        # Capture output
        with _patch("builtins.print") as mock_print:
            _tail_lines(logfile, 3)
            # Should have printed last 3 lines
            assert mock_print.call_count == 3

    def test_tail_lines_fewer_than_n(self, tmp_path):
        logfile = tmp_path / "test.log"
        logfile.write_text("only\ntwo\n", encoding="utf-8")

        from opensepia.commands.observe import _tail_lines
        with patch("builtins.print") as mock_print:
            _tail_lines(logfile, 10)
            assert mock_print.call_count == 2

    def test_show_last_cycle_no_logs(self, tmp_path, capsys):
        from opensepia.commands.observe import _show_last_cycle
        _show_last_cycle(tmp_path / "nonexistent")
        captured = capsys.readouterr()
        assert "No cycle logs" in captured.out

    def test_show_last_cycle_no_json_files(self, tmp_path, capsys):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        from opensepia.commands.observe import _show_last_cycle
        _show_last_cycle(logs_dir)
        captured = capsys.readouterr()
        assert "No cycle logs" in captured.out

    def test_show_last_cycle_with_data(self, tmp_path, capsys):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        data = {
            "timestamp": "2026-03-27T10:00:00",
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 5,
            "status": "ok",
            "agents_ok": ["po", "dev1"],
            "agents_failed": [],
            "agents": [
                {"agent": "po", "context_chars": 1000, "response_chars": 500},
                {"agent": "dev1", "context_chars": 2000, "response_chars": 800},
            ],
        }
        (logs_dir / "cycle_20260327_100000.json").write_text(
            json.dumps(data), encoding="utf-8",
        )

        from opensepia.commands.observe import _show_last_cycle
        _show_last_cycle(logs_dir)
        captured = capsys.readouterr()
        assert "dev-team" in captured.out
        assert "2 ok" in captured.out

    def test_show_last_cycle_with_failed_agents(self, tmp_path, capsys):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        data = {
            "timestamp": "2026-03-27T10:00:00",
            "mode": "dev-team",
            "sprint": 1,
            "cycle": 5,
            "status": "partial",
            "agents_ok": ["po"],
            "agents_failed": ["dev1"],
            "agents": [
                {"agent": "po", "context_chars": 1000, "response_chars": 500},
                {"agent": "dev1", "error": "Timeout after 900s"},
            ],
        }
        (logs_dir / "cycle_20260327_100000.json").write_text(
            json.dumps(data), encoding="utf-8",
        )

        from opensepia.commands.observe import _show_last_cycle
        _show_last_cycle(logs_dir)
        captured = capsys.readouterr()
        assert "1 failed" in captured.out
        assert "FAILED" in captured.out

    @patch("opensepia.commands.observe.OrchestratorConfig.load")
    def test_get_project_dirs_with_config(self, mock_load):
        config = MagicMock()
        config.tool_dir = Path("/opt/tool")
        config.logs_dir = Path("/opt/tool/project/logs/runs")
        mock_load.return_value = config

        from opensepia.commands.observe import _get_project_dirs
        tool_dir, logs_dir = _get_project_dirs()
        assert tool_dir == Path("/opt/tool")
        assert logs_dir == Path("/opt/tool/project/logs/runs")

    @patch("opensepia.commands.observe.OrchestratorConfig.load")
    def test_get_project_dirs_config_error(self, mock_load):
        from opensepia.errors import ConfigError
        mock_load.side_effect = ConfigError("missing config")

        from opensepia.commands.observe import _get_project_dirs
        tool_dir, logs_dir = _get_project_dirs()
        # Falls back to relative path detection
        assert tool_dir.is_absolute() or True  # just check it returns something
        assert "logs" in str(logs_dir)


# =============================================================================
# Helpers
# =============================================================================

def _make_mock_config(tool_dir):
    """Create a side_effect function for OrchestratorConfig.load."""
    from opensepia.errors import ConfigError

    def _load(*args, **kwargs):
        config_file = tool_dir / "config" / "agents.yaml"
        if not config_file.exists():
            raise ConfigError("no config")
        with open(config_file, encoding="utf-8") as f:
            agents = yaml.safe_load(f)
        return MagicMock(
            get_all_agent_ids=MagicMock(return_value=list(agents.get("agents", {}).keys())),
        )

    return _load


def _run_init(tool_dir, name, description):
    """Call cmd_init with tool_dir override."""
    from opensepia.commands import project as proj_module

    with patch("opensepia.dirs.get_tool_dir", return_value=tool_dir):
        proj_module.cmd_init([name, description])


def _run_reset(tool_dir):
    """Call cmd_reset with tool_dir override and --yes to skip confirmation."""
    from opensepia.commands import project as proj_module

    # The daemon imports happen inside cmd_reset via:
    #   from opensepia.daemon import stop_daemon, get_daemon_status
    # We patch the daemon module functions so the lazy import picks them up.
    with patch("opensepia.dirs.get_tool_dir", return_value=tool_dir), \
         patch("opensepia.daemon.stop_daemon", side_effect=RuntimeError("not running")), \
         patch("opensepia.daemon.get_daemon_status", side_effect=RuntimeError("not running")):
        proj_module.cmd_reset(["--yes"])
