"""Tests for per-agent pipeline steps: AgentStep, AgentCommitStep, AgentSyncStep, InitStandupStep.

TDD: these tests define the expected behavior before implementation.
"""

import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from opensepia.pipeline import PipelineContext
from opensepia.board_adapter_markdown import MarkdownBoardAdapter


def _create_test_env(tmp_path):
    """Create a full test environment with board, workspace, adapter."""
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()

    (board / "sprint.md").write_text(
        "# Sprint 1\n\n## TODO\n- [ ] STORY-001: Login (dev1)\n\n## DONE\n",
        encoding="utf-8",
    )
    (board / "backlog.md").write_text(
        "# Backlog\n\n## HIGH\n### STORY-001: Login\n**Priority**: HIGH\n**Status**: TODO\n",
        encoding="utf-8",
    )
    (board / "project.md").write_text("# Test\n", encoding="utf-8")
    (board / "standup.md").write_text("", encoding="utf-8")

    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
        (board / "inbox" / f"{agent}.md").write_text("", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()

    # Init git in workspace
    subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(workspace), capture_output=True)
    (workspace / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(workspace), capture_output=True)

    adapter = MarkdownBoardAdapter(board_dir=board, workspace_dir=workspace, project_dir=tmp_path)

    agents_config = {
        "agents": {
            "po": {"name": "Product Owner", "color": "P", "system_prompt": "You are PO."},
            "dev1": {"name": "Developer 1", "color": "D", "system_prompt": "You are Dev1."},
            "tester": {"name": "Tester", "color": "T", "system_prompt": "You are Tester."},
        },
        "global": {"standup_instruction": "Write standup.", "communication_rules": "Use inbox."},
        "execution": {"timeout": 30, "max_retries": 0, "retry_delay": 5, "pause_between_agents": 0},
    }
    project_config = {
        "sprint": {"current_sprint": 1, "current_cycle": 1},
        "project": {"name": "Test"},
    }

    ctx = PipelineContext(
        mode="minimal",
        tool_dir=tmp_path,
        project_dir=tmp_path,
        agents_config=agents_config,
        project_config=project_config,
        board_dir=board,
        workspace_dir=workspace,
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs" / "runs",
        sprint_num=1,
        cycle_num=1,
        agent_ids=["po", "dev1", "tester"],
        execution_params={"timeout": 30, "max_retries": 0, "retry_delay": 5, "pause_between_agents": 0},
        board_adapter=adapter,
    )

    return ctx, adapter, board, workspace


MOCK_AGENT_RESPONSE = """\
## PO Report

---FILES---
path: board/sprint.md
content:
# Sprint 1

## TODO
- [ ] STORY-001: Login (dev1)

## DONE

---
path: board/standup.md
action: append
content:
## PO
- Done: Reviewed sprint
---
path: board/inbox/dev1.md
action: append
content:
## Message from PO
Please start STORY-001.
---END---
"""


# =============================================================================
# InitStandupStep
# =============================================================================

class TestInitStandupStep:
    def test_initializes_standup(self, tmp_path):
        ctx, adapter, board, _ = _create_test_env(tmp_path)
        from opensepia.steps.agent_step import InitStandupStep
        step = InitStandupStep()
        assert step.name == "init_standup"
        step.execute(ctx)
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "Sprint 1" in content
        assert "Cycle 1" in content

    def test_skips_on_dry_run(self, tmp_path):
        ctx, _, board, _ = _create_test_env(tmp_path)
        ctx.dry_run = True
        from opensepia.steps.agent_step import InitStandupStep
        InitStandupStep().execute(ctx)
        # Standup should not be rewritten
        assert (board / "standup.md").read_text(encoding="utf-8") == ""


# =============================================================================
# AgentStep
# =============================================================================

class TestAgentStep:
    def test_has_parameterized_name(self, tmp_path):
        from opensepia.steps.agent_step import AgentStep
        step = AgentStep("dev1")
        assert step.name == "run_agent:dev1"

    def test_is_not_critical(self, tmp_path):
        from opensepia.steps.agent_step import AgentStep
        assert AgentStep("dev1").critical is False

    def test_runs_agent_and_stores_result(self, tmp_path):
        ctx, _, _, _ = _create_test_env(tmp_path)

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = datetime.now().isoformat()
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        from opensepia.steps.agent_step import AgentStep
        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            step = AgentStep("po")
            result_ctx = step.execute(ctx)

        assert len(result_ctx.agent_results) == 1
        assert result_ctx.agent_results[0]["agent_id"] == "po"
        assert result_ctx.current_agent_id == "po"

    def test_writes_files_via_adapter(self, tmp_path):
        ctx, _, board, _ = _create_test_env(tmp_path)

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = datetime.now().isoformat()
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        from opensepia.steps.agent_step import AgentStep
        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            AgentStep("po").execute(ctx)

        # Check inbox was written
        inbox = (board / "inbox" / "dev1.md").read_text(encoding="utf-8")
        assert "STORY-001" in inbox

    def test_handles_agent_error(self, tmp_path):
        ctx, _, _, _ = _create_test_env(tmp_path)

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = "ERROR: timeout"
        mock_result.timestamp = datetime.now().isoformat()
        mock_result.context_size = 5000
        mock_result.response_size = 15
        mock_result.error = "timeout after 30s"

        from opensepia.steps.agent_step import AgentStep
        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            result_ctx = AgentStep("po").execute(ctx)

        assert len(result_ctx.agent_results) == 1
        assert result_ctx.agent_results[0].get("error") is not None


# =============================================================================
# AgentCommitStep
# =============================================================================

class TestAgentCommitStep:
    def test_has_parameterized_name(self):
        from opensepia.steps.agent_step import AgentCommitStep
        assert AgentCommitStep("dev1").name == "commit:dev1"

    def test_commits_workspace_changes(self, tmp_path):
        ctx, _, _, workspace = _create_test_env(tmp_path)

        # Write a file to workspace (simulating agent output)
        (workspace / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        # Check git log for the commit
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        assert "dev1" in result.stdout.lower() or "developer" in result.stdout.lower()

    def test_commit_has_agent_author(self, tmp_path):
        ctx, _, _, workspace = _create_test_env(tmp_path)
        (workspace / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentCommitStep
        AgentCommitStep("dev1").execute(ctx)

        result = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        assert "dev1@opensepia.ai" in result.stdout

    def test_skips_when_no_changes(self, tmp_path):
        ctx, _, _, workspace = _create_test_env(tmp_path)

        from opensepia.steps.agent_step import AgentCommitStep
        # No new files — should not crash
        AgentCommitStep("dev1").execute(ctx)

        result = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        # Should still only have the initial commit
        assert result.stdout.strip().count("\n") == 0


# =============================================================================
# AgentSyncStep
# =============================================================================

class TestAgentSyncStep:
    def test_has_parameterized_name(self):
        from opensepia.steps.agent_step import AgentSyncStep
        assert AgentSyncStep("po").name == "sync:po"

    def test_archives_inbox(self, tmp_path):
        ctx, _, board, _ = _create_test_env(tmp_path)

        # Put something in PO's inbox
        (board / "inbox" / "po.md").write_text("## Message\nHello PO\n", encoding="utf-8")

        from opensepia.steps.agent_step import AgentSyncStep
        AgentSyncStep("po").execute(ctx)

        # Inbox should be cleared
        assert (board / "inbox" / "po.md").read_text(encoding="utf-8").strip() == ""
