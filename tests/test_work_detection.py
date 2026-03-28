"""Tests for work_detection.py — agent work availability and stuck story detection."""

import pytest
from pathlib import Path

from opensepia.work_detection import (
    agent_has_work,
    detect_stuck_stories,
    escalate_stuck_stories,
    STUCK_THRESHOLD_CYCLES,
)


SPRINT_WITH_WORK = """# Sprint 1

## TODO
- [ ] STORY-001: Setup (dev1)

## IN PROGRESS
- [ ] STORY-002: API endpoints (dev2)

## REVIEW
- [ ] STORY-003: Auth module (dev1)

## TESTING
- [ ] STORY-004: Login flow (tester)

## DONE
- [x] STORY-005: MVP scope (po)

## BLOCKED
"""

SPRINT_EMPTY = """# Sprint 1

## TODO

## IN PROGRESS

## REVIEW

## TESTING

## DONE

## BLOCKED
"""


class TestAgentHasWork:
    def test_po_always_has_work(self):
        assert agent_has_work("po", SPRINT_EMPTY, "") is True

    def test_pm_always_has_work(self):
        assert agent_has_work("pm", SPRINT_EMPTY, "") is True

    def test_dev1_has_assigned_story(self):
        assert agent_has_work("dev1", SPRINT_WITH_WORK, "") is True

    def test_dev2_has_assigned_story(self):
        assert agent_has_work("dev2", SPRINT_WITH_WORK, "") is True

    def test_tester_has_testing_work(self):
        assert agent_has_work("tester", SPRINT_WITH_WORK, "") is True

    def test_dev1_no_work_on_empty_sprint(self):
        assert agent_has_work("dev1", SPRINT_EMPTY, "") is False

    def test_dev2_no_work_on_empty_sprint(self):
        assert agent_has_work("dev2", SPRINT_EMPTY, "") is False

    def test_tester_no_work_on_empty_sprint(self):
        assert agent_has_work("tester", SPRINT_EMPTY, "") is False

    def test_devops_no_work_on_empty_sprint(self):
        assert agent_has_work("devops", SPRINT_EMPTY, "") is False

    def test_inbox_message_means_work(self):
        assert agent_has_work("dev1", SPRINT_EMPTY, "## Message from PM\nDo stuff") is True

    def test_empty_inbox_no_work(self):
        assert agent_has_work("devops", SPRINT_EMPTY, "") is False

    def test_unknown_agent_has_work(self):
        # Spawned agents we don't know about — assume they have work
        assert agent_has_work("frontend_dev", SPRINT_EMPTY, "") is True

    def test_tester_has_work_when_review_stories_exist(self):
        sprint = "## REVIEW\n- [ ] STORY-010: Feature (dev1)\n\n## TESTING\n"
        assert agent_has_work("tester", sprint, "") is True

    def test_security_agent_has_work_when_stories_active(self):
        sprint = "## IN PROGRESS\n- [ ] STORY-001: API (dev1)\n"
        assert agent_has_work("sec_analyst", sprint, "") is True

    def test_security_agent_no_work_when_empty(self):
        assert agent_has_work("sec_analyst", SPRINT_EMPTY, "") is False


class TestDetectStuckStories:
    def test_no_stuck_on_first_cycle(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        stuck = detect_stuck_stories(SPRINT_WITH_WORK, board, 1)
        assert stuck == []

    def test_detects_stuck_after_threshold(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        sprint = "## IN PROGRESS\n- [ ] STORY-001: Stuck story (dev1)\n\n## DONE\n"

        # Simulate N cycles with same state
        for cycle in range(STUCK_THRESHOLD_CYCLES + 1):
            stuck = detect_stuck_stories(sprint, board, cycle)

        assert len(stuck) == 1
        assert stuck[0]["story_id"] == "STORY-001"
        assert stuck[0]["cycles_stuck"] >= STUCK_THRESHOLD_CYCLES

    def test_status_change_resets_counter(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()

        # Story in IN PROGRESS for 2 cycles
        sprint_ip = "## IN PROGRESS\n- [ ] STORY-001: Story (dev1)\n\n## DONE\n"
        detect_stuck_stories(sprint_ip, board, 0)
        detect_stuck_stories(sprint_ip, board, 1)

        # Story moves to REVIEW — counter resets
        sprint_review = "## IN PROGRESS\n\n## REVIEW\n- [ ] STORY-001: Story (dev1)\n\n## DONE\n"
        stuck = detect_stuck_stories(sprint_review, board, 2)
        assert stuck == []

    def test_done_stories_not_tracked(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        sprint = "## DONE\n- [x] STORY-001: Done story (dev1)\n"
        for cycle in range(5):
            stuck = detect_stuck_stories(sprint, board, cycle)
        assert stuck == []

    def test_blocked_stories_not_tracked(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        sprint = "## BLOCKED\n- [ ] STORY-001: Blocked (dev1)\n"
        for cycle in range(5):
            stuck = detect_stuck_stories(sprint, board, cycle)
        assert stuck == []


class TestEscalateStuckStories:
    def test_sends_inbox_to_po(self, tmp_path):
        board = tmp_path / "board"
        (board / "inbox").mkdir(parents=True)
        (board / "inbox" / "po.md").write_text("")

        stuck = [{"story_id": "STORY-001", "status": "in progress", "stuck_since_cycle": 0, "cycles_stuck": 4}]
        count = escalate_stuck_stories(stuck, board)

        assert count == 1
        po_inbox = (board / "inbox" / "po.md").read_text()
        assert "STORY-001" in po_inbox
        assert "Stuck Stories" in po_inbox

    def test_no_duplicate_alerts(self, tmp_path):
        board = tmp_path / "board"
        (board / "inbox").mkdir(parents=True)
        (board / "inbox" / "po.md").write_text("## System Alert — Stuck Stories\nold alert")

        stuck = [{"story_id": "STORY-001", "status": "review", "stuck_since_cycle": 0, "cycles_stuck": 5}]
        count = escalate_stuck_stories(stuck, board)

        assert count == 0  # Duplicate not sent

    def test_empty_stuck_list(self, tmp_path):
        board = tmp_path / "board"
        (board / "inbox").mkdir(parents=True)
        (board / "inbox" / "po.md").write_text("")

        count = escalate_stuck_stories([], board)
        assert count == 0
