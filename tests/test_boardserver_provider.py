"""Tests for BoardServerProvider — opensepia integration with board server.

Spins up a real board server, connects the provider to it, and tests
the full flow: create issues, update status, comment, inbox, board view.
"""

import json
import os
import threading
import time
import pytest

from boardserver.config import BoardConfig
from boardserver.db import Database
from boardserver.api import create_server

from opensepia.integrations.providers.boardserver import BoardServerProvider, BoardServerConfig
from opensepia.integrations.base import BOARD_LABELS, PRIORITY_LABELS


@pytest.fixture
def live_server(tmp_path):
    """Start a real board server and return (url, provider)."""
    config = BoardConfig.load()
    config.port = 0  # OS picks free port
    config.db_path = str(tmp_path / "test.db")
    db = Database(config.db_path, config)
    db.connect()
    server = create_server(config, db)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    bs_config = BoardServerConfig()
    bs_config.url = url
    provider = BoardServerProvider(bs_config)

    yield provider

    server.shutdown()
    db.close()


# =============================================================================
# Provider basics
# =============================================================================

class TestProviderBasics:
    def test_name(self, live_server):
        assert live_server.name == "boardserver"

    def test_enabled(self, live_server):
        assert live_server.enabled is True

    def test_init(self, live_server):
        live_server.init()  # Should not raise


# =============================================================================
# Issue CRUD
# =============================================================================

class TestIssues:
    def test_create_story(self, live_server):
        result = live_server.create_issue(
            "[STORY-001] User login",
            "Implement login page",
            labels=["status::todo", "priority::high"],
        )
        assert "error" not in result
        assert result["id"].startswith("STORY-")
        assert result["iid"] == result["id"]

    def test_create_bug(self, live_server):
        result = live_server.create_issue(
            "[BUG-001] Login crash",
            "App crashes on login",
            labels=["status::todo", "priority::critical", "type::bug"],
        )
        assert "error" not in result
        assert result["id"].startswith("BUG-")

    def test_list_issues(self, live_server):
        live_server.create_issue("Story 1", "Desc", labels=["status::todo"])
        live_server.create_issue("Story 2", "Desc", labels=["status::in-progress"])
        items = live_server.list_issues()
        assert len(items) == 2
        # All should have labels array
        for item in items:
            assert "labels" in item
            assert "iid" in item
            assert "state" in item

    def test_list_issues_by_state(self, live_server):
        live_server.create_issue("Open", "D", labels=["status::todo"])
        live_server.create_issue("Done", "D", labels=["status::done"])
        opened = live_server.list_issues(state="opened")
        closed = live_server.list_issues(state="closed")
        assert len(opened) == 1
        assert len(closed) == 1

    def test_close_issue(self, live_server):
        item = live_server.create_issue("To close", "D", labels=["status::todo"])
        live_server.close_issue(item["id"])
        closed = live_server.list_issues(state="closed")
        assert len(closed) == 1

    def test_reopen_issue(self, live_server):
        item = live_server.create_issue("To reopen", "D", labels=["status::done"])
        live_server.reopen_issue(item["id"])
        opened = live_server.list_issues(state="opened")
        assert any(i["id"] == item["id"] for i in opened)

    def test_update_issue_status(self, live_server):
        item = live_server.create_issue("S", "D", labels=["status::todo"])
        live_server.update_issue_status(item["id"], "todo", "in_progress")
        updated = live_server.list_issues()
        found = [i for i in updated if i["id"] == item["id"]]
        assert found[0]["status"] == "in_progress"

    def test_update_issue_labels(self, live_server):
        item = live_server.create_issue("S", "D", labels=["status::todo", "priority::low"])
        live_server.update_issue_labels(item["id"], ["status::review", "priority::high"])
        updated = live_server.list_issues()
        found = [i for i in updated if i["id"] == item["id"]]
        assert found[0]["status"] == "review"
        assert found[0].get("priority") == "high"

    def test_find_issue_by_id(self, live_server):
        item = live_server.create_issue("[STORY-042] Test", "D")
        # Direct ID lookup
        found = live_server.find_issue_by_id(item["id"])
        assert found is not None

    def test_find_issue_by_id_not_found(self, live_server):
        found = live_server.find_issue_by_id("STORY-999")
        assert found is None

    def test_search_issues(self, live_server):
        live_server.create_issue("Login feature", "D")
        live_server.create_issue("Dashboard", "D")
        results = live_server.search_issues("login")
        assert len(results) == 1
        assert "Login" in results[0]["title"]


# =============================================================================
# Comments
# =============================================================================

class TestComments:
    def test_comment_on_issue(self, live_server):
        item = live_server.create_issue("S", "D")
        result = live_server.comment_on_issue(item["id"], "dev1", "Looks good!")
        assert "error" not in result

    def test_get_issue_comments(self, live_server):
        item = live_server.create_issue("S", "D")
        live_server.comment_on_issue(item["id"], "dev1", "Comment 1")
        live_server.comment_on_issue(item["id"], "tester", "Comment 2")
        comments = live_server.get_issue_comments(item["id"])
        assert len(comments) == 2
        assert comments[0]["author"]["name"] == "dev1"
        assert comments[1]["body"]  # Has formatted content


# =============================================================================
# Board view
# =============================================================================

class TestBoardView:
    def test_get_board_state(self, live_server):
        live_server.create_issue("S1", "D", labels=["status::todo"])
        live_server.create_issue("S2", "D", labels=["status::in-progress"])
        board = live_server.get_board_state()
        assert isinstance(board, dict)
        assert "todo" in board

    def test_get_board_summary_md(self, live_server):
        live_server.create_issue("S1", "D", labels=["status::todo", "priority::high"])
        md = live_server.get_board_summary_md()
        assert "TODO" in md
        assert "STORY-" in md


# =============================================================================
# MR methods (no-ops)
# =============================================================================

class TestMRNoOps:
    def test_list_mrs_empty(self, live_server):
        assert live_server.list_mrs() == []

    def test_create_mr_not_supported(self, live_server):
        result = live_server.create_mr("branch", "main", "title")
        assert "error" in result

    def test_get_open_mrs_md(self, live_server):
        md = live_server.get_open_mrs_md()
        assert "not manage" in md.lower() or "does not" in md.lower()
