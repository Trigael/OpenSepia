"""Tests for board/merge.py and board/restore.py."""

import re
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opensepia.board.merge import (
    _parse_provider_date,
    _is_our_branch,
    _parse_cycle_number,
    merge_approved_mrs,
    STALE_DAYS,
)
from opensepia.board.restore import (
    check_board_health,
    restore_from_snapshot,
    restore_from_provider,
    CRITICAL_FILES,
    IMPORTANT_FILES,
)


# =============================================================================
# merge.py tests
# =============================================================================


class TestParseProviderDate:
    def test_iso_format_with_z(self):
        dt = _parse_provider_date("2024-01-15T10:30:00Z")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_iso_format_with_offset(self):
        dt = _parse_provider_date("2024-06-20T08:00:00+02:00")
        assert dt.year == 2024
        assert dt.month == 6

    def test_invalid_string_returns_now(self):
        dt = _parse_provider_date("not-a-date")
        # Should return approximately now
        assert (datetime.now(timezone.utc) - dt).total_seconds() < 5

    def test_empty_string_returns_now(self):
        dt = _parse_provider_date("")
        assert (datetime.now(timezone.utc) - dt).total_seconds() < 5


class TestIsOurBranch:
    def test_ai_team_branch(self):
        assert _is_our_branch({"source_branch": "ai-team/sprint-1-cycle-2"})

    def test_non_ai_team_branch(self):
        assert not _is_our_branch({"source_branch": "feature/login"})

    def test_missing_source_branch(self):
        assert not _is_our_branch({})

    def test_empty_source_branch(self):
        assert not _is_our_branch({"source_branch": ""})


class TestParseCycleNumber:
    def test_standard_branch_name(self):
        assert _parse_cycle_number("ai-team/sprint-1-cycle-5") == 5

    def test_story_branch_name(self):
        # rsplit("-", 1)[-1] on "ai-team/story001-s1c3" is "s1c3" which is not int -> 0
        assert _parse_cycle_number("ai-team/story001-s1c3") == 0

    def test_cycle_suffix(self):
        assert _parse_cycle_number("ai-team/sprint-1-cycle-7") == 7

    def test_no_number(self):
        assert _parse_cycle_number("ai-team/main") == 0

    def test_empty(self):
        assert _parse_cycle_number("") == 0


class TestMergeApprovedMrs:
    def _make_client(self):
        client = MagicMock()
        client.enabled = True
        return client

    def test_disabled_provider(self):
        client = MagicMock()
        client.enabled = False
        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 0

    def test_no_open_mrs(self):
        client = self._make_client()
        client.list_mrs.return_value = []
        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 0

    def test_no_ai_team_mrs(self):
        client = self._make_client()
        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "feature/login", "title": "Login"},
        ]
        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 0

    def test_merge_newest_approved(self):
        client = self._make_client()
        now = datetime.now(timezone.utc)
        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "ai-team/sprint-1-cycle-2", "title": "Cycle 2"},
            {"iid": 2, "source_branch": "ai-team/sprint-1-cycle-1", "title": "Cycle 1"},
        ]
        client.get_mr.return_value = {
            "detailed_merge_status": "can_be_merged",
            "created_at": now.isoformat(),
        }
        client.get_mr_approvals.return_value = {"approved": True}
        client.merge_mr.return_value = {"iid": 1}
        client.comment_on_mr.return_value = {}
        client.close_mr.return_value = {"iid": 2}

        merged, closed = merge_approved_mrs(client)
        assert merged == 1
        assert closed == 1  # older MR closed as superseded

    def test_merge_failure(self):
        client = self._make_client()
        now = datetime.now(timezone.utc)
        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "ai-team/sprint-1-cycle-1", "title": "Cycle 1"},
        ]
        client.get_mr.return_value = {
            "detailed_merge_status": "can_be_merged",
            "created_at": now.isoformat(),
        }
        client.get_mr_approvals.return_value = {"approved": True}
        client.merge_mr.return_value = {"error": "conflict"}

        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 0

    def test_close_conflicting_mr(self):
        client = self._make_client()
        now = datetime.now(timezone.utc)
        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "ai-team/sprint-1-cycle-1", "title": "Cycle 1"},
        ]
        client.get_mr.return_value = {
            "detailed_merge_status": "cannot_be_merged",
            "created_at": now.isoformat(),
        }
        client.get_mr_approvals.return_value = {"approved": True}
        client.close_mr.return_value = {"iid": 1}

        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 1

    def test_close_stale_mr(self):
        client = self._make_client()
        old_date = (datetime.now(timezone.utc) - timedelta(days=STALE_DAYS + 1)).isoformat()
        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "ai-team/sprint-1-cycle-1", "title": "Cycle 1"},
        ]
        client.get_mr.return_value = {
            "detailed_merge_status": "checking",
            "created_at": old_date,
        }
        client.get_mr_approvals.return_value = {"approved": False}
        client.close_mr.return_value = {"iid": 1}

        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 1

    def test_skip_young_unapproved_mr(self):
        client = self._make_client()
        now = datetime.now(timezone.utc)
        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "ai-team/sprint-1-cycle-1", "title": "Cycle 1"},
        ]
        client.get_mr.return_value = {
            "detailed_merge_status": "checking",
            "created_at": now.isoformat(),
        }
        client.get_mr_approvals.return_value = {"approved": False}

        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 0

    def test_mr_detail_error(self):
        client = self._make_client()
        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "ai-team/sprint-1-cycle-1", "title": "Cycle 1"},
        ]
        client.get_mr.return_value = {"error": "not found"}

        merged, closed = merge_approved_mrs(client)
        assert merged == 0
        assert closed == 0

    def test_sort_by_cycle_number(self):
        """Newest cycle (higher number) should be merged first."""
        client = self._make_client()
        now = datetime.now(timezone.utc)

        client.list_mrs.return_value = [
            {"iid": 1, "source_branch": "ai-team/sprint-1-cycle-1", "title": "Old"},
            {"iid": 2, "source_branch": "ai-team/sprint-1-cycle-3", "title": "New"},
            {"iid": 3, "source_branch": "ai-team/sprint-1-cycle-2", "title": "Mid"},
        ]

        def get_mr_side_effect(iid):
            return {
                "detailed_merge_status": "can_be_merged",
                "created_at": now.isoformat(),
            }

        client.get_mr.side_effect = get_mr_side_effect
        client.get_mr_approvals.return_value = {"approved": True}
        client.merge_mr.return_value = {"iid": 2}
        client.close_mr.return_value = {}
        client.comment_on_mr.return_value = {}

        merged, closed = merge_approved_mrs(client)
        # iid=2 (cycle-3) merged, iid=1 and iid=3 closed
        assert merged == 1
        assert closed == 2
        # The first merge call should be for iid=2 (newest)
        client.merge_mr.assert_called_once_with(2, squash=False)


# =============================================================================
# restore.py tests
# =============================================================================


class TestCheckBoardHealth:
    def test_all_files_present(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        for f in CRITICAL_FILES + IMPORTANT_FILES:
            (board_dir / f).write_text("content", encoding="utf-8")

        report = check_board_health(board_dir)
        assert report["ok"] is True
        assert len(report["missing"]) == 0
        assert len(report["empty"]) == 0
        assert len(report["present"]) == len(CRITICAL_FILES + IMPORTANT_FILES)

    def test_missing_critical_files(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        # Only create important files
        for f in IMPORTANT_FILES:
            (board_dir / f).write_text("content", encoding="utf-8")

        report = check_board_health(board_dir)
        assert report["ok"] is False
        assert set(report["missing"]) == set(CRITICAL_FILES)

    def test_empty_files(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        for f in CRITICAL_FILES + IMPORTANT_FILES:
            (board_dir / f).write_text("", encoding="utf-8")

        report = check_board_health(board_dir)
        assert report["ok"] is False
        assert len(report["empty"]) == len(CRITICAL_FILES + IMPORTANT_FILES)

    def test_mixed_state(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        # sprint.md present, backlog.md missing, project.md empty
        (board_dir / "sprint.md").write_text("sprint content", encoding="utf-8")
        (board_dir / "project.md").write_text("", encoding="utf-8")

        report = check_board_health(board_dir)
        assert report["ok"] is False
        assert "sprint.md" in report["present"]
        assert "backlog.md" in report["missing"]
        assert "project.md" in report["empty"]


class TestRestoreFromSnapshot:
    def test_no_snapshot_dir(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        assert restore_from_snapshot(board_dir) is False

    def test_empty_snapshot_dir(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        (board_dir / ".snapshot").mkdir()
        assert restore_from_snapshot(board_dir) is False

    def test_restore_missing_files(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        snapshot_dir = board_dir / ".snapshot"
        snapshot_dir.mkdir()

        (snapshot_dir / "sprint.md.bak").write_text("sprint backup", encoding="utf-8")
        (snapshot_dir / "backlog.md.bak").write_text("backlog backup", encoding="utf-8")

        assert restore_from_snapshot(board_dir) is True
        assert (board_dir / "sprint.md").read_text() == "sprint backup"
        assert (board_dir / "backlog.md").read_text() == "backlog backup"

    def test_restore_empty_files(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        snapshot_dir = board_dir / ".snapshot"
        snapshot_dir.mkdir()

        (board_dir / "sprint.md").write_text("", encoding="utf-8")
        (snapshot_dir / "sprint.md.bak").write_text("sprint backup", encoding="utf-8")

        assert restore_from_snapshot(board_dir) is True
        assert (board_dir / "sprint.md").read_text() == "sprint backup"

    def test_skip_existing_nonempty_files(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        snapshot_dir = board_dir / ".snapshot"
        snapshot_dir.mkdir()

        (board_dir / "sprint.md").write_text("existing content", encoding="utf-8")
        (snapshot_dir / "sprint.md.bak").write_text("backup content", encoding="utf-8")

        assert restore_from_snapshot(board_dir) is False
        assert (board_dir / "sprint.md").read_text() == "existing content"


class TestRestoreFromProvider:
    """Tests for restore_from_provider.

    The function does local imports of detect_provider, BOARD_LABELS, and
    PRIORITY_LABELS, so we patch at the module where they originate.
    """

    def _patch_provider(self, mock_provider):
        return patch("opensepia.integrations.providers.detect_provider", return_value=mock_provider)

    def test_no_provider_configured(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        mock_provider = MagicMock()
        mock_provider.enabled = False

        with self._patch_provider(mock_provider):
            result = restore_from_provider(board_dir)
        assert result is False

    def test_no_provider_at_all(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        with self._patch_provider(None):
            result = restore_from_provider(board_dir)
        assert result is False

    def test_no_issues_found(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_provider.name = "GitHub"
        mock_provider.list_issues.return_value = []

        with self._patch_provider(mock_provider):
            result = restore_from_provider(board_dir)
        assert result is False

    def test_no_story_issues(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_provider.name = "GitHub"
        mock_provider.list_issues.side_effect = [
            [{"title": "Random issue", "labels": [], "state": "opened"}],
            [],
        ]

        with self._patch_provider(mock_provider):
            result = restore_from_provider(board_dir)
        assert result is False

    def test_reconstruct_board_from_issues(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_provider.name = "GitHub"
        mock_provider.list_issues.side_effect = [
            [
                {
                    "title": "[STORY-001] Build login page",
                    "labels": ["status::todo", "priority::high"],
                    "state": "opened",
                    "description": "Implement OAuth login",
                },
                {
                    "title": "[BUG-002] Fix crash on startup",
                    "labels": ["status::in-progress", "priority::critical"],
                    "state": "opened",
                    "description": "App crashes on init",
                },
            ],
            [
                {
                    "title": "[STORY-003] Add dashboard",
                    "labels": ["status::done", "priority::medium"],
                    "state": "closed",
                    "description": "Dashboard page",
                },
            ],
        ]

        with self._patch_provider(mock_provider):
            result = restore_from_provider(board_dir)

        assert result is True
        assert (board_dir / "backlog.md").exists()
        assert (board_dir / "sprint.md").exists()
        assert (board_dir / "inbox").is_dir()

        backlog = (board_dir / "backlog.md").read_text()
        assert "STORY-001" in backlog
        assert "BUG-002" in backlog

        sprint = (board_dir / "sprint.md").read_text()
        assert "STORY-001" in sprint
        assert "STORY-003" in sprint  # done section

    def test_does_not_overwrite_existing_board_files(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        (board_dir / "sprint.md").write_text("existing sprint", encoding="utf-8")
        (board_dir / "backlog.md").write_text("existing backlog", encoding="utf-8")

        mock_provider = MagicMock()
        mock_provider.enabled = True
        mock_provider.name = "GitHub"
        mock_provider.list_issues.side_effect = [
            [{"title": "[STORY-001] Test", "labels": [], "state": "opened", "description": ""}],
            [],
        ]

        with self._patch_provider(mock_provider):
            result = restore_from_provider(board_dir)

        assert result is True  # Returns True (provider had stories), but files unchanged
        assert (board_dir / "sprint.md").read_text() == "existing sprint"
        assert (board_dir / "backlog.md").read_text() == "existing backlog"

    def test_import_error(self, tmp_path):
        """If integrations can't be imported, should return False."""
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        with patch.dict("sys.modules", {"opensepia.integrations.providers": None}):
            # Force an ImportError by patching the import
            result = restore_from_provider(board_dir)
        assert result is False
