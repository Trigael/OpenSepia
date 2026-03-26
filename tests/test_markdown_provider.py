"""Tests for MarkdownProvider — board operations via local markdown files."""

import pytest
from pathlib import Path

from opensepia.integrations.providers.markdown import MarkdownProvider
from opensepia.integrations.base import BOARD_LABELS, PRIORITY_LABELS


@pytest.fixture
def provider(tmp_path):
    """Create a MarkdownProvider with a fresh board directory."""
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()

    # Seed sprint.md
    (board / "sprint.md").write_text("""\
# Sprint 1

## TODO
- [ ] STORY-001: User login (dev1)
- [ ] STORY-002: Dashboard (dev2)

## IN PROGRESS

## REVIEW
- [ ] STORY-003: API scaffold (dev1)

## DONE
- [x] STORY-004: Define MVP (po)
""", encoding="utf-8")

    # Seed backlog.md
    (board / "backlog.md").write_text("""\
# Backlog

## HIGH
### STORY-001: User login
**Priority**: HIGH
**Status**: TODO
**Assigned**: dev1

### STORY-003: API scaffold
**Priority**: HIGH
**Status**: REVIEW

## MEDIUM
### STORY-002: Dashboard
**Priority**: MEDIUM
**Status**: TODO
**Assigned**: dev2

## DONE
### STORY-004: Define MVP
**Priority**: HIGH
**Status**: DONE
""", encoding="utf-8")

    # Seed project.md
    (board / "project.md").write_text("# My Project\nA test project.\n", encoding="utf-8")

    # Seed standup
    (board / "standup.md").write_text("# Standup\n## Dev1\n- Done: stuff\n", encoding="utf-8")

    # Create inboxes
    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
        (board / "inbox" / f"{agent}.md").write_text("", encoding="utf-8")

    return MarkdownProvider(board_dir=board)


# =============================================================================
# Basics
# =============================================================================

class TestBasics:
    def test_name(self, provider):
        assert provider.name == "markdown"

    def test_enabled(self, provider):
        assert provider.enabled is True

    def test_disabled_when_no_dir(self, tmp_path):
        p = MarkdownProvider(board_dir=tmp_path / "nonexistent")
        assert p.enabled is False

    def test_init_creates_dirs(self, tmp_path):
        board = tmp_path / "new_board"
        p = MarkdownProvider(board_dir=board)
        p.init()
        assert board.exists()
        assert (board / "inbox").exists()
        assert (board / "archive").exists()


# =============================================================================
# List issues
# =============================================================================

class TestListIssues:
    def test_list_all(self, provider):
        items = provider.list_issues(state="opened")
        # STORY-001, 002, 003 are open; 004 is done
        ids = [i["id"] for i in items]
        assert "STORY-001" in ids
        assert "STORY-002" in ids
        assert "STORY-003" in ids
        assert "STORY-004" not in ids

    def test_list_closed(self, provider):
        items = provider.list_issues(state="closed")
        ids = [i["id"] for i in items]
        assert "STORY-004" in ids
        assert "STORY-001" not in ids

    def test_list_has_labels(self, provider):
        items = provider.list_issues()
        for item in items:
            assert "labels" in item
            assert "iid" in item
            assert "state" in item

    def test_list_has_status(self, provider):
        items = provider.list_issues()
        statuses = {i["id"]: i["status"] for i in items}
        assert statuses["STORY-001"] == "todo"
        # STORY-003 has REVIEW in sprint.md
        assert statuses["STORY-003"] == "review"


# =============================================================================
# Find issue
# =============================================================================

class TestFindIssue:
    def test_find_existing(self, provider):
        found = provider.find_issue_by_id("STORY-001")
        assert found == "STORY-001"

    def test_find_not_found(self, provider):
        found = provider.find_issue_by_id("STORY-999")
        assert found is None

    def test_find_caches(self, provider):
        provider.find_issue_by_id("STORY-001")
        assert "STORY-001" in provider._issue_cache


# =============================================================================
# Create issue
# =============================================================================

class TestCreateIssue:
    def test_create_story(self, provider):
        result = provider.create_issue(
            "New feature",
            "Build something cool",
            labels=["status::todo", "priority::high"],
        )
        assert "error" not in result
        assert result["id"].startswith("STORY-")
        assert result["status"] == "todo"

        # Should be in backlog
        backlog = provider._read("backlog.md")
        assert "New feature" in backlog

    def test_create_with_explicit_id(self, provider):
        result = provider.create_issue(
            "[STORY-050] Explicit ID",
            "Description",
        )
        assert result["id"] == "STORY-050"

    def test_create_bug(self, provider):
        result = provider.create_issue(
            "Login crash",
            "App crashes",
            labels=["type::bug", "priority::critical"],
        )
        assert result["id"].startswith("BUG-") or "bug" in result.get("title", "").lower()

    def test_sequential_ids(self, provider):
        r1 = provider.create_issue("First", "D")
        r2 = provider.create_issue("Second", "D")
        # Should be STORY-005 and STORY-006 (004 already exists)
        num1 = int(r1["id"].split("-")[1])
        num2 = int(r2["id"].split("-")[1])
        assert num2 == num1 + 1


# =============================================================================
# Update status
# =============================================================================

class TestUpdateStatus:
    def test_close_issue(self, provider):
        provider.close_issue("STORY-001")
        items = provider.list_issues(state="closed")
        ids = [i["id"] for i in items]
        assert "STORY-001" in ids

    def test_reopen_issue(self, provider):
        provider.reopen_issue("STORY-004")
        items = provider.list_issues(state="opened")
        ids = [i["id"] for i in items]
        assert "STORY-004" in ids

    def test_update_labels(self, provider):
        provider.update_issue_labels("STORY-001", ["status::in-progress"])
        items = provider.list_issues()
        s1 = next(i for i in items if i["id"] == "STORY-001")
        assert s1["status"] == "in_progress"


# =============================================================================
# Board view
# =============================================================================

class TestBoard:
    def test_get_board_state(self, provider):
        board = provider.get_board_state()
        assert isinstance(board, dict)
        assert "todo" in board or "review" in board

    def test_get_board_summary_md(self, provider):
        md = provider.get_board_summary_md()
        assert "Sprint 1" in md
        assert "STORY-001" in md


# =============================================================================
# Inbox
# =============================================================================

class TestInbox:
    def test_get_empty_inbox(self, provider):
        content = provider.get_inbox("dev1")
        assert content == ""

    def test_send_and_get_inbox(self, provider):
        provider.send_inbox("dev1", "pm", "## Task\nImplement STORY-001")
        content = provider.get_inbox("dev1")
        assert "STORY-001" in content

    def test_archive_inbox(self, provider):
        provider.send_inbox("dev1", "pm", "Message")
        provider.archive_inbox("dev1")
        assert provider.get_inbox("dev1") == ""
        # Check archive exists
        archives = list((provider.board_dir / "archive" / "dev1").glob("*.md"))
        assert len(archives) == 1

    def test_archive_empty_inbox(self, provider):
        # Should not crash
        provider.archive_inbox("dev1")


# =============================================================================
# Extra methods
# =============================================================================

class TestExtras:
    def test_get_standup(self, provider):
        standup = provider.get_standup()
        assert "Standup" in standup

    def test_get_project_description(self, provider):
        desc = provider.get_project_description()
        assert "My Project" in desc

    def test_search_issues(self, provider):
        results = provider.search_issues("login")
        assert len(results) == 1
        assert "STORY-001" in results[0]["id"]

    def test_search_no_results(self, provider):
        results = provider.search_issues("nonexistent")
        assert results == []


# =============================================================================
# MR no-ops
# =============================================================================

class TestMRNoOps:
    def test_list_mrs_empty(self, provider):
        assert provider.list_mrs() == []

    def test_create_mr_not_supported(self, provider):
        result = provider.create_mr("branch", "main", "title")
        assert "error" in result

    def test_comments_on_issue_noop(self, provider):
        result = provider.comment_on_issue("STORY-001", "dev1", "Nice!")
        assert "error" not in result
        # But there are no per-issue comments in markdown
        assert provider.get_issue_comments("STORY-001") == []
