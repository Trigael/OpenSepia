"""Tests for BoardAdapter — captures current behavior for TDD migration.

These tests run against the MarkdownBoardAdapter to verify it produces
the same results as the current direct file operations. Each test
documents a specific behavior that must be preserved.
"""

import pytest
from pathlib import Path

from opensepia.board_adapter import BoardAdapter, AgentContext
from opensepia.agents.parser import ParsedFile


def _create_test_board(tmp_path) -> Path:
    """Create a minimal board directory matching the current structure."""
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()

    (board / "project.md").write_text(
        "# Test Project\n\n## Description\nA test project.\n",
        encoding="utf-8",
    )

    (board / "sprint.md").write_text(
        "# Sprint 1\n\n## TODO\n- [ ] STORY-001: Login (dev1)\n\n"
        "## IN PROGRESS\n- [ ] STORY-002: API (dev1)\n\n"
        "## REVIEW\n\n## DONE\n- [x] STORY-003: Setup (devops)\n",
        encoding="utf-8",
    )

    (board / "backlog.md").write_text(
        "# Backlog\n\n## HIGH\n### STORY-001: Login\n**Priority**: HIGH\n**Status**: TODO\n\n"
        "### STORY-002: API\n**Priority**: HIGH\n**Status**: IN_PROGRESS\n\n"
        "## MEDIUM\n### STORY-004: Dashboard\n**Priority**: MEDIUM\n**Status**: TODO\n",
        encoding="utf-8",
    )

    (board / "standup.md").write_text(
        "# Standup — Sprint 1, Cycle 3\n\n## Dev1\n- Done: STORY-002\n",
        encoding="utf-8",
    )

    (board / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")

    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
        (board / "inbox" / f"{agent}.md").write_text("", encoding="utf-8")

    (board / "inbox" / "dev1.md").write_text(
        "## Message from PM\nPlease work on STORY-002.\n",
        encoding="utf-8",
    )

    return board


def _create_test_workspace(tmp_path) -> Path:
    """Create a minimal workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    return ws


def _minimal_agents_config() -> dict:
    """Minimal agents.yaml-like config for testing."""
    return {
        "agents": {
            "po": {"name": "Product Owner", "color": "P", "system_prompt": "You are PO."},
            "pm": {"name": "Project Manager", "color": "M", "system_prompt": "You are PM."},
            "dev1": {"name": "Developer 1", "color": "D", "system_prompt": "You are Dev1."},
            "dev2": {"name": "Developer 2", "color": "D", "system_prompt": "You are Dev2."},
            "devops": {"name": "DevOps", "color": "O", "system_prompt": "You are DevOps."},
            "tester": {"name": "Tester", "color": "T", "system_prompt": "You are Tester."},
        },
        "global": {
            "standup_instruction": "Write a standup.",
            "communication_rules": "Use inbox files.",
        },
    }


def _minimal_project_config() -> dict:
    return {
        "sprint": {"current_sprint": 1, "current_cycle": 3},
        "project": {"name": "Test"},
    }


# =============================================================================
# Fixture: MarkdownBoardAdapter with test board
# =============================================================================

@pytest.fixture
def adapter_env(tmp_path):
    """Create a test environment with board, workspace, and adapter."""
    board = _create_test_board(tmp_path)
    workspace = _create_test_workspace(tmp_path)

    from opensepia.board_adapter_markdown import MarkdownBoardAdapter
    adapter = MarkdownBoardAdapter(
        board_dir=board,
        workspace_dir=workspace,
        project_dir=tmp_path,
    )

    return adapter, board, workspace


# =============================================================================
# get_agent_context
# =============================================================================

class TestGetAgentContext:
    """Verify context building produces the same data as direct file reads."""

    def test_returns_agent_context(self, adapter_env):
        adapter, board, ws = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert isinstance(ctx, AgentContext)

    def test_project_description(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "Test Project" in ctx.project_description

    def test_sprint_md(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "Sprint 1" in ctx.sprint_md
        assert "STORY-001" in ctx.sprint_md
        assert "STORY-003" in ctx.sprint_md

    def test_backlog_md(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "Backlog" in ctx.backlog_md
        assert "STORY-004" in ctx.backlog_md

    def test_standup(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "Standup" in ctx.standup

    def test_inbox_for_agent(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "STORY-002" in ctx.inbox

    def test_empty_inbox(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("po", _minimal_agents_config(), _minimal_project_config())
        assert ctx.inbox == "" or ctx.inbox.strip() == ""

    def test_workspace_tree(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "main.py" in ctx.workspace_tree

    def test_sprint_and_cycle_nums(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert ctx.sprint_num == 1
        assert ctx.cycle_num == 3

    def test_backlog_truncated(self, adapter_env):
        """Backlog should be truncated to ~4000 chars."""
        adapter, board, _ = adapter_env
        # Write a huge backlog
        (board / "backlog.md").write_text("# Backlog\n" + "x" * 10000, encoding="utf-8")
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert len(ctx.backlog_md) <= 4100  # Some tolerance

    def test_standup_strips_details(self, adapter_env):
        """Standup should strip nested <details> blocks."""
        adapter, board, _ = adapter_env
        (board / "standup.md").write_text(
            "# Standup\n## Dev1\n- Done: stuff\n"
            "<details><summary>Old</summary>\nold stuff\n</details>\n",
            encoding="utf-8",
        )
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "<details>" not in ctx.standup


# =============================================================================
# apply_agent_output
# =============================================================================

class TestApplyAgentOutput:
    """Verify file writing matches current behavior."""

    def test_write_overwrite(self, adapter_env):
        adapter, board, _ = adapter_env
        files = [ParsedFile(path="board/sprint.md", content="# New Sprint\n", action="overwrite")]
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        assert written == 1
        assert (board / "sprint.md").read_text(encoding="utf-8") == "# New Sprint\n"

    def test_write_append(self, adapter_env):
        adapter, board, _ = adapter_env
        files = [ParsedFile(path="board/standup.md", content="## Dev1\n- Done: more stuff", action="append")]
        adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "more stuff" in content
        assert "Standup — Sprint 1" in content  # Original content preserved

    def test_write_inbox(self, adapter_env):
        adapter, board, _ = adapter_env
        files = [ParsedFile(path="board/inbox/pm.md", content="## Message\nHello PM", action="append")]
        adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        content = (board / "inbox" / "pm.md").read_text(encoding="utf-8")
        assert "Hello PM" in content

    def test_write_workspace(self, adapter_env):
        adapter, _, ws = adapter_env
        files = [ParsedFile(path="workspace/src/new.py", content="print('new')\n", action="overwrite")]
        # Workspace writes use project_dir as base
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        # The file should be written relative to project_dir
        assert written >= 1

    def test_path_traversal_blocked(self, adapter_env):
        adapter, _, _ = adapter_env
        files = [ParsedFile(path="../../etc/passwd", content="hacked", action="overwrite")]
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        assert written == 0

    def test_multiple_files(self, adapter_env):
        adapter, board, _ = adapter_env
        files = [
            ParsedFile(path="board/sprint.md", content="# Sprint\n", action="overwrite"),
            ParsedFile(path="board/standup.md", content="## Entry\n", action="append"),
            ParsedFile(path="board/inbox/pm.md", content="## Msg\n", action="append"),
        ]
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        assert written == 3


# =============================================================================
# Inbox operations
# =============================================================================

class TestInbox:
    def test_get_inbox(self, adapter_env):
        adapter, _, _ = adapter_env
        content = adapter.get_inbox("dev1")
        assert "STORY-002" in content

    def test_get_empty_inbox(self, adapter_env):
        adapter, _, _ = adapter_env
        content = adapter.get_inbox("po")
        assert content.strip() == ""

    def test_archive_inbox(self, adapter_env):
        adapter, board, _ = adapter_env
        adapter.archive_inbox("dev1")
        assert adapter.get_inbox("dev1").strip() == ""
        archives = list((board / "archive" / "dev1").glob("*.md"))
        assert len(archives) == 1

    def test_archive_empty_inbox(self, adapter_env):
        adapter, _, _ = adapter_env
        adapter.archive_inbox("po")  # Should not crash


# =============================================================================
# Standup
# =============================================================================

class TestStandup:
    def test_init_standup(self, adapter_env):
        adapter, board, _ = adapter_env
        adapter.init_standup(1, 4)
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "Sprint 1, Cycle 4" in content

    def test_init_standup_archives_old(self, adapter_env):
        adapter, board, _ = adapter_env
        adapter.init_standup(1, 4)
        archives = list((board / "archive" / "standup").glob("*.md"))
        assert len(archives) == 1

    def test_init_standup_keeps_previous_as_details(self, adapter_env):
        adapter, board, _ = adapter_env
        adapter.init_standup(1, 4)
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "<details>" in content
        assert "Previous cycle" in content


# =============================================================================
# Board readiness
# =============================================================================

class TestBoardReady:
    def test_ensure_board_ready(self, adapter_env):
        adapter, board, _ = adapter_env
        # Remove inbox to test recreation
        import shutil
        shutil.rmtree(board / "inbox")
        adapter.ensure_board_ready()
        assert (board / "inbox").exists()

    def test_ensure_creates_agent_inboxes(self, adapter_env):
        adapter, board, _ = adapter_env
        import shutil
        shutil.rmtree(board / "inbox")
        adapter.ensure_board_ready()
        assert (board / "inbox" / "po.md").exists()
        assert (board / "inbox" / "dev1.md").exists()
