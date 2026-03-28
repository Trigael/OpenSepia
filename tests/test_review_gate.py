"""Tests for opensepia/review_gate.py and the review gate in MarkdownBoardAdapter."""

import pytest
from pathlib import Path

from opensepia.review_gate import (
    check_review_evidence,
    get_reviewer_for_story,
    APPROVAL_KEYWORDS,
    REJECTION_KEYWORDS,
)
from opensepia.board_adapter_markdown import MarkdownBoardAdapter
from opensepia.agents.parser import ParsedFile


# =============================================================================
# Helpers
# =============================================================================

def _make_board(tmp_path: Path) -> Path:
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()
    for a in ["dev1", "dev2", "po", "pm"]:
        (board / "inbox" / f"{a}.md").write_text("", encoding="utf-8")
    return board


def _make_adapter(tmp_path: Path) -> tuple[MarkdownBoardAdapter, Path]:
    board = _make_board(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    adapter = MarkdownBoardAdapter(board_dir=board, workspace_dir=ws, project_dir=tmp_path)
    return adapter, board


OLD_SPRINT = (
    "# Sprint 1\n\n"
    "## TODO\n- [ ] STORY-010: Backlog item (dev1)\n\n"
    "## IN PROGRESS\n- [ ] STORY-020: Active work (dev2)\n\n"
    "## REVIEW\n- [ ] STORY-001: Login page (dev1)\n\n"
    "## DONE\n- [x] STORY-099: Setup\n"
)

NEW_SPRINT_PROMOTED = (
    "# Sprint 1\n\n"
    "## TODO\n- [ ] STORY-010: Backlog item (dev1)\n\n"
    "## IN PROGRESS\n- [ ] STORY-020: Active work (dev2)\n\n"
    "## REVIEW\n\n"
    "## DONE\n- [x] STORY-001: Login page (dev1)\n- [x] STORY-099: Setup\n"
)

NEW_SPRINT_NO_CHANGE = (
    "# Sprint 1\n\n"
    "## TODO\n- [ ] STORY-010: Backlog item (dev1)\n\n"
    "## IN PROGRESS\n- [ ] STORY-020: Active work (dev2)\n\n"
    "## REVIEW\n- [ ] STORY-001: Login page (dev1)\n\n"
    "## DONE\n- [x] STORY-099: Setup\n"
)


# =============================================================================
# check_review_evidence
# =============================================================================

class TestCheckReviewEvidence:
    def test_approval_in_archive(self, tmp_path):
        board = _make_board(tmp_path)
        archive = board / "archive" / "dev2"
        archive.mkdir(parents=True)
        (archive / "20260101_120000.md").write_text(
            "Reviewed STORY-001. LGTM, looks good.\n", encoding="utf-8"
        )
        has_review, reviewer = check_review_evidence("STORY-001", board)
        assert has_review is True
        assert reviewer == "dev2"

    def test_approval_in_standup(self, tmp_path):
        board = _make_board(tmp_path)
        (board / "standup.md").write_text(
            "## Dev2\n- Reviewed STORY-001: approved\n", encoding="utf-8"
        )
        has_review, reviewer = check_review_evidence("STORY-001", board)
        assert has_review is True

    def test_no_evidence(self, tmp_path):
        board = _make_board(tmp_path)
        (board / "standup.md").write_text("## Dev1\n- Working on stuff\n", encoding="utf-8")
        has_review, reason = check_review_evidence("STORY-001", board)
        assert has_review is False
        assert "no review evidence" in reason

    def test_rejection_keywords_block(self, tmp_path):
        board = _make_board(tmp_path)
        archive = board / "archive" / "dev2"
        archive.mkdir(parents=True)
        (archive / "20260101_120000.md").write_text(
            "Reviewed STORY-001. Needs changes in auth module.\n", encoding="utf-8"
        )
        has_review, reason = check_review_evidence("STORY-001", board)
        assert has_review is False
        assert "rejection" in reason

    def test_case_insensitive_story_id(self, tmp_path):
        board = _make_board(tmp_path)
        archive = board / "archive" / "dev2"
        archive.mkdir(parents=True)
        (archive / "20260101_120000.md").write_text(
            "Reviewed story-001. Approved.\n", encoding="utf-8"
        )
        has_review, _ = check_review_evidence("STORY-001", board)
        assert has_review is True

    def test_unrelated_story_not_matched(self, tmp_path):
        board = _make_board(tmp_path)
        archive = board / "archive" / "dev2"
        archive.mkdir(parents=True)
        (archive / "20260101_120000.md").write_text(
            "Reviewed STORY-999. Approved.\n", encoding="utf-8"
        )
        has_review, _ = check_review_evidence("STORY-001", board)
        assert has_review is False


# =============================================================================
# get_reviewer_for_story
# =============================================================================

class TestGetReviewer:
    def test_dev1_reviewed_by_dev2(self):
        assert get_reviewer_for_story("STORY-001", "dev1") == "dev2"

    def test_dev2_reviewed_by_dev1(self):
        assert get_reviewer_for_story("STORY-001", "dev2") == "dev1"

    def test_unknown_agent_defaults_to_dev1(self):
        assert get_reviewer_for_story("STORY-001", "po") == "dev1"


# =============================================================================
# MarkdownBoardAdapter review gate integration
# =============================================================================

class TestReviewGateIntegration:
    def test_review_evidence_found_allows_promotion(self, tmp_path):
        """When approval exists in archive, REVIEW->DONE goes through."""
        adapter, board = _make_adapter(tmp_path)
        # Write old sprint
        (board / "sprint.md").write_text(OLD_SPRINT, encoding="utf-8")
        # Create approval evidence
        archive = board / "archive" / "dev2"
        archive.mkdir(parents=True)
        (archive / "20260101_120000.md").write_text(
            "Reviewed STORY-001. LGTM.\n", encoding="utf-8"
        )
        # Apply agent output that promotes STORY-001 to DONE
        pf = ParsedFile(path="board/sprint.md", content=NEW_SPRINT_PROMOTED)
        written = adapter.apply_agent_output("pm", [pf], {})
        assert written == 1
        result = (board / "sprint.md").read_text(encoding="utf-8")
        assert "STORY-001" in result
        # Should be in DONE
        sections = adapter._parse_stories_by_section(result)
        assert "STORY-001" in sections.get("done", set())

    def test_no_evidence_blocks_promotion(self, tmp_path):
        """When no review evidence, story stays in REVIEW."""
        adapter, board = _make_adapter(tmp_path)
        (board / "sprint.md").write_text(OLD_SPRINT, encoding="utf-8")
        pf = ParsedFile(path="board/sprint.md", content=NEW_SPRINT_PROMOTED)
        written = adapter.apply_agent_output("pm", [pf], {})
        assert written == 1
        result = (board / "sprint.md").read_text(encoding="utf-8")
        sections = adapter._parse_stories_by_section(result)
        assert "STORY-001" in sections.get("review", set())
        assert "STORY-001" not in sections.get("done", set())

    def test_rejection_blocks_promotion(self, tmp_path):
        """When rejection found, story stays in REVIEW."""
        adapter, board = _make_adapter(tmp_path)
        (board / "sprint.md").write_text(OLD_SPRINT, encoding="utf-8")
        archive = board / "archive" / "dev2"
        archive.mkdir(parents=True)
        (archive / "20260101_120000.md").write_text(
            "Reviewed STORY-001. Needs changes.\n", encoding="utf-8"
        )
        pf = ParsedFile(path="board/sprint.md", content=NEW_SPRINT_PROMOTED)
        written = adapter.apply_agent_output("pm", [pf], {})
        result = (board / "sprint.md").read_text(encoding="utf-8")
        sections = adapter._parse_stories_by_section(result)
        assert "STORY-001" in sections.get("review", set())

    def test_non_review_transitions_unaffected(self, tmp_path):
        """Transitions not from REVIEW are not blocked."""
        adapter, board = _make_adapter(tmp_path)
        # Old: STORY-020 in IN PROGRESS; New: STORY-020 in DONE (skip REVIEW)
        old = (
            "# Sprint 1\n\n"
            "## IN PROGRESS\n- [ ] STORY-020: Work (dev2)\n\n"
            "## DONE\n"
        )
        new = (
            "# Sprint 1\n\n"
            "## IN PROGRESS\n\n"
            "## DONE\n- [x] STORY-020: Work (dev2)\n"
        )
        (board / "sprint.md").write_text(old, encoding="utf-8")
        pf = ParsedFile(path="board/sprint.md", content=new)
        written = adapter.apply_agent_output("pm", [pf], {})
        assert written == 1
        result = (board / "sprint.md").read_text(encoding="utf-8")
        sections = adapter._parse_stories_by_section(result)
        assert "STORY-020" in sections.get("done", set())

    def test_blocked_transition_sends_inbox(self, tmp_path):
        """Blocked promotion sends an inbox message to the reviewer."""
        adapter, board = _make_adapter(tmp_path)
        (board / "sprint.md").write_text(OLD_SPRINT, encoding="utf-8")
        pf = ParsedFile(path="board/sprint.md", content=NEW_SPRINT_PROMOTED)
        adapter.apply_agent_output("pm", [pf], {})
        inbox = (board / "inbox" / "dev2.md").read_text(encoding="utf-8")
        assert "STORY-001" in inbox
        assert "review" in inbox.lower()

    def test_no_sprint_change_is_noop(self, tmp_path):
        """Writing sprint.md without REVIEW->DONE is unaffected."""
        adapter, board = _make_adapter(tmp_path)
        (board / "sprint.md").write_text(OLD_SPRINT, encoding="utf-8")
        pf = ParsedFile(path="board/sprint.md", content=NEW_SPRINT_NO_CHANGE)
        written = adapter.apply_agent_output("pm", [pf], {})
        assert written == 1
        result = (board / "sprint.md").read_text(encoding="utf-8")
        sections = adapter._parse_stories_by_section(result)
        assert "STORY-001" in sections.get("review", set())
