"""Tests for quality_gates.py and DoD enforcement in MarkdownBoardAdapter."""

import pytest
from pathlib import Path

from opensepia.quality_gates import check_definition_of_done
from opensepia.board_adapter_markdown import MarkdownBoardAdapter
from opensepia.agents.parser import ParsedFile


# =============================================================================
# check_definition_of_done — unit tests
# =============================================================================

class TestCheckDefinitionOfDone:
    def test_all_checked_passes(self):
        text = (
            "### STORY-001: Login\n"
            "- [x] User can enter credentials\n"
            "- [x] Error shown on bad password\n"
            "- [x] Session token stored\n"
        )
        passed, unchecked = check_definition_of_done(text)
        assert passed is True
        assert unchecked == []

    def test_unchecked_fails(self):
        text = (
            "### STORY-001: Login\n"
            "- [x] User can enter credentials\n"
            "- [ ] Error shown on bad password\n"
            "- [x] Session token stored\n"
        )
        passed, unchecked = check_definition_of_done(text)
        assert passed is False
        assert unchecked == ["Error shown on bad password"]

    def test_multiple_unchecked(self):
        text = (
            "### STORY-001: Login\n"
            "- [ ] User can enter credentials\n"
            "- [ ] Error shown on bad password\n"
            "- [x] Session token stored\n"
        )
        passed, unchecked = check_definition_of_done(text)
        assert passed is False
        assert len(unchecked) == 2
        assert "User can enter credentials" in unchecked
        assert "Error shown on bad password" in unchecked

    def test_no_checkboxes_passes(self):
        """Backward compat: stories without acceptance criteria pass."""
        text = "### STORY-001: Login\nImplement login page.\n"
        passed, unchecked = check_definition_of_done(text)
        assert passed is True
        assert unchecked == []

    def test_empty_text_passes(self):
        passed, unchecked = check_definition_of_done("")
        assert passed is True
        assert unchecked == []

    def test_whitespace_only_passes(self):
        passed, unchecked = check_definition_of_done("   \n\n  ")
        assert passed is True
        assert unchecked == []

    def test_uppercase_x_passes(self):
        text = "- [X] Criterion one\n- [x] Criterion two\n"
        passed, unchecked = check_definition_of_done(text)
        assert passed is True
        assert unchecked == []

    def test_indented_checkboxes(self):
        text = "  - [ ] Indented criterion\n  - [x] Done criterion\n"
        passed, unchecked = check_definition_of_done(text)
        assert passed is False
        assert unchecked == ["Indented criterion"]

    def test_mixed_content(self):
        """Checkboxes mixed with plain text."""
        text = (
            "### STORY-001\n"
            "Some description text.\n\n"
            "**Acceptance Criteria:**\n"
            "- [x] First criterion\n"
            "- [ ] Second criterion\n"
            "\nNotes: something else\n"
        )
        passed, unchecked = check_definition_of_done(text)
        assert passed is False
        assert unchecked == ["Second criterion"]


# =============================================================================
# MarkdownBoardAdapter DoD integration — helpers
# =============================================================================

def _make_adapter(tmp_path, sprint_text="", backlog_text=""):
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    for a in ["po", "pm", "dev1"]:
        (board / "inbox" / f"{a}.md").write_text("", encoding="utf-8")
    (board / "sprint.md").write_text(sprint_text, encoding="utf-8")
    (board / "backlog.md").write_text(backlog_text, encoding="utf-8")
    ws = tmp_path / "workspace"
    ws.mkdir()
    return MarkdownBoardAdapter(board_dir=board, workspace_dir=ws, project_dir=tmp_path), board


def _agents_config():
    return {"agents": {"po": {}, "dev1": {}}}


# =============================================================================
# _extract_done_ids
# =============================================================================

class TestExtractDoneIds:
    def test_finds_done_ids(self):
        text = (
            "## TODO\n- [ ] STORY-001: Login\n\n"
            "## DONE\n- [x] STORY-002: Setup\n- [x] BUG-010: Fix\n"
        )
        ids = MarkdownBoardAdapter._extract_done_ids(text)
        assert ids == {"STORY-002", "BUG-010"}

    def test_empty_done(self):
        text = "## TODO\n- [ ] STORY-001\n\n## DONE\n"
        ids = MarkdownBoardAdapter._extract_done_ids(text)
        assert ids == set()

    def test_no_done_section(self):
        text = "## TODO\n- [ ] STORY-001\n"
        ids = MarkdownBoardAdapter._extract_done_ids(text)
        assert ids == set()


# =============================================================================
# _extract_story_from_backlog
# =============================================================================

class TestExtractStoryFromBacklog:
    def test_extracts_story(self):
        backlog = (
            "# Backlog\n\n"
            "## HIGH\n"
            "### STORY-001: Login\n"
            "- [x] User enters credentials\n"
            "- [ ] Error on bad password\n\n"
            "### STORY-002: Dashboard\n"
            "- [x] Shows widgets\n"
        )
        section = MarkdownBoardAdapter._extract_story_from_backlog("STORY-001", backlog)
        assert "STORY-001" in section
        assert "Error on bad password" in section
        assert "STORY-002" not in section

    def test_missing_story_returns_empty(self):
        backlog = "# Backlog\n\n## HIGH\n### STORY-001\nStuff\n"
        section = MarkdownBoardAdapter._extract_story_from_backlog("STORY-999", backlog)
        assert section == ""

    def test_story_at_end_of_file(self):
        backlog = "## HIGH\n### STORY-001: Login\n- [ ] Criterion\n"
        section = MarkdownBoardAdapter._extract_story_from_backlog("STORY-001", backlog)
        assert "Criterion" in section


# =============================================================================
# _revert_stories_to_review
# =============================================================================

class TestRevertStoriesToReview:
    def test_moves_story_from_done_to_review(self):
        sprint = (
            "## REVIEW\n"
            "- [ ] STORY-010: Old review\n\n"
            "## DONE\n"
            "- [x] STORY-001: Login\n"
            "- [x] STORY-002: Setup\n"
        )
        result = MarkdownBoardAdapter._revert_stories_to_review(sprint, {"STORY-001"})
        lines = result.split("\n")
        # STORY-001 should be after REVIEW header, not in DONE
        review_idx = next(i for i, l in enumerate(lines) if "## REVIEW" in l)
        done_idx = next(i for i, l in enumerate(lines) if "## DONE" in l)
        story_lines = [i for i, l in enumerate(lines) if "STORY-001" in l]
        assert len(story_lines) == 1
        assert review_idx < story_lines[0] < done_idx

    def test_creates_review_section_if_missing(self):
        sprint = "## TODO\n\n## DONE\n- [x] STORY-001: Login\n"
        result = MarkdownBoardAdapter._revert_stories_to_review(sprint, {"STORY-001"})
        assert "## REVIEW" in result
        assert "STORY-001" in result


# =============================================================================
# apply_agent_output integration — DoD gate
# =============================================================================

class TestApplyAgentOutputDoDGate:
    def test_story_with_all_criteria_checked_moves_to_done(self, tmp_path):
        """Story with all checkboxes checked passes the gate."""
        old_sprint = "## TODO\n- [ ] STORY-001: Login (dev1)\n\n## DONE\n"
        backlog = (
            "# Backlog\n\n"
            "### STORY-001: Login\n"
            "- [x] User can log in\n"
            "- [x] Error on bad password\n"
        )
        adapter, board = _make_adapter(tmp_path, old_sprint, backlog)

        new_sprint = "## TODO\n\n## DONE\n- [x] STORY-001: Login (dev1)\n"
        files = [ParsedFile(path="board/sprint.md", content=new_sprint, action="overwrite")]
        adapter.apply_agent_output("dev1", files, _agents_config())

        result = (board / "sprint.md").read_text(encoding="utf-8")
        # Story should be in DONE since all criteria are checked
        assert "STORY-001" in result
        # PO inbox should be empty (no notification)
        po_inbox = (board / "inbox" / "po.md").read_text(encoding="utf-8")
        assert "blocked" not in po_inbox.lower()

    def test_story_with_unchecked_criteria_blocked(self, tmp_path):
        """Story with unchecked criteria is reverted to REVIEW."""
        old_sprint = "## REVIEW\n- [ ] STORY-001: Login (dev1)\n\n## DONE\n"
        backlog = (
            "# Backlog\n\n"
            "### STORY-001: Login\n"
            "- [x] User can log in\n"
            "- [ ] Error on bad password\n"
        )
        adapter, board = _make_adapter(tmp_path, old_sprint, backlog)
        # Seed review evidence so review gate passes (we're testing DoD gate)
        archive_dir = board / "archive" / "dev2"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "review.md").write_text("STORY-001 code review: APPROVED\n")

        new_sprint = "## REVIEW\n\n## DONE\n- [x] STORY-001: Login (dev1)\n"
        files = [ParsedFile(path="board/sprint.md", content=new_sprint, action="overwrite")]
        adapter.apply_agent_output("dev1", files, _agents_config())

        result = (board / "sprint.md").read_text(encoding="utf-8")
        # Story should NOT be in DONE — should be in REVIEW
        done_section = result.split("## DONE")[-1] if "## DONE" in result else ""
        assert "STORY-001" not in done_section
        review_section = result.split("## REVIEW")[1].split("## ")[0] if "## REVIEW" in result else ""
        assert "STORY-001" in review_section

        # PO should have been notified
        po_inbox = (board / "inbox" / "po.md").read_text(encoding="utf-8")
        assert "STORY-001" in po_inbox
        assert "Error on bad password" in po_inbox
        assert "blocked" in po_inbox.lower()

    def test_story_without_criteria_passes(self, tmp_path):
        """Backward compat: story with no checkboxes in backlog passes."""
        old_sprint = "## TODO\n- [ ] STORY-001: Login (dev1)\n\n## DONE\n"
        backlog = "# Backlog\n\n### STORY-001: Login\nImplement login.\n"
        adapter, board = _make_adapter(tmp_path, old_sprint, backlog)

        new_sprint = "## TODO\n\n## DONE\n- [x] STORY-001: Login (dev1)\n"
        files = [ParsedFile(path="board/sprint.md", content=new_sprint, action="overwrite")]
        adapter.apply_agent_output("dev1", files, _agents_config())

        result = (board / "sprint.md").read_text(encoding="utf-8")
        done_section = result.split("## DONE")[-1] if "## DONE" in result else ""
        assert "STORY-001" in done_section

    def test_story_not_in_backlog_passes(self, tmp_path):
        """Story not found in backlog passes (no criteria to check)."""
        old_sprint = "## TODO\n- [ ] STORY-001: Login\n\n## DONE\n"
        backlog = "# Backlog\n"
        adapter, board = _make_adapter(tmp_path, old_sprint, backlog)

        new_sprint = "## TODO\n\n## DONE\n- [x] STORY-001: Login\n"
        files = [ParsedFile(path="board/sprint.md", content=new_sprint, action="overwrite")]
        adapter.apply_agent_output("dev1", files, _agents_config())

        result = (board / "sprint.md").read_text(encoding="utf-8")
        done_section = result.split("## DONE")[-1]
        assert "STORY-001" in done_section

    def test_non_sprint_files_unaffected(self, tmp_path):
        """Non-sprint.md files are not subject to DoD gate."""
        adapter, board = _make_adapter(tmp_path, "", "")
        files = [ParsedFile(path="board/standup.md", content="# Standup\n- Did stuff\n", action="overwrite")]
        count = adapter.apply_agent_output("dev1", files, _agents_config())
        assert count == 1

    def test_already_done_story_not_rechecked(self, tmp_path):
        """A story already in DONE is not re-checked when sprint is rewritten."""
        old_sprint = "## DONE\n- [x] STORY-001: Login\n"
        backlog = "### STORY-001: Login\n- [ ] Unchecked criterion\n"
        adapter, board = _make_adapter(tmp_path, old_sprint, backlog)

        # Rewrite sprint with same DONE story
        new_sprint = "## DONE\n- [x] STORY-001: Login\n"
        files = [ParsedFile(path="board/sprint.md", content=new_sprint, action="overwrite")]
        adapter.apply_agent_output("dev1", files, _agents_config())

        result = (board / "sprint.md").read_text(encoding="utf-8")
        # Story should remain in DONE since it was already there
        assert "STORY-001" in result.split("## DONE")[-1]

    def test_multiple_stories_mixed_gate(self, tmp_path):
        """One story passes, another is blocked."""
        old_sprint = "## REVIEW\n- [ ] STORY-001\n- [ ] STORY-002\n\n## DONE\n"
        backlog = (
            "### STORY-001: Login\n"
            "- [x] All done\n\n"
            "### STORY-002: Dashboard\n"
            "- [ ] Not done yet\n"
        )
        adapter, board = _make_adapter(tmp_path, old_sprint, backlog)
        # Seed review evidence for both stories so review gate passes
        archive_dir = board / "archive" / "dev2"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "review.md").write_text(
            "STORY-001 APPROVED\nSTORY-002 APPROVED\n"
        )

        new_sprint = (
            "## REVIEW\n\n"
            "## DONE\n"
            "- [x] STORY-001: Login\n"
            "- [x] STORY-002: Dashboard\n"
        )
        files = [ParsedFile(path="board/sprint.md", content=new_sprint, action="overwrite")]
        adapter.apply_agent_output("dev1", files, _agents_config())

        result = (board / "sprint.md").read_text(encoding="utf-8")
        done_section = result.split("## DONE")[-1]
        # STORY-001 should be in DONE
        assert "STORY-001" in done_section
        # STORY-002 should be in REVIEW, not DONE
        assert "STORY-002" not in done_section
        review_section = result.split("## REVIEW")[1].split("## ")[0]
        assert "STORY-002" in review_section
