"""Tests for per-story git branches in AgentCommitStep and AgentSyncStep."""

import subprocess
import re
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from opensepia.pipeline import PipelineContext
from opensepia.board_adapter_markdown import MarkdownBoardAdapter


def _create_git_env(tmp_path):
    """Create test env with git-initialized workspace."""
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()
    (board / "sprint.md").write_text("# Sprint 1\n\n## TODO\n- [ ] STORY-001: Login\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("# Test\n", encoding="utf-8")
    (board / "standup.md").write_text("", encoding="utf-8")
    for a in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
        (board / "inbox" / f"{a}.md").write_text("", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()

    subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(workspace), capture_output=True)
    (workspace / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(workspace), capture_output=True)

    adapter = MarkdownBoardAdapter(board_dir=board, workspace_dir=workspace, project_dir=tmp_path)

    agents_config = {
        "agents": {
            "dev1": {"name": "Developer 1", "color": "D", "system_prompt": "Dev1."},
            "dev2": {"name": "Developer 2", "color": "D", "system_prompt": "Dev2."},
        },
        "global": {},
        "execution": {"timeout": 30, "max_retries": 0, "retry_delay": 5, "pause_between_agents": 0},
    }

    ctx = PipelineContext(
        mode="minimal",
        tool_dir=tmp_path,
        project_dir=tmp_path,
        agents_config=agents_config,
        project_config={"sprint": {"current_sprint": 1, "current_cycle": 1}, "project": {"name": "Test"}},
        board_dir=board,
        workspace_dir=workspace,
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs" / "runs",
        sprint_num=1,
        cycle_num=1,
        agent_ids=["dev1", "dev2"],
        board_adapter=adapter,
    )

    return ctx, workspace, board


def _git(workspace, *args):
    """Run git command in workspace."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True,
        cwd=str(workspace), timeout=10,
    )


def _branches(workspace):
    """Get list of branch names."""
    result = _git(workspace, "branch", "--list")
    return [b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()]


# =============================================================================
# AgentCommitStep — story branch creation
# =============================================================================

class TestStoryBranchCreation:
    def test_creates_story_branch(self, tmp_path):
        ctx, ws, _ = _create_git_env(tmp_path)
        ctx.current_agent_id = "dev1"
        ctx.current_agent_result = {
            "agent_id": "dev1",
            "response": "Implemented STORY-001: login page\n---FILES---\npath: workspace/src/login.py\ncontent:\nprint('login')\n---END---",
        }
        (ws / "src" / "login.py").write_text("print('login')\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        branches = _branches(ws)
        assert "story/story-001" in branches or any("story-001" in b for b in branches)

    def test_commits_on_story_branch(self, tmp_path):
        ctx, ws, _ = _create_git_env(tmp_path)
        ctx.current_agent_id = "dev1"
        ctx.current_agent_result = {
            "agent_id": "dev1",
            "response": "Working on STORY-001",
        }
        (ws / "src" / "login.py").write_text("print('login')\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        # Check commit is on story branch
        result = _git(ws, "log", "story/story-001", "--oneline", "-1")
        assert "dev1" in result.stdout.lower() or "story" in result.stdout.lower()

    def test_returns_to_master_after_commit(self, tmp_path):
        ctx, ws, _ = _create_git_env(tmp_path)
        ctx.current_agent_id = "dev1"
        ctx.current_agent_result = {"agent_id": "dev1", "response": "STORY-001 done"}
        (ws / "src" / "login.py").write_text("code\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        result = _git(ws, "branch", "--show-current")
        assert result.stdout.strip() == "master"

    def test_multiple_agents_same_story(self, tmp_path):
        ctx, ws, _ = _create_git_env(tmp_path)

        # Dev1 works on STORY-001
        ctx.current_agent_id = "dev1"
        ctx.current_agent_result = {"agent_id": "dev1", "response": "STORY-001 backend"}
        (ws / "src" / "backend.py").write_text("backend\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        # Dev2 also works on STORY-001
        ctx.current_agent_id = "dev2"
        ctx.current_agent_result = {"agent_id": "dev2", "response": "STORY-001 frontend"}
        (ws / "src").mkdir(exist_ok=True)
        (ws / "src" / "frontend.py").write_text("frontend\n", encoding="utf-8")
        AgentCommitStep("dev2").execute(ctx)

        # Both commits on same branch
        result = _git(ws, "log", "story/story-001", "--oneline")
        assert result.stdout.strip().count("\n") >= 1  # At least 2 commits

    def test_fallback_to_master_no_story(self, tmp_path):
        ctx, ws, _ = _create_git_env(tmp_path)
        ctx.current_agent_id = "dev1"
        ctx.current_agent_result = {"agent_id": "dev1", "response": "General cleanup"}
        (ws / "src" / "utils.py").write_text("utils\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        result = _git(ws, "log", "master", "--oneline", "-1")
        assert "dev1" in result.stdout.lower()

    def test_no_changes_no_branch(self, tmp_path):
        ctx, ws, _ = _create_git_env(tmp_path)
        ctx.current_agent_id = "dev1"
        ctx.current_agent_result = {"agent_id": "dev1", "response": "STORY-001 reviewed"}

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        branches = _branches(ws)
        # No story branch created since no files changed
        assert "story/story-001" not in branches


# =============================================================================
# AgentSyncStep — merge on DONE
# =============================================================================

class TestStoryBranchMerge:
    def test_merge_on_done(self, tmp_path):
        ctx, ws, board = _create_git_env(tmp_path)

        # Create story branch with a commit
        ctx.current_agent_id = "dev1"
        ctx.current_agent_result = {"agent_id": "dev1", "response": "STORY-001 done"}
        (ws / "src" / "login.py").write_text("done\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep, AgentSyncStep
        AgentCommitStep("dev1").execute(ctx)

        # Mark story as done in sprint
        (board / "sprint.md").write_text(
            "# Sprint 1\n\n## DONE\n- [x] STORY-001: Login\n",
            encoding="utf-8",
        )

        AgentSyncStep("dev1").execute(ctx)

        # Story branch should be merged to master
        result = _git(ws, "log", "master", "--oneline")
        assert "login" in result.stdout.lower() or "story-001" in result.stdout.lower() or "merge" in result.stdout.lower()
