"""Tests for orchestrator/board/sync.py — backlog parsing and status normalization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.board.sync import parse_backlog, normalize_status, parse_sprint_statuses


# ---------------------------------------------------------------------------
# parse_backlog
# ---------------------------------------------------------------------------

SAMPLE_BACKLOG = """\
# Backlog

## CRITICAL

## HIGH

### STORY-001: User authentication
**Priority**: HIGH
**Status**: IN_PROGRESS
**Assigned**: dev1

### BUG-001: Login page crash
**Priority**: HIGH
**Status**: TODO

## MEDIUM

### STORY-002: Dashboard widgets
**Priority**: MEDIUM
**Status**: TODO

## LOW
"""


def test_parse_backlog_returns_all_items(tmp_path):
    p = tmp_path / "backlog.md"
    p.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(p)
    assert len(items) == 3


def test_parse_backlog_extracts_ids(tmp_path):
    p = tmp_path / "backlog.md"
    p.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(p)
    ids = [item["id"] for item in items]
    assert "STORY-001" in ids
    assert "BUG-001" in ids
    assert "STORY-002" in ids


def test_parse_backlog_extracts_priority(tmp_path):
    p = tmp_path / "backlog.md"
    p.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(p)
    story_001 = next(i for i in items if i["id"] == "STORY-001")
    assert story_001["priority"] == "high"
    story_002 = next(i for i in items if i["id"] == "STORY-002")
    assert story_002["priority"] == "medium"


def test_parse_backlog_extracts_status(tmp_path):
    p = tmp_path / "backlog.md"
    p.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(p)
    story_001 = next(i for i in items if i["id"] == "STORY-001")
    assert story_001["status"] == "in_progress"


def test_parse_backlog_detects_bugs(tmp_path):
    p = tmp_path / "backlog.md"
    p.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(p)
    bug = next(i for i in items if i["id"] == "BUG-001")
    assert bug["is_bug"] is True
    story = next(i for i in items if i["id"] == "STORY-001")
    assert story["is_bug"] is False


def test_parse_backlog_extracts_assigned(tmp_path):
    p = tmp_path / "backlog.md"
    p.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(p)
    story_001 = next(i for i in items if i["id"] == "STORY-001")
    assert story_001["assigned"] == "dev1"


def test_parse_backlog_empty_file(tmp_path):
    p = tmp_path / "backlog.md"
    p.write_text("# Backlog\n\nEmpty.\n", encoding="utf-8")
    items = parse_backlog(p)
    assert items == []


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------

def test_normalize_status_todo():
    assert normalize_status("TODO") == "todo"

def test_normalize_status_in_progress():
    assert normalize_status("IN_PROGRESS") == "in_progress"

def test_normalize_status_done():
    assert normalize_status("DONE") == "done"

def test_normalize_status_done_conditional():
    assert normalize_status("DONE (conditionally accepted)") == "done"

def test_normalize_status_blocked():
    assert normalize_status("BLOCKED") == "blocked"

def test_normalize_status_review():
    assert normalize_status("REVIEW") == "review"

def test_normalize_status_testing():
    assert normalize_status("TESTING") == "testing"

def test_normalize_status_unknown_defaults_to_todo():
    assert normalize_status("something random") == "todo"

def test_normalize_status_case_insensitive():
    assert normalize_status("in progress") == "in_progress"
    assert normalize_status("In Progress") == "in_progress"


# ---------------------------------------------------------------------------
# parse_sprint_statuses
# ---------------------------------------------------------------------------

SAMPLE_SPRINT_SECTIONS = """\
# Sprint 1

## TODO
- [ ] STORY-003: New feature

## IN PROGRESS
- [ ] STORY-001: Auth system

## DONE
- [x] STORY-004: Old feature
"""

SAMPLE_SPRINT_BLOCKS = """\
# Sprint 1

### STORY-005: Widget
**Status**: REVIEW
"""


def test_parse_sprint_statuses_section_based(tmp_path):
    p = tmp_path / "sprint.md"
    p.write_text(SAMPLE_SPRINT_SECTIONS, encoding="utf-8")
    statuses = parse_sprint_statuses(p)
    assert statuses.get("STORY-003") == "todo"
    assert statuses.get("STORY-001") == "in_progress"
    assert statuses.get("STORY-004") == "done"


def test_parse_sprint_statuses_block_based(tmp_path):
    p = tmp_path / "sprint.md"
    p.write_text(SAMPLE_SPRINT_BLOCKS, encoding="utf-8")
    statuses = parse_sprint_statuses(p)
    assert statuses.get("STORY-005") == "review"


def test_parse_sprint_statuses_section_takes_priority(tmp_path):
    combined = SAMPLE_SPRINT_SECTIONS + "\n" + SAMPLE_SPRINT_BLOCKS
    p = tmp_path / "sprint.md"
    p.write_text(combined, encoding="utf-8")
    statuses = parse_sprint_statuses(p)
    assert statuses.get("STORY-001") == "in_progress"
    assert statuses.get("STORY-005") == "review"


def test_parse_sprint_statuses_empty_file(tmp_path):
    p = tmp_path / "sprint.md"
    p.write_text("# Sprint 1\n\nNothing here yet.\n", encoding="utf-8")
    statuses = parse_sprint_statuses(p)
    assert statuses == {}
