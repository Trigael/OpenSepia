"""Tests for orchestrator/board/restore.py — board health checking."""

from opensepia.board.restore import check_board_health


# ---------------------------------------------------------------------------
# check_board_health — all files present
# ---------------------------------------------------------------------------

def test_check_board_health_all_present(temp_board_dir):
    report = check_board_health(temp_board_dir)
    assert report["ok"] is True
    assert report["empty"] == []
    assert len(report["present"]) >= 6


# ---------------------------------------------------------------------------
# check_board_health — missing files
# ---------------------------------------------------------------------------

def test_check_board_health_missing_critical_files(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    (board / "project.md").write_text("# Project\n", encoding="utf-8")
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    report = check_board_health(board)

    assert report["ok"] is False
    assert "sprint.md" in report["missing"]
    assert "backlog.md" in report["missing"]


def test_check_board_health_missing_important_files(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")

    report = check_board_health(board)

    assert report["ok"] is False
    assert "project.md" in report["missing"]
    assert "architecture.md" in report["missing"]


# ---------------------------------------------------------------------------
# check_board_health — empty files
# ---------------------------------------------------------------------------

def test_check_board_health_empty_critical_file(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    (board / "sprint.md").write_text("", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("# Project\n", encoding="utf-8")
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    report = check_board_health(board)

    assert report["ok"] is False
    assert "sprint.md" in report["empty"]
    assert "backlog.md" in report["present"]


def test_check_board_health_empty_important_file(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("", encoding="utf-8")
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    report = check_board_health(board)

    assert report["ok"] is False
    assert "project.md" in report["empty"]


# ---------------------------------------------------------------------------
# check_board_health — inbox handling
# ---------------------------------------------------------------------------

def test_check_board_health_missing_inbox_not_critical(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("# Project\n", encoding="utf-8")
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    report = check_board_health(board)

    # Board is ok even without inbox files (health check only checks critical+important)
    assert report["ok"] is True


def test_check_board_health_report_structure(temp_board_dir):
    report = check_board_health(temp_board_dir)

    assert "ok" in report
    assert "missing" in report
    assert "empty" in report
    assert "present" in report
    assert isinstance(report["ok"], bool)
    assert isinstance(report["missing"], list)
    assert isinstance(report["empty"], list)
    assert isinstance(report["present"], list)
