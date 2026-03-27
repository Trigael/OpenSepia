"""Tests for agent modules: workspace, context, writer."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opensepia.agents.workspace import (
    get_workspace_tree,
    MAX_WORKSPACE_FILES_PER_DIR,
    MAX_WORKSPACE_SUBDIRS,
    SKIP_DIRS,
)
from opensepia.agents.context import build_agent_context_from_adapter
from opensepia.agents.writer import (
    read_file_safe,
    write_file,
    archive_inbox,
    _handle_standup_fallback,
    _handle_provider_comments,
)
from opensepia.agents.parser import ParsedFile
from opensepia.board_adapter import AgentContext


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_agents_config(agent_id="dev1", agent_name="Developer 1", color="🔨"):
    """Return a minimal agents_config dict."""
    return {
        "global": {
            "communication_rules": "Be concise.",
            "standup_instruction": "Write a standup update.",
        },
        "agents": {
            agent_id: {
                "name": agent_name,
                "color": color,
                "system_prompt": "You are a developer agent.",
            },
            "po": {
                "name": "Product Owner",
                "color": "📋",
                "system_prompt": "You are the PO.",
            },
        },
    }


def _make_agent_context(**overrides):
    """Return an AgentContext with sensible defaults."""
    defaults = dict(
        project_description="Test project",
        sprint_md="# Sprint 1\n- STORY-001 TODO",
        backlog_md="# Backlog\n- STORY-002",
        standup="## dev1\nDid stuff",
        inbox="## Message from PO\nPlease fix bug",
        workspace_tree="src/\n  main.py",
        provider_comments="",
        sprint_num=1,
        cycle_num=3,
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


# ===========================================================================
# workspace.py — get_workspace_tree
# ===========================================================================


class TestGetWorkspaceTree:

    def test_empty_directory(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        assert get_workspace_tree(ws) == "(workspace is empty)"

    def test_nonexistent_directory(self, tmp_path):
        ws = tmp_path / "nope"
        assert get_workspace_tree(ws) == "(workspace is empty)"

    def test_single_file(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "README.md").write_text("hi")
        result = get_workspace_tree(ws)
        assert "README.md" in result

    def test_nested_dirs(self, tmp_path):
        ws = tmp_path / "workspace"
        (ws / "src" / "lib").mkdir(parents=True)
        (ws / "src" / "lib" / "util.py").write_text("")
        (ws / "src" / "main.py").write_text("")
        result = get_workspace_tree(ws, max_depth=3)
        assert "src/" in result
        assert "main.py" in result
        assert "lib/" in result
        assert "util.py" in result

    def test_max_depth_truncation(self, tmp_path):
        ws = tmp_path / "workspace"
        deep = ws / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "secret.txt").write_text("")
        # depth 0 = ws, depth 1 = a, depth 2 = b, depth 3 would be c — blocked at max_depth=2
        result = get_workspace_tree(ws, max_depth=2)
        assert "a/" in result
        assert "b/" in result
        # c/ is at depth 3, should not appear
        assert "secret.txt" not in result

    def test_skip_dirs(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        for skip in SKIP_DIRS:
            d = ws / skip
            d.mkdir()
            (d / "junk.txt").write_text("x")
        (ws / "keep.py").write_text("x")
        result = get_workspace_tree(ws)
        assert "keep.py" in result
        for skip in SKIP_DIRS:
            assert skip not in result

    def test_hidden_files_excluded(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".hidden").write_text("x")
        (ws / "visible.py").write_text("x")
        result = get_workspace_tree(ws)
        assert ".hidden" not in result
        assert "visible.py" in result

    def test_file_count_limit(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        count = MAX_WORKSPACE_FILES_PER_DIR + 5
        for i in range(count):
            (ws / f"file_{i:03d}.txt").write_text("")
        result = get_workspace_tree(ws)
        assert f"... and {count - MAX_WORKSPACE_FILES_PER_DIR} more" in result

    def test_subdir_count_limit(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        for i in range(MAX_WORKSPACE_SUBDIRS + 3):
            (ws / f"dir_{i:02d}").mkdir()
        result = get_workspace_tree(ws)
        # Only MAX_WORKSPACE_SUBDIRS directories should appear
        listed_dirs = [line for line in result.splitlines() if line.endswith("/")]
        assert len(listed_dirs) == MAX_WORKSPACE_SUBDIRS

    def test_permission_error_skipped(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "ok.txt").write_text("hi")
        bad = ws / "noperm"
        bad.mkdir()
        bad.chmod(0o000)
        try:
            result = get_workspace_tree(ws)
            # Should not crash; ok.txt still appears
            assert "ok.txt" in result
        finally:
            bad.chmod(0o755)


# ===========================================================================
# context.py — build_agent_context_from_adapter
# ===========================================================================


class TestBuildAgentContext:

    def test_all_sections_present(self):
        cfg = _make_agents_config()
        ac = _make_agent_context()
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)

        assert "You are a developer agent." in prompt
        assert "Sprint: 1" in prompt
        assert "Cycle: 3" in prompt
        assert "Test project" in prompt
        assert "# Sprint 1" in prompt
        assert "# Backlog" in prompt
        assert "## dev1" in prompt
        assert "Message from PO" in prompt
        assert "src/" in prompt
        assert "Be concise." in prompt
        assert "Write a standup update." in prompt
        assert "---FILES---" in prompt
        # Inbox file list should include both agent ids
        assert "dev1.md" in prompt
        assert "po.md" in prompt

    def test_empty_project_description(self):
        cfg = _make_agents_config()
        ac = _make_agent_context(project_description="")
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)
        assert "(empty)" in prompt

    def test_empty_sprint(self):
        cfg = _make_agents_config()
        ac = _make_agent_context(sprint_md="")
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)
        assert "(none)" in prompt

    def test_empty_backlog(self):
        cfg = _make_agents_config()
        ac = _make_agent_context(backlog_md="")
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)
        assert "## Backlog (truncated)\n(empty)" in prompt

    def test_empty_standup(self):
        cfg = _make_agents_config()
        ac = _make_agent_context(standup="   ")
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)
        assert "(empty so far)" in prompt

    def test_empty_inbox(self):
        cfg = _make_agents_config()
        ac = _make_agent_context(inbox="")
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)
        assert "(no messages)" in prompt

    def test_no_communication_rules(self):
        cfg = _make_agents_config()
        cfg["global"]["communication_rules"] = ""
        ac = _make_agent_context()
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)
        # Should still build without error
        assert "---FILES---" in prompt

    def test_provider_comments_included(self):
        cfg = _make_agents_config()
        ac = _make_agent_context(provider_comments="\n## MR Comments\nLGTM")
        prompt = build_agent_context_from_adapter("dev1", cfg, ac)
        assert "LGTM" in prompt


# ===========================================================================
# writer.py — read_file_safe
# ===========================================================================


class TestReadFileSafe:

    def test_existing_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_file_safe(f) == "hello world"

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nope.txt"
        assert read_file_safe(f) == ""

    def test_read_error(self, tmp_path):
        f = tmp_path / "bad.txt"
        f.write_text("data")
        f.chmod(0o000)
        try:
            result = read_file_safe(f)
            assert result.startswith("[READ ERROR:")
        finally:
            f.chmod(0o644)


# ===========================================================================
# writer.py — write_file
# ===========================================================================


class TestWriteFile:

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        write_file(target, "content")
        assert target.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("old")
        write_file(f, "new")
        assert f.read_text(encoding="utf-8") == "new"


# ===========================================================================
# writer.py — archive_inbox
# ===========================================================================


class TestArchiveInbox:

    def test_creates_timestamped_file(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        archive_inbox("dev1", "## Message\nHello", board_dir)
        archive_dir = board_dir / "archive" / "dev1"
        assert archive_dir.exists()
        files = list(archive_dir.iterdir())
        assert len(files) == 1
        assert files[0].suffix == ".md"
        assert files[0].read_text(encoding="utf-8") == "## Message\nHello"
        # filename should be a timestamp pattern YYYYMMDD_HHMMSS.md
        assert len(files[0].stem) == 15  # e.g. 20260327_143012

    def test_empty_content_skipped(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        archive_inbox("dev1", "   ", board_dir)
        assert not (board_dir / "archive").exists()

    def test_multiple_archives(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        archive_inbox("dev1", "msg1", board_dir)
        archive_inbox("dev1", "msg2", board_dir)
        files = list((board_dir / "archive" / "dev1").iterdir())
        # Could be 1 or 2 depending on timing — at least 1
        assert len(files) >= 1


# ===========================================================================
# writer.py — _handle_standup_fallback
# ===========================================================================


class TestHandleStandupFallback:

    def test_no_fallback_when_standup_in_files(self, tmp_path):
        standup_file = tmp_path / "standup.md"
        standup_file.write_text("existing")
        parsed = [ParsedFile(path="board/standup.md", content="update", action="overwrite")]
        cfg = _make_agents_config()
        result = {"response": "---STANDUP---\nDid work\n---"}
        _handle_standup_fallback("dev1", result, parsed, cfg, standup_file)
        # File should be unchanged because standup was already in parsed files
        assert standup_file.read_text() == "existing"

    def test_fallback_writes_when_standup_not_in_files(self, tmp_path):
        standup_file = tmp_path / "standup.md"
        standup_file.write_text("# Standup\n")
        parsed = [ParsedFile(path="board/sprint.md", content="sprint", action="overwrite")]
        cfg = _make_agents_config()
        result = {"response": "blah blah\n---STANDUP---\nI fixed the bug\n---\nmore text"}
        _handle_standup_fallback("dev1", result, parsed, cfg, standup_file)
        content = standup_file.read_text()
        assert "I fixed the bug" in content
        assert "Developer 1" in content

    def test_fallback_no_standup_section_in_response(self, tmp_path):
        standup_file = tmp_path / "standup.md"
        standup_file.write_text("original")
        parsed = []
        cfg = _make_agents_config()
        result = {"response": "Just some regular output with no standup section."}
        _handle_standup_fallback("dev1", result, parsed, cfg, standup_file)
        assert standup_file.read_text() == "original"

    def test_fallback_empty_files_list(self, tmp_path):
        standup_file = tmp_path / "standup.md"
        parsed = []
        cfg = _make_agents_config()
        result = {"response": "---STANDUP---\nDone tasks\n---"}
        _handle_standup_fallback("dev1", result, parsed, cfg, standup_file)
        content = standup_file.read_text()
        assert "Done tasks" in content


# ===========================================================================
# writer.py — _handle_provider_comments
# ===========================================================================


class TestHandleProviderComments:

    @patch("opensepia.agents.writer.detect_provider", create=True)
    @patch("opensepia.agents.writer.post_agent_messages_to_provider", create=True)
    @patch("opensepia.agents.writer.reset_mr_cache", create=True)
    def test_posts_comments_when_provider_enabled(self, mock_reset, mock_post, mock_detect):
        """Provider comments are posted when a provider is enabled."""
        # We need to patch at the import location inside the function
        provider = MagicMock()
        provider.enabled = True

        with patch("opensepia.integrations.providers.detect_provider", return_value=provider), \
             patch("opensepia.board.comments.post_agent_messages_to_provider") as mock_post_inner, \
             patch("opensepia.board.comments.reset_mr_cache") as mock_reset_inner:

            parsed = [ParsedFile(path="board/inbox/dev1.md", content="msg", action="append")]
            _handle_provider_comments("po", parsed)

            mock_reset_inner.assert_called_once()
            mock_post_inner.assert_called_once()
            args = mock_post_inner.call_args
            assert args[0][0] == "po"
            assert args[0][1] == [{"path": "board/inbox/dev1.md", "content": "msg", "action": "append"}]
            assert args[0][2] is provider

    def test_no_crash_when_provider_not_available(self):
        """Should not raise even if imports fail."""
        with patch.dict("sys.modules", {"opensepia.integrations.providers": None}):
            # The function catches all exceptions, so it should not raise
            parsed = [ParsedFile(path="board/sprint.md", content="x", action="overwrite")]
            _handle_provider_comments("dev1", parsed)

    def test_provider_disabled(self):
        """No comments posted when provider is disabled."""
        provider = MagicMock()
        provider.enabled = False

        with patch("opensepia.integrations.providers.detect_provider", return_value=provider), \
             patch("opensepia.board.comments.post_agent_messages_to_provider") as mock_post, \
             patch("opensepia.board.comments.reset_mr_cache"):

            parsed = [ParsedFile(path="board/sprint.md", content="x", action="overwrite")]
            _handle_provider_comments("dev1", parsed)
            mock_post.assert_not_called()

    def test_provider_none(self):
        """No comments posted when no provider detected."""
        with patch("opensepia.integrations.providers.detect_provider", return_value=None), \
             patch("opensepia.board.comments.reset_mr_cache"):

            parsed = [ParsedFile(path="board/sprint.md", content="x", action="overwrite")]
            _handle_provider_comments("dev1", parsed)
            # Should complete without error
