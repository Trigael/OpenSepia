"""Tests for board_adapter_markdown.py — MarkdownBoardAdapter."""

import pytest
from pathlib import Path

from opensepia.board_adapter_markdown import (
    MarkdownBoardAdapter,
    MAX_BACKLOG_CHARS,
    MAX_PROJECT_CHARS,
    MAX_COMMENT_CONTEXT_CHARS,
)
from opensepia.config import MAX_STANDUP_CHARS, MAX_INBOX_CHARS
from opensepia.agents.parser import ParsedFile


# =============================================================================
# Helpers
# =============================================================================

def _make_board(tmp_path) -> Path:
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()
    for a in ["po", "pm", "dev1"]:
        (board / "inbox" / f"{a}.md").write_text("", encoding="utf-8")
    (board / "sprint.md").write_text(
        "# Sprint 1\n\n## TODO\n- [ ] STORY-001: Login (dev1)\n\n"
        "## IN PROGRESS\n- [ ] STORY-002: API (dev1)\n\n"
        "## DONE\n- [x] STORY-003: Setup\n",
        encoding="utf-8",
    )
    (board / "backlog.md").write_text("# Backlog\n\n## HIGH\n### STORY-001\n", encoding="utf-8")
    (board / "project.md").write_text("# Project\nDescription here.\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup — Sprint 1, Cycle 1\n\n## Dev1\n- Working\n", encoding="utf-8")
    return board


def _make_adapter(tmp_path) -> tuple[MarkdownBoardAdapter, Path, Path]:
    board = _make_board(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    adapter = MarkdownBoardAdapter(board_dir=board, workspace_dir=ws, project_dir=tmp_path)
    return adapter, board, ws


@pytest.fixture
def env(tmp_path):
    return _make_adapter(tmp_path)


def _agents_config():
    return {
        "agents": {
            "po": {"name": "PO", "system_prompt": "You are PO."},
            "dev1": {"name": "Dev1", "system_prompt": "You are Dev1."},
        },
        "global": {"standup_instruction": "Write standup.", "communication_rules": "Use inbox."},
    }


def _project_config():
    return {"sprint": {"current_sprint": 1, "current_cycle": 1}}


# =============================================================================
# _read
# =============================================================================

class TestRead:
    def test_reads_existing_file(self, env):
        adapter, board, _ = env
        assert "Sprint 1" in adapter._read(board / "sprint.md")

    def test_returns_empty_for_missing(self, env):
        adapter, board, _ = env
        assert adapter._read(board / "nonexistent.md") == ""


# =============================================================================
# get_agent_context
# =============================================================================

class TestGetAgentContext:
    def test_returns_agent_context(self, env):
        adapter, _, _ = env
        from opensepia.board_adapter import AgentContext
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert isinstance(ctx, AgentContext)

    def test_context_contains_sprint(self, env):
        adapter, _, _ = env
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert "Sprint 1" in ctx.sprint_md

    def test_context_contains_inbox(self, env):
        adapter, board, _ = env
        (board / "inbox" / "dev1.md").write_text("## Message\nHello dev1\n", encoding="utf-8")
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert "Hello dev1" in ctx.inbox

    def test_context_truncates_backlog(self, env):
        adapter, board, _ = env
        (board / "backlog.md").write_text("x" * (MAX_BACKLOG_CHARS + 500), encoding="utf-8")
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert len(ctx.backlog_md) == MAX_BACKLOG_CHARS

    def test_context_truncates_project(self, env):
        adapter, board, _ = env
        (board / "project.md").write_text("x" * (MAX_PROJECT_CHARS + 500), encoding="utf-8")
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert len(ctx.project_description) == MAX_PROJECT_CHARS

    def test_context_strips_details_from_standup(self, env):
        adapter, board, _ = env
        (board / "standup.md").write_text(
            "Current cycle\n<details>old stuff</details>\n", encoding="utf-8"
        )
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert "<details>" not in ctx.standup

    def test_context_sprint_and_cycle_nums(self, env):
        adapter, _, _ = env
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert ctx.sprint_num == 1
        assert ctx.cycle_num == 1


# =============================================================================
# apply_agent_output
# =============================================================================

class TestApplyAgentOutput:
    def test_writes_file(self, env):
        adapter, _, _ = env
        files = [ParsedFile(path="board/test_output.md", content="hello", action="write")]
        count = adapter.apply_agent_output("dev1", files, _agents_config())
        assert count == 1

    def test_append_mode(self, env):
        adapter, board, _ = env
        (board / "test.md").write_text("line1\n", encoding="utf-8")
        files = [ParsedFile(path="board/test.md", content="line2", action="append")]
        adapter.apply_agent_output("dev1", files, _agents_config())
        content = (board / "test.md").read_text(encoding="utf-8")
        assert "line1" in content
        assert "line2" in content

    def test_blocks_path_traversal(self, env, tmp_path):
        adapter, _, _ = env
        files = [ParsedFile(path="../../../etc/passwd", content="bad", action="write")]
        count = adapter.apply_agent_output("dev1", files, _agents_config())
        assert count == 0

    def test_skips_empty_content(self, env):
        adapter, _, _ = env
        files = [ParsedFile(path="board/empty.md", content="", action="write")]
        count = adapter.apply_agent_output("dev1", files, _agents_config())
        assert count == 0


# =============================================================================
# archive_inbox
# =============================================================================

class TestArchiveInbox:
    def test_archives_inbox(self, env):
        adapter, board, _ = env
        (board / "inbox" / "dev1.md").write_text("## Message\nHello\n", encoding="utf-8")
        adapter.archive_inbox("dev1")
        assert (board / "inbox" / "dev1.md").read_text(encoding="utf-8") == ""
        archive_dir = board / "archive" / "dev1"
        assert archive_dir.exists()
        archived = list(archive_dir.glob("*.md"))
        assert len(archived) == 1

    def test_empty_inbox_not_archived(self, env):
        adapter, board, _ = env
        (board / "inbox" / "dev1.md").write_text("", encoding="utf-8")
        adapter.archive_inbox("dev1")
        archive_dir = board / "archive" / "dev1"
        assert not archive_dir.exists() or len(list(archive_dir.glob("*.md"))) == 0


# =============================================================================
# init_standup
# =============================================================================

class TestInitStandup:
    def test_creates_standup_header(self, env):
        adapter, board, _ = env
        adapter.init_standup(2, 1)
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "Sprint 2" in content
        assert "Cycle 1" in content

    def test_archives_old_standup(self, env):
        adapter, board, _ = env
        adapter.init_standup(1, 2)
        archive = board / "archive" / "standup"
        assert archive.exists()
        assert len(list(archive.glob("*.md"))) >= 1


# =============================================================================
# ensure_board_ready
# =============================================================================

class TestEnsureBoardReady:
    def test_creates_dirs(self, tmp_path):
        board = tmp_path / "new_board"
        adapter = MarkdownBoardAdapter(board, tmp_path / "ws", tmp_path)
        adapter.ensure_board_ready()
        assert (board / "inbox").is_dir()
        assert (board / "archive").is_dir()

    def test_creates_inbox_from_config(self, tmp_path):
        board = tmp_path / "new_board"
        adapter = MarkdownBoardAdapter(board, tmp_path / "ws", tmp_path)
        config = {"agents": {"alpha": {}, "beta": {}}}
        adapter.ensure_board_ready(agents_config=config)
        assert (board / "inbox" / "alpha.md").exists()
        assert (board / "inbox" / "beta.md").exists()

    def test_falls_back_to_defaults_without_config(self, tmp_path):
        board = tmp_path / "new_board"
        adapter = MarkdownBoardAdapter(board, tmp_path / "ws", tmp_path)
        adapter.ensure_board_ready()
        assert (board / "inbox" / "po.md").exists()
        assert (board / "inbox" / "dev1.md").exists()

    def test_idempotent(self, tmp_path):
        board = tmp_path / "new_board"
        adapter = MarkdownBoardAdapter(board, tmp_path / "ws", tmp_path)
        adapter.ensure_board_ready()
        adapter.ensure_board_ready()  # Should not crash
        assert (board / "inbox").is_dir()


# =============================================================================
# get_sprint_number
# =============================================================================

class TestGetSprintNumber:
    def test_parses_sprint_number(self, env):
        adapter, _, _ = env
        assert adapter.get_sprint_number() == 1

    def test_defaults_to_1_if_missing(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        adapter = MarkdownBoardAdapter(board, tmp_path, tmp_path)
        assert adapter.get_sprint_number() == 1


# =============================================================================
# get_active_story_ids
# =============================================================================

class TestGetActiveStoryIds:
    def test_returns_active_stories(self, env):
        adapter, _, _ = env
        ids = adapter.get_active_story_ids()
        assert "STORY-001" in ids
        assert "STORY-002" in ids

    def test_excludes_done_stories(self, env):
        adapter, _, _ = env
        ids = adapter.get_active_story_ids()
        assert "STORY-003" not in ids

    def test_empty_sprint(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        adapter = MarkdownBoardAdapter(board, tmp_path, tmp_path)
        assert adapter.get_active_story_ids() == []


# =============================================================================
# get_board_summary
# =============================================================================

class TestGetBoardSummary:
    def test_counts_by_section(self, env):
        adapter, _, _ = env
        summary = adapter.get_board_summary()
        assert summary.get("todo") == 1
        assert summary.get("in_progress") == 1
        assert summary.get("done") == 1


# =============================================================================
# check_board_health
# =============================================================================

class TestCheckBoardHealth:
    def test_healthy_board(self, env):
        adapter, _, _ = env
        health = adapter.check_board_health()
        assert health["sprint.md"] is True
        assert health["backlog.md"] is True

    def test_missing_files(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        adapter = MarkdownBoardAdapter(board, tmp_path, tmp_path)
        health = adapter.check_board_health()
        assert health["sprint.md"] is False


# =============================================================================
# create_snapshot
# =============================================================================

class TestCreateSnapshot:
    def test_snapshots_existing_files(self, env):
        adapter, board, _ = env
        count = adapter.create_snapshot()
        assert count >= 1
        assert (board / ".snapshot" / "sprint.md.bak").exists()

    def test_skips_missing_files(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        adapter = MarkdownBoardAdapter(board, tmp_path, tmp_path)
        count = adapter.create_snapshot()
        assert count == 0


# =============================================================================
# send_inbox_message
# =============================================================================

class TestSendInboxMessage:
    def test_appends_message(self, env):
        adapter, board, _ = env
        adapter.send_inbox_message("dev1", "PM", "Please review STORY-001")
        content = (board / "inbox" / "dev1.md").read_text(encoding="utf-8")
        assert "PM" in content
        assert "STORY-001" in content
