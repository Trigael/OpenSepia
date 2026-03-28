"""Tests for opensepia.blockers — blocker extraction, formatting, and registry."""

from pathlib import Path

import pytest

from opensepia.blockers import (
    extract_blockers,
    format_blockers_for_context,
    update_blocker_registry,
)

# ---------------------------------------------------------------------------
# Sample sprint text fixtures
# ---------------------------------------------------------------------------

SPRINT_WITH_BLOCKERS = """\
# Sprint 3

## TODO
- [ ] STORY-010 Build dashboard

## IN PROGRESS
- [ ] STORY-011 Payment integration (dev1)

## BLOCKED
- [ ] STORY-042 OAuth provider down
- [ ] BUG-007 CI pipeline broken

## REVIEW
- [ ] STORY-012 Search feature (dev2)

## DONE
- [x] STORY-009 Setup infra
"""

SPRINT_NO_BLOCKERS = """\
# Sprint 2

## TODO
- [ ] STORY-001 Login page

## IN PROGRESS
- [ ] STORY-002 API layer

## DONE
- [x] STORY-003 Initial setup
"""

SPRINT_EMPTY_BLOCKED = """\
# Sprint 4

## BLOCKED

## TODO
- [ ] STORY-020 Feature X
"""


# ===========================================================================
# extract_blockers
# ===========================================================================

class TestExtractBlockers:
    def test_extracts_blocked_stories(self):
        result = extract_blockers(SPRINT_WITH_BLOCKERS)
        assert len(result) == 2
        assert result[0]["story_id"] == "STORY-042"
        assert result[0]["title"] == "OAuth provider down"
        assert result[1]["story_id"] == "BUG-007"
        assert result[1]["title"] == "CI pipeline broken"

    def test_no_blocked_section(self):
        result = extract_blockers(SPRINT_NO_BLOCKERS)
        assert result == []

    def test_empty_blocked_section(self):
        result = extract_blockers(SPRINT_EMPTY_BLOCKED)
        assert result == []

    def test_empty_input(self):
        result = extract_blockers("")
        assert result == []

    def test_blocked_since_initially_empty(self):
        result = extract_blockers(SPRINT_WITH_BLOCKERS)
        for b in result:
            assert b["blocked_since"] == ""


# ===========================================================================
# format_blockers_for_context
# ===========================================================================

class TestFormatBlockersForContext:
    def test_no_blockers(self):
        text = format_blockers_for_context([], cycle_num=5)
        assert "Active Blockers" in text
        assert "(none)" in text

    def test_format_with_blockers(self):
        blockers = [
            {"story_id": "STORY-042", "title": "OAuth down", "blocked_since": "3"},
        ]
        text = format_blockers_for_context(blockers, cycle_num=5)
        assert "STORY-042" in text
        assert "OAuth down" in text
        assert "blocked 2 cycle(s)" in text

    def test_age_calculation_new_blocker(self):
        blockers = [
            {"story_id": "BUG-001", "title": "Broken", "blocked_since": "10"},
        ]
        text = format_blockers_for_context(blockers, cycle_num=10)
        # Same cycle => age should be at least 1
        assert "blocked 1 cycle(s)" in text

    def test_age_without_blocked_since(self):
        blockers = [
            {"story_id": "STORY-099", "title": "Unknown age", "blocked_since": ""},
        ]
        text = format_blockers_for_context(blockers, cycle_num=7)
        assert "blocked 1 cycle(s)" in text


# ===========================================================================
# update_blocker_registry
# ===========================================================================

class TestUpdateBlockerRegistry:
    def test_creates_registry_file(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        blockers = [
            {"story_id": "STORY-042", "title": "OAuth down", "blocked_since": ""},
        ]
        update_blocker_registry(board_dir, blockers, cycle_num=5)

        registry = board_dir / "blockers.md"
        assert registry.exists()
        content = registry.read_text()
        assert "STORY-042" in content
        assert "since cycle 5" in content

    def test_preserves_blocked_since(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        # First cycle: blocker appears
        blockers = [
            {"story_id": "STORY-042", "title": "OAuth down", "blocked_since": ""},
        ]
        update_blocker_registry(board_dir, blockers, cycle_num=3)

        # Second cycle: same blocker, blocked_since should stay 3
        blockers2 = [
            {"story_id": "STORY-042", "title": "OAuth down", "blocked_since": ""},
        ]
        update_blocker_registry(board_dir, blockers2, cycle_num=5)

        content = (board_dir / "blockers.md").read_text()
        assert "since cycle 3" in content
        assert "age 2" in content

    def test_drops_resolved_blockers(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        # Cycle 3: two blockers
        blockers = [
            {"story_id": "STORY-042", "title": "OAuth down", "blocked_since": ""},
            {"story_id": "BUG-007", "title": "CI broken", "blocked_since": ""},
        ]
        update_blocker_registry(board_dir, blockers, cycle_num=3)

        # Cycle 5: only one remains
        blockers2 = [
            {"story_id": "STORY-042", "title": "OAuth down", "blocked_since": ""},
        ]
        update_blocker_registry(board_dir, blockers2, cycle_num=5)

        content = (board_dir / "blockers.md").read_text()
        assert "STORY-042" in content
        assert "BUG-007" not in content

    def test_empty_blockers_writes_no_blockers(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        update_blocker_registry(board_dir, [], cycle_num=1)

        content = (board_dir / "blockers.md").read_text()
        assert "(no blockers)" in content

    def test_age_tracking_across_cycles(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()

        blocker = [{"story_id": "STORY-100", "title": "DB migration", "blocked_since": ""}]

        update_blocker_registry(board_dir, blocker, cycle_num=2)
        content = (board_dir / "blockers.md").read_text()
        assert "age 1" in content

        update_blocker_registry(board_dir, blocker, cycle_num=5)
        content = (board_dir / "blockers.md").read_text()
        assert "age 3" in content
        assert "since cycle 2" in content
