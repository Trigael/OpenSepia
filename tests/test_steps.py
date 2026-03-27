"""
Unit tests for pipeline steps.

Tests each step's execute() method with mocked dependencies.
No external API calls or Claude CLI invocations.
"""

import json
import os
from dataclasses import field
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import yaml

from opensepia.pipeline import PipelineContext
from opensepia.board_adapter import BoardAdapter
from opensepia.steps.board_health import BoardHealthStep, SnapshotStep, CRITICAL_FILES, SNAPSHOT_FILES
from opensepia.steps.sprint_check import SprintCheckStep, SprintSyncStep
from opensepia.steps.board_sync import BoardSyncStep
from opensepia.steps.standup_sync import StandupSyncStep
from opensepia.steps.merge_mrs import MergeMRsStep
from opensepia.steps.git_sync import GitSyncStep
from opensepia.steps.logging_step import CycleLogStep
from opensepia.steps.alerting import AlertingStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path, **overrides):
    """Create a minimal PipelineContext rooted in tmp_path."""
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

    defaults = dict(
        mode="dev-team",
        tool_dir=tmp_path,
        project_dir=project_dir,
        agents_config={"agents": {"po": {"name": "PO"}, "pm": {"name": "PM"}, "dev1": {"name": "Dev1"}}},
        project_config={"sprint": {"current_sprint": 1, "current_cycle": 3, "cycles_per_sprint": 10}},
        board_dir=board_dir,
        workspace_dir=workspace_dir,
        config_dir=config_dir,
        logs_dir=logs_dir,
        sprint_num=1,
        cycle_num=3,
        agent_ids=["po", "pm", "dev1"],
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


def _mock_board_adapter():
    """Return a MagicMock that is an instance of BoardAdapter (but NOT BoardServerAdapter)."""
    adapter = MagicMock(spec=BoardAdapter)
    adapter.check_board_health.return_value = {"sprint.md": True, "backlog.md": True}
    adapter.create_snapshot.return_value = 5
    adapter.get_sprint_number.return_value = 1
    adapter.get_active_story_ids.return_value = ["STORY-001", "STORY-002"]
    return adapter


def _mock_board_server_adapter():
    """Return a MagicMock that appears to be a BoardServerAdapter instance."""
    from opensepia.board_adapter_server import BoardServerAdapter
    adapter = MagicMock(spec=BoardServerAdapter)
    adapter.check_board_health.return_value = {"sprint.md": True, "backlog.md": True}
    adapter.create_snapshot.return_value = 5
    adapter.get_sprint_number.return_value = 1
    adapter.get_active_story_ids.return_value = ["STORY-001"]
    return adapter


# ===========================================================================
# BoardHealthStep
# ===========================================================================

class TestBoardHealthStep:

    def test_name_and_critical(self):
        step = BoardHealthStep()
        assert step.name == "board_health"
        assert step.critical is False

    def test_healthy_board_with_adapter(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.check_board_health.return_value = {"sprint.md": True, "backlog.md": True}
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        result = BoardHealthStep().execute(ctx)

        adapter.check_board_health.assert_called_once()
        adapter.ensure_board_ready.assert_called_once()
        assert result is ctx

    def test_unhealthy_board_with_adapter_triggers_restore(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.check_board_health.return_value = {"sprint.md": False, "backlog.md": True}
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        # _try_restore will be called but won't find snapshot dir
        result = BoardHealthStep().execute(ctx)

        adapter.check_board_health.assert_called_once()
        adapter.ensure_board_ready.assert_called_once()
        assert result is ctx

    def test_fallback_no_adapter_all_present(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        board = ctx.board_dir
        for f in CRITICAL_FILES:
            (board / f).write_text("content", encoding="utf-8")

        result = BoardHealthStep().execute(ctx)
        assert result is ctx

    def test_fallback_creates_inbox_files(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        board = ctx.board_dir
        for f in CRITICAL_FILES:
            (board / f).write_text("content", encoding="utf-8")

        BoardHealthStep().execute(ctx)

        inbox_dir = board / "inbox"
        assert inbox_dir.exists()
        for agent in ["po", "pm", "dev1"]:
            assert (inbox_dir / f"{agent}.md").exists()

    def test_fallback_missing_files_triggers_restore(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        # Don't create critical files -> missing

        with patch("opensepia.steps.board_health.BoardHealthStep._try_restore") as mock_restore:
            BoardHealthStep().execute(ctx)
            mock_restore.assert_called_once()

    def test_try_restore_snapshot_path(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        board = ctx.board_dir
        snapshot_dir = board / ".snapshot"
        snapshot_dir.mkdir()

        with patch("opensepia.board.restore.restore_from_snapshot") as mock_snap, \
             patch("opensepia.board.restore.restore_from_provider") as mock_prov:
            # After restore_from_snapshot, files still missing -> tries provider
            step = BoardHealthStep()
            step._try_restore(ctx, board)
            mock_snap.assert_called_once_with(board)
            mock_prov.assert_called_once_with(board)

    def test_try_restore_no_snapshot_dir(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        board = ctx.board_dir

        with patch("opensepia.board.restore.restore_from_snapshot") as mock_snap, \
             patch("opensepia.board.restore.restore_from_provider") as mock_prov:
            step = BoardHealthStep()
            step._try_restore(ctx, board)
            mock_snap.assert_not_called()
            mock_prov.assert_called_once_with(board)


# ===========================================================================
# SnapshotStep
# ===========================================================================

class TestSnapshotStep:

    def test_name_and_critical(self):
        step = SnapshotStep()
        assert step.name == "snapshot"
        assert step.critical is False

    def test_dry_run_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        result = SnapshotStep().execute(ctx)
        assert result is ctx
        # No snapshot dir created
        assert not (ctx.board_dir / ".snapshot").exists()

    def test_with_adapter(self, tmp_path):
        adapter = _mock_board_adapter()
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        result = SnapshotStep().execute(ctx)

        adapter.create_snapshot.assert_called_once()
        assert result is ctx

    def test_fallback_copies_files(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        board = ctx.board_dir
        # Create some snapshot-eligible files
        (board / "sprint.md").write_text("sprint content", encoding="utf-8")
        (board / "backlog.md").write_text("backlog content", encoding="utf-8")
        (board / "project.md").write_text("project content", encoding="utf-8")

        SnapshotStep().execute(ctx)

        snapshot_dir = board / ".snapshot"
        assert snapshot_dir.exists()
        assert (snapshot_dir / "sprint.md.bak").exists()
        assert (snapshot_dir / "backlog.md.bak").exists()
        assert (snapshot_dir / "project.md.bak").exists()
        # Missing files should not be copied
        assert not (snapshot_dir / "architecture.md.bak").exists()

    def test_fallback_no_files(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        result = SnapshotStep().execute(ctx)
        assert result is ctx


# ===========================================================================
# SprintCheckStep
# ===========================================================================

class TestSprintCheckStep:

    def test_name_and_critical(self):
        step = SprintCheckStep()
        assert step.name == "sprint_check"
        assert step.critical is False

    def test_cycle_increment(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        # current_cycle=3, cycles_per_sprint=10 -> increment to 4
        (ctx.project_dir / "project.yaml").write_text("", encoding="utf-8")

        SprintCheckStep().execute(ctx)

        assert ctx.cycle_num == 4
        assert ctx.project_config["sprint"]["current_cycle"] == 4
        # project.yaml should be written
        saved = yaml.safe_load((ctx.project_dir / "project.yaml").read_text())
        assert saved["sprint"]["current_cycle"] == 4

    def test_dry_run_skips_increment(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        SprintCheckStep().execute(ctx)

        # Should use existing cycle, not increment
        assert ctx.cycle_num == 3
        assert ctx.project_config["sprint"]["current_cycle"] == 3

    def test_no_increment_flag(self, tmp_path):
        ctx = _make_ctx(tmp_path, no_increment=True)
        SprintCheckStep().execute(ctx)

        assert ctx.cycle_num == 3
        assert ctx.project_config["sprint"]["current_cycle"] == 3

    def test_sprint_end_detection(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ctx.project_config["sprint"]["current_cycle"] = 10
        ctx.project_config["sprint"]["cycles_per_sprint"] = 10
        (ctx.project_dir / "project.yaml").write_text("", encoding="utf-8")

        with patch.object(SprintCheckStep, "_run_retrospective"):
            SprintCheckStep().execute(ctx)

        assert ctx.skip_agents is True
        # Sprint should advance
        assert ctx.sprint_num == 2
        assert ctx.cycle_num == 0
        assert ctx.project_config["sprint"]["current_sprint"] == 2
        assert ctx.project_config["sprint"]["current_cycle"] == 0

    def test_sprint_end_with_board_adapter(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_sprint_number.return_value = 3  # Board says sprint 3
        ctx = _make_ctx(tmp_path, board_adapter=adapter)
        ctx.project_config["sprint"]["current_cycle"] = 10
        ctx.project_config["sprint"]["cycles_per_sprint"] = 10
        (ctx.project_dir / "project.yaml").write_text("", encoding="utf-8")

        with patch.object(SprintCheckStep, "_run_retrospective"):
            SprintCheckStep().execute(ctx)

        # Should use board's sprint number since it's higher
        assert ctx.sprint_num == 3

    def test_sprint_end_reads_sprint_md_fallback(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        ctx.project_config["sprint"]["current_cycle"] = 10
        ctx.project_config["sprint"]["cycles_per_sprint"] = 10
        (ctx.project_dir / "project.yaml").write_text("", encoding="utf-8")
        (ctx.board_dir / "sprint.md").write_text("# Sprint 5\n\nStuff here", encoding="utf-8")

        with patch.object(SprintCheckStep, "_run_retrospective"):
            SprintCheckStep().execute(ctx)

        # Sprint 5 from file > sprint 1 + 1 = 2
        assert ctx.sprint_num == 5

    def test_save_project_writes_yaml(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        (ctx.project_dir / "project.yaml").write_text("", encoding="utf-8")

        step = SprintCheckStep()
        step._save_project(ctx)

        saved = yaml.safe_load((ctx.project_dir / "project.yaml").read_text())
        assert saved["sprint"]["current_sprint"] == 1


# ===========================================================================
# SprintSyncStep
# ===========================================================================

class TestSprintSyncStep:

    def test_name_and_critical(self):
        step = SprintSyncStep()
        assert step.name == "sprint_sync"
        assert step.critical is False

    def test_sync_with_adapter_advances(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_sprint_number.return_value = 3
        ctx = _make_ctx(tmp_path, board_adapter=adapter)
        (ctx.project_dir / "project.yaml").write_text("", encoding="utf-8")

        SprintSyncStep().execute(ctx)

        assert ctx.sprint_num == 3
        assert ctx.project_config["sprint"]["current_sprint"] == 3
        assert ctx.project_config["sprint"]["current_cycle"] == 1
        saved = yaml.safe_load((ctx.project_dir / "project.yaml").read_text())
        assert saved["sprint"]["current_sprint"] == 3

    def test_sync_with_adapter_no_advance(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_sprint_number.return_value = 1  # Same as current
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        result = SprintSyncStep().execute(ctx)
        # Should not change
        assert ctx.sprint_num == 1
        assert result is ctx

    def test_sync_never_goes_backward(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_sprint_number.return_value = 0  # Lower
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        SprintSyncStep().execute(ctx)
        assert ctx.sprint_num == 1  # Unchanged

    def test_sync_fallback_no_sprint_md(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        # No sprint.md file -> early return
        result = SprintSyncStep().execute(ctx)
        assert result is ctx

    def test_sync_fallback_parses_sprint_md(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        (ctx.board_dir / "sprint.md").write_text(
            "# Sprint 1\nold stuff\n# Sprint 4\nnew stuff", encoding="utf-8"
        )
        (ctx.project_dir / "project.yaml").write_text("", encoding="utf-8")

        SprintSyncStep().execute(ctx)

        assert ctx.sprint_num == 4
        assert ctx.project_config["sprint"]["current_sprint"] == 4

    def test_sync_fallback_no_sprint_match(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        (ctx.board_dir / "sprint.md").write_text("no sprint header here", encoding="utf-8")

        result = SprintSyncStep().execute(ctx)
        assert ctx.sprint_num == 1  # Unchanged


# ===========================================================================
# BoardSyncStep
# ===========================================================================

class TestBoardSyncStep:

    def test_name_and_critical(self):
        step = BoardSyncStep()
        assert step.name == "board_sync"
        assert step.critical is False

    def test_dry_run_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        result = BoardSyncStep().execute(ctx)
        assert result is ctx

    def test_skip_with_board_server_adapter(self, tmp_path):
        adapter = _mock_board_server_adapter()
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        result = BoardSyncStep().execute(ctx)
        assert result is ctx

    def test_no_provider_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)

        with patch("opensepia.integrations.providers.detect_provider", return_value=None):
            result = BoardSyncStep().execute(ctx)
        assert result is ctx

    def test_provider_disabled_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        mock_provider = MagicMock()
        mock_provider.enabled = False

        with patch("opensepia.integrations.providers.detect_provider", return_value=mock_provider):
            result = BoardSyncStep().execute(ctx)
        assert result is ctx

    def test_non_server_adapter_does_not_skip(self, tmp_path):
        """A regular BoardAdapter (not BoardServerAdapter) should not cause skip."""
        adapter = _mock_board_adapter()
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        with patch("opensepia.integrations.providers.detect_provider", return_value=None):
            result = BoardSyncStep().execute(ctx)
        assert result is ctx

    def test_exception_handled_gracefully(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)

        with patch("opensepia.integrations.providers.detect_provider", side_effect=ImportError("boom")):
            result = BoardSyncStep().execute(ctx)
        assert result is ctx


# ===========================================================================
# StandupSyncStep
# ===========================================================================

class TestStandupSyncStep:

    def test_name_and_critical(self):
        step = StandupSyncStep()
        assert step.name == "standup_sync"
        assert step.critical is False

    def test_dry_run_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        result = StandupSyncStep().execute(ctx)
        assert result is ctx

    def test_skip_with_board_server_adapter(self, tmp_path):
        adapter = _mock_board_server_adapter()
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        result = StandupSyncStep().execute(ctx)
        assert result is ctx

    def test_no_provider_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)

        with patch("opensepia.integrations.providers.detect_provider", return_value=None):
            result = StandupSyncStep().execute(ctx)
        assert result is ctx

    def test_provider_disabled_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        mock_provider = MagicMock()
        mock_provider.enabled = False

        with patch("opensepia.integrations.providers.detect_provider", return_value=mock_provider):
            result = StandupSyncStep().execute(ctx)
        assert result is ctx

    def test_non_server_adapter_does_not_skip(self, tmp_path):
        adapter = _mock_board_adapter()
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        mock_provider = MagicMock()
        mock_provider.enabled = True

        with patch("opensepia.integrations.providers.detect_provider", return_value=mock_provider), \
             patch("opensepia.board.comments.post_standup_to_provider", return_value=2):
            result = StandupSyncStep().execute(ctx)
        assert result is ctx

    def test_exception_handled_gracefully(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)

        with patch("opensepia.integrations.providers.detect_provider", side_effect=ImportError("boom")):
            result = StandupSyncStep().execute(ctx)
        assert result is ctx


# ===========================================================================
# MergeMRsStep
# ===========================================================================

class TestMergeMRsStep:

    def test_name_and_critical(self):
        step = MergeMRsStep()
        assert step.name == "merge_mrs"
        assert step.critical is False

    def test_dry_run_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        result = MergeMRsStep().execute(ctx)
        assert result is ctx

    def test_skip_with_board_server_adapter(self, tmp_path):
        adapter = _mock_board_server_adapter()
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        result = MergeMRsStep().execute(ctx)
        assert result is ctx

    def test_no_provider_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)

        with patch("opensepia.integrations.providers.detect_provider", return_value=None):
            result = MergeMRsStep().execute(ctx)
        assert result is ctx

    def test_provider_disabled_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)
        mock_provider = MagicMock()
        mock_provider.enabled = False

        with patch("opensepia.integrations.providers.detect_provider", return_value=mock_provider):
            result = MergeMRsStep().execute(ctx)
        assert result is ctx

    def test_non_server_adapter_does_not_skip(self, tmp_path):
        adapter = _mock_board_adapter()
        ctx = _make_ctx(tmp_path, board_adapter=adapter)

        mock_provider = MagicMock()
        mock_provider.enabled = True

        with patch("opensepia.integrations.providers.detect_provider", return_value=mock_provider), \
             patch("opensepia.board.merge.merge_approved_mrs", return_value=(1, 0)):
            result = MergeMRsStep().execute(ctx)
        assert result is ctx

    def test_exception_handled_gracefully(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None)

        with patch("opensepia.integrations.providers.detect_provider", side_effect=ImportError("boom")):
            result = MergeMRsStep().execute(ctx)
        assert result is ctx


# ===========================================================================
# GitSyncStep
# ===========================================================================

class TestGitSyncStep:

    def test_name_and_critical(self):
        step = GitSyncStep()
        assert step.name == "git_sync"
        assert step.critical is False

    def test_dry_run_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        result = GitSyncStep().execute(ctx)
        assert result is ctx

    def test_no_workspace_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        # Remove workspace dir
        ctx.workspace_dir.rmdir()
        result = GitSyncStep().execute(ctx)
        assert result is ctx

    def test_no_git_dir_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        # workspace exists but no .git
        result = GitSyncStep().execute(ctx)
        assert result is ctx

    def test_no_repo_url_skips(self, tmp_path, monkeypatch):
        ctx = _make_ctx(tmp_path)
        (ctx.workspace_dir / ".git").mkdir()
        monkeypatch.delenv("GIT_REPO_URL", raising=False)

        result = GitSyncStep().execute(ctx)
        assert result is ctx

    def test_branch_name_with_adapter(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_active_story_ids.return_value = ["STORY-001", "BUG-002"]
        ctx = _make_ctx(tmp_path, board_adapter=adapter, sprint_num=2, cycle_num=5)

        step = GitSyncStep()
        branch = step._compute_branch_name(ctx)

        assert branch == "ai-team/story001-bug002-s2c5"

    def test_branch_name_with_adapter_no_stories(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_active_story_ids.return_value = []
        ctx = _make_ctx(tmp_path, board_adapter=adapter, sprint_num=1, cycle_num=3)

        step = GitSyncStep()
        branch = step._compute_branch_name(ctx)

        assert branch == "ai-team/sprint-1-cycle-3"

    def test_branch_name_with_adapter_exception(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_active_story_ids.side_effect = ValueError("fail")
        ctx = _make_ctx(tmp_path, board_adapter=adapter, sprint_num=1, cycle_num=2)

        step = GitSyncStep()
        branch = step._compute_branch_name(ctx)

        assert branch == "ai-team/sprint-1-cycle-2"

    def test_branch_name_fallback_sprint_md(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None, sprint_num=1, cycle_num=2)
        (ctx.board_dir / "sprint.md").write_text(
            "### STORY-010 Some story\n**Status**: IN_PROGRESS\n"
            "### BUG-003 Some bug\n**Status**: REVIEW\n",
            encoding="utf-8",
        )

        step = GitSyncStep()
        branch = step._compute_branch_name(ctx)

        assert branch == "ai-team/story010-bug003-s1c2"

    def test_branch_name_fallback_no_active_stories(self, tmp_path):
        ctx = _make_ctx(tmp_path, board_adapter=None, sprint_num=2, cycle_num=7)
        (ctx.board_dir / "sprint.md").write_text(
            "### STORY-010 Some story\n**Status**: DONE\n", encoding="utf-8"
        )

        step = GitSyncStep()
        branch = step._compute_branch_name(ctx)

        assert branch == "ai-team/sprint-2-cycle-7"

    def test_branch_name_limits_to_3_stories(self, tmp_path):
        adapter = _mock_board_adapter()
        adapter.get_active_story_ids.return_value = [
            "STORY-001", "STORY-002", "STORY-003", "STORY-004"
        ]
        ctx = _make_ctx(tmp_path, board_adapter=adapter, sprint_num=1, cycle_num=1)

        step = GitSyncStep()
        branch = step._compute_branch_name(ctx)

        # Only first 3
        assert branch == "ai-team/story001-story002-story003-s1c1"


# ===========================================================================
# CycleLogStep
# ===========================================================================

class TestCycleLogStep:

    def test_name_and_critical(self):
        step = CycleLogStep()
        assert step.name == "cycle_log"
        assert step.critical is False

    def test_dry_run_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        result = CycleLogStep().execute(ctx)
        assert result is ctx

    def test_creates_json_log(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GIT_REPO_URL", raising=False)
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("BOARD_SERVER_URL", raising=False)

        ctx = _make_ctx(tmp_path)
        ctx.agent_results = [
            {"agent_id": "po", "agent_name": "PO", "context_size": 100, "response_size": 50},
            {"agent_id": "dev1", "agent_name": "Dev1", "error": "timeout"},
        ]

        CycleLogStep().execute(ctx)

        # Find the log file
        log_files = list(ctx.logs_dir.glob("cycle_*.json"))
        assert len(log_files) == 1

        data = json.loads(log_files[0].read_text())
        assert data["mode"] == "dev-team"
        assert data["sprint"] == 1
        assert data["cycle"] == 3
        assert data["agents_ok"] == ["PO"]
        assert data["agents_failed"] == ["Dev1"]
        assert data["agents_ok_count"] == 1
        assert data["agents_failed_count"] == 1
        assert data["status"] == "error"
        assert data["git_sync"] is False
        assert data["provider_sync"] is False

    def test_all_agents_ok(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GIT_REPO_URL", raising=False)
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("BOARD_SERVER_URL", raising=False)

        ctx = _make_ctx(tmp_path)
        ctx.agent_results = [
            {"agent_id": "po", "agent_name": "PO", "context_size": 100, "response_size": 50},
        ]

        CycleLogStep().execute(ctx)

        log_files = list(ctx.logs_dir.glob("cycle_*.json"))
        data = json.loads(log_files[0].read_text())
        assert data["status"] == "ok"
        assert data["agents_failed"] == []

    def test_creates_logs_dir_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GIT_REPO_URL", raising=False)
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("BOARD_SERVER_URL", raising=False)

        ctx = _make_ctx(tmp_path)
        # Remove logs dir
        ctx.logs_dir.rmdir()
        ctx.agent_results = []

        CycleLogStep().execute(ctx)
        assert ctx.logs_dir.exists()

    def test_env_flags(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_REPO_URL", "https://example.com/repo.git")
        monkeypatch.setenv("GITLAB_TOKEN", "glpat-fake")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("BOARD_SERVER_URL", raising=False)

        ctx = _make_ctx(tmp_path)
        ctx.agent_results = []

        CycleLogStep().execute(ctx)

        log_files = list(ctx.logs_dir.glob("cycle_*.json"))
        data = json.loads(log_files[0].read_text())
        assert data["git_sync"] is True
        assert data["provider_sync"] is True


# ===========================================================================
# AlertingStep
# ===========================================================================

class TestAlertingStep:

    def test_name_and_critical(self):
        step = AlertingStep()
        assert step.name == "alerting"
        assert step.critical is False

    def test_dry_run_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        ctx.agent_results = [{"agent_name": "Dev1", "error": "boom"}]
        result = AlertingStep().execute(ctx)
        assert result is ctx

    def test_no_failures_skips(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ctx.agent_results = [
            {"agent_name": "PO"},
            {"agent_name": "Dev1"},
        ]

        result = AlertingStep().execute(ctx)
        assert result is ctx
        # No alerts.log should be created/written
        alerts_log = ctx.project_dir / "logs" / "alerts.log"
        assert not alerts_log.exists()

    def test_alert_log_written_on_failure(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ctx.agent_results = [
            {"agent_name": "PO"},
            {"agent_name": "Dev1", "error": "timeout"},
            {"agent_name": "PM", "error": "parse failed"},
        ]

        with patch.object(AlertingStep, "_create_provider_alert"):
            AlertingStep().execute(ctx)

        alerts_log = ctx.project_dir / "logs" / "alerts.log"
        assert alerts_log.exists()
        content = alerts_log.read_text()
        assert "Dev1" in content
        assert "PM" in content
        assert "dev-team" in content

    def test_alert_creates_logs_dir(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ctx.agent_results = [{"agent_name": "Dev1", "error": "boom"}]
        # Remove the logs dir that _make_ctx creates
        logs_dir = ctx.project_dir / "logs"
        # Remove runs subdir first, then logs
        if (logs_dir / "runs").exists():
            (logs_dir / "runs").rmdir()
        if logs_dir.exists():
            logs_dir.rmdir()

        with patch.object(AlertingStep, "_create_provider_alert"):
            AlertingStep().execute(ctx)

        assert (ctx.project_dir / "logs" / "alerts.log").exists()

    def test_provider_alert_no_provider(self, tmp_path):
        ctx = _make_ctx(tmp_path)

        with patch("opensepia.integrations.providers.detect_provider", return_value=None):
            step = AlertingStep()
            step._create_provider_alert(ctx, "Dev1", __import__("datetime").datetime.now())

    def test_provider_alert_calls_create_issue(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_provider.create_issue.return_value = {"iid": 42}

        with patch("opensepia.integrations.providers.detect_provider", return_value=mock_provider):
            step = AlertingStep()
            step._create_provider_alert(ctx, "Dev1", __import__("datetime").datetime.now())

        mock_provider.create_issue.assert_called_once()
        call_args = mock_provider.create_issue.call_args
        assert "Dev1" in call_args[0][0]  # title
        assert "alert" in call_args[1]["labels"]

    def test_provider_alert_exception_handled(self, tmp_path):
        ctx = _make_ctx(tmp_path)

        with patch("opensepia.integrations.providers.detect_provider", side_effect=ImportError("fail")):
            step = AlertingStep()
            # Should not raise
            step._create_provider_alert(ctx, "Dev1", __import__("datetime").datetime.now())


# ===========================================================================
# Step protocol conformance
# ===========================================================================

class TestStepProtocol:
    """Verify all steps implement the Step protocol."""

    @pytest.mark.parametrize("step_cls", [
        BoardHealthStep, SnapshotStep, SprintCheckStep, SprintSyncStep,
        BoardSyncStep, StandupSyncStep, MergeMRsStep, GitSyncStep,
        CycleLogStep, AlertingStep,
    ])
    def test_has_name(self, step_cls):
        step = step_cls()
        assert isinstance(step.name, str)
        assert len(step.name) > 0

    @pytest.mark.parametrize("step_cls", [
        BoardHealthStep, SnapshotStep, SprintCheckStep, SprintSyncStep,
        BoardSyncStep, StandupSyncStep, MergeMRsStep, GitSyncStep,
        CycleLogStep, AlertingStep,
    ])
    def test_has_critical(self, step_cls):
        step = step_cls()
        assert isinstance(step.critical, bool)

    @pytest.mark.parametrize("step_cls", [
        BoardHealthStep, SnapshotStep, SprintCheckStep, SprintSyncStep,
        BoardSyncStep, StandupSyncStep, MergeMRsStep, GitSyncStep,
        CycleLogStep, AlertingStep,
    ])
    def test_has_execute(self, step_cls):
        step = step_cls()
        assert callable(step.execute)

    @pytest.mark.parametrize("step_cls", [
        BoardHealthStep, SnapshotStep, SprintCheckStep, SprintSyncStep,
        BoardSyncStep, StandupSyncStep, MergeMRsStep, GitSyncStep,
        CycleLogStep, AlertingStep,
    ])
    def test_all_non_critical(self, step_cls):
        """All listed steps are non-critical."""
        step = step_cls()
        assert step.critical is False
