"""Chaos monkey tests — throw bad data and edge cases at everything.

Tests unexpected inputs, malformed requests, concurrent access,
large payloads, empty data, unicode, and error recovery.
"""

import json
import threading
import time
import pytest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from boardserver.config import BoardConfig
from boardserver.db import Database
from boardserver.api import create_server
from opensepia.integrations.providers.boardserver import BoardServerProvider, BoardServerConfig
from opensepia.cycle_state import CycleState
from opensepia.daemon_state import DaemonState
from opensepia.lockfile import ProcessLock


@pytest.fixture
def live_server(tmp_path):
    """Start a real board server."""
    config = BoardConfig.load()
    config.port = 0
    config.db_path = str(tmp_path / "chaos.db")
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

    yield url, provider, db

    server.shutdown()
    db.close()


def _raw_api(url, method, path, body=None):
    """Raw HTTP call for malformed request testing."""
    data = body.encode("utf-8") if isinstance(body, str) else (
        json.dumps(body).encode("utf-8") if body else None
    )
    req = Request(f"{url}/api{path}", data=data, method=method,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"raw": body_text}


# =============================================================================
# Malformed API requests
# =============================================================================

class TestMalformedRequests:
    def test_empty_body_post(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "POST", "/items", body="{}")
        assert status == 400

    def test_invalid_json_body(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "POST", "/items", body="not json{{{")
        assert status == 400

    def test_unknown_item_type(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "POST", "/items", body={"type": "spaceship", "title": "X"})
        assert status == 400
        assert "Unknown" in resp.get("error", "")

    def test_missing_required_field(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "POST", "/items", body={"type": "story"})
        assert status == 400

    def test_invalid_enum_value(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "POST", "/items",
                                body={"type": "story", "title": "T", "status": "banana"})
        assert status == 400

    def test_get_nonexistent_item(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "GET", "/items/STORY-999")
        assert status == 404

    def test_patch_nonexistent_item(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "PATCH", "/items/STORY-999", body={"status": "done"})
        assert status == 404

    def test_delete_nonexistent_item(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "DELETE", "/items/STORY-999")
        assert status == 404

    def test_comment_on_nonexistent_item(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "POST", "/items/STORY-999/comments",
                                body={"body": "hello"})
        assert status == 404

    def test_empty_comment(self, live_server):
        url, provider, _ = live_server
        item = provider.create_issue("Test", "D")
        status, resp = _raw_api(url, "POST", f"/items/{item['id']}/comments",
                                body={"body": ""})
        assert status == 400

    def test_nonexistent_api_path(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "GET", "/items/STORY-001/nonexistent")
        assert status == 404

    def test_wrong_http_method(self, live_server):
        url, _, _ = live_server
        status, resp = _raw_api(url, "DELETE", "/items")
        assert status == 404


# =============================================================================
# Unicode and special characters
# =============================================================================

class TestUnicode:
    def test_unicode_title(self, live_server):
        _, provider, _ = live_server
        item = provider.create_issue("Héllo Wörld 日本語 🚀", "Description with émojis 💻")
        assert "error" not in item
        fetched = provider.list_issues()
        assert any("Héllo" in i.get("title", "") for i in fetched)

    def test_unicode_comment(self, live_server):
        _, provider, _ = live_server
        item = provider.create_issue("Test", "D")
        provider.comment_on_issue(item["id"], "dev1", "Výborně! 🎉 Это работает!")
        comments = provider.get_issue_comments(item["id"])
        assert len(comments) >= 1

    def test_special_chars_in_title(self, live_server):
        _, provider, _ = live_server
        item = provider.create_issue('Title with "quotes" & <html> tags', "D")
        assert "error" not in item

    def test_very_long_title(self, live_server):
        _, provider, _ = live_server
        item = provider.create_issue("A" * 10000, "D")
        assert "error" not in item

    def test_very_long_description(self, live_server):
        _, provider, _ = live_server
        item = provider.create_issue("Test", "D" * 100000)
        assert "error" not in item

    def test_newlines_in_comment(self, live_server):
        _, provider, _ = live_server
        item = provider.create_issue("Test", "D")
        provider.comment_on_issue(item["id"], "dev1", "Line 1\nLine 2\n\nLine 4")
        comments = provider.get_issue_comments(item["id"])
        assert "Line 1" in comments[-1]["body"]


# =============================================================================
# Concurrent access
# =============================================================================

class TestConcurrency:
    def test_concurrent_creates(self, live_server):
        """Multiple threads creating items simultaneously."""
        url, provider, _ = live_server
        results = []
        errors = []

        def create_item(i):
            try:
                item = provider.create_issue(f"Concurrent story {i}", "D")
                results.append(item)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=create_item, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10
        # All IDs should be unique
        ids = [r["id"] for r in results if "id" in r]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {ids}"

    def test_concurrent_comments(self, live_server):
        """Multiple threads commenting on the same item."""
        _, provider, _ = live_server
        item = provider.create_issue("Comment target", "D")
        errors = []

        def add_comment(i):
            try:
                provider.comment_on_issue(item["id"], f"agent{i}", f"Comment {i}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=add_comment, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
        comments = provider.get_issue_comments(item["id"], limit=50)
        assert len(comments) == 10


# =============================================================================
# Provider with dead/unreachable server
# =============================================================================

class TestDeadServer:
    def test_provider_with_wrong_url(self):
        config = BoardServerConfig()
        config.url = "http://127.0.0.1:1"  # Nothing listening
        provider = BoardServerProvider(config)

        # Should return error dicts, not crash
        result = provider.create_issue("Test", "D")
        assert "error" in result

        items = provider.list_issues()
        assert items == []

        found = provider.find_issue_by_id("STORY-001")
        assert found is None

    def test_provider_with_empty_url(self):
        config = BoardServerConfig()
        config.url = ""
        provider = BoardServerProvider(config)
        assert provider.enabled is False


# =============================================================================
# CycleState edge cases
# =============================================================================

class TestCycleStateChaos:
    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("", encoding="utf-8")
        state = CycleState.load(path)
        assert state.status == "pending"

    def test_load_null_json(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("null", encoding="utf-8")
        state = CycleState.load(path)
        assert state.status == "pending"

    def test_load_array_json(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("[1,2,3]", encoding="utf-8")
        state = CycleState.load(path)
        assert state.status == "pending"

    def test_load_partial_json(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text('{"status": "in_progress"}', encoding="utf-8")
        state = CycleState.load(path)
        assert state.status == "in_progress"
        assert state.completed_steps == []

    def test_load_extra_fields(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text('{"status": "completed", "unknown_field": 42}', encoding="utf-8")
        state = CycleState.load(path)
        assert state.status == "completed"

    def test_save_to_readonly_dir(self, tmp_path):
        """Save should handle permission errors gracefully."""
        path = tmp_path / "nonexistent" / "deep" / "state.json"
        state = CycleState(cycle_id="test")
        state.save(path)  # Should create dirs
        assert path.exists()


# =============================================================================
# DaemonState edge cases
# =============================================================================

class TestDaemonStateChaos:
    def test_load_binary_garbage(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_bytes(b"\x00\xff\xfe\x80")
        state = DaemonState.load(path)
        assert state.status == "stopped"

    def test_is_process_alive_negative_pid(self):
        state = DaemonState(pid=-1)
        assert state.is_process_alive() is False

    def test_is_process_alive_very_large_pid(self):
        state = DaemonState(pid=999999999)
        assert state.is_process_alive() is False


# =============================================================================
# Lockfile edge cases
# =============================================================================

class TestLockfileChaos:
    def test_lock_with_corrupted_pid_file(self, tmp_path):
        lock_path = tmp_path / "ai-team-cli-chaos.lock"
        lock_path.write_text("not-a-number", encoding="utf-8")
        lock = ProcessLock("chaos", lock_dir=str(tmp_path))
        lock.acquire()  # Should handle gracefully
        assert lock_path.exists()
        assert lock_path.read_text(encoding="utf-8").strip().isdigit()
        lock.release()
        assert not lock_path.exists()

    def test_lock_with_empty_pid_file(self, tmp_path):
        lock_path = tmp_path / "ai-team-cli-chaos.lock"
        lock_path.write_text("", encoding="utf-8")
        lock = ProcessLock("chaos", lock_dir=str(tmp_path))
        lock.acquire()
        assert lock_path.exists()
        assert lock_path.read_text(encoding="utf-8").strip().isdigit()
        lock.release()
        assert not lock_path.exists()

    def test_double_release(self, tmp_path):
        lock = ProcessLock("chaos", lock_dir=str(tmp_path))
        lock_path = tmp_path / "ai-team-cli-chaos.lock"
        lock.acquire()
        assert lock_path.exists()
        lock.release()
        assert not lock_path.exists()
        lock.release()  # Should not raise
        assert not lock_path.exists()


# =============================================================================
# Database edge cases
# =============================================================================

class TestDatabaseChaos:
    @pytest.fixture
    def db(self, tmp_path):
        config = BoardConfig.load()
        database = Database(str(tmp_path / "chaos.db"), config)
        database.connect()
        yield database
        database.close()

    def test_create_many_items(self, db):
        """Create 100 items and verify IDs are sequential."""
        for i in range(100):
            db.create_item("story", {"title": f"Story {i}"})
        items = db.list_items()
        assert len(items) == 100
        assert items[0]["id"] == "STORY-001"
        assert items[99]["id"] == "STORY-100"

    def test_update_with_no_changes(self, db):
        item = db.create_item("story", {"title": "Same", "status": "todo"})
        result = db.update_item(item["id"], {"status": "todo"})
        assert "_changes" not in result or result["_changes"] == {}

    def test_comment_with_empty_author(self, db):
        item = db.create_item("story", {"title": "S"})
        comment = db.add_comment(item["id"], "", "Anonymous comment")
        assert comment["author"] == ""

    def test_inbox_to_unknown_agent(self, db):
        """Sending to unknown agent should still work."""
        msg = db.send_inbox("nonexistent_agent", "Hello!")
        assert msg["agent_id"] == "nonexistent_agent"
        messages = db.get_inbox("nonexistent_agent")
        assert len(messages) == 1

    def test_get_board_empty_db(self, db):
        board = db.get_board()
        assert board == {}

    def test_get_events_empty_db(self, db):
        events = db.get_events()
        assert events == []
