"""Tests for boardserver — config, database, and API."""

import json
import pytest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import threading
import time

from boardserver.config import BoardConfig, FieldDef, ItemTypeDef
from boardserver.db import Database
from boardserver.events import EventProcessor
from boardserver.api import create_server


# =============================================================================
# Config
# =============================================================================

class TestConfig:
    def test_load_default_config(self):
        config = BoardConfig.load()
        assert "story" in config.item_types
        assert "bug" in config.item_types
        assert config.port == 8080

    def test_item_type_has_fields(self):
        config = BoardConfig.load()
        story = config.item_types["story"]
        assert "title" in story.fields
        assert "status" in story.fields
        assert "priority" in story.fields

    def test_field_validation_required(self):
        f = FieldDef(name="title", type="string", required=True)
        ok, msg = f.validate(None)
        assert not ok
        assert "required" in msg

    def test_field_validation_enum(self):
        f = FieldDef(name="status", type="enum", values=["todo", "done"])
        ok, _ = f.validate("todo")
        assert ok
        ok, msg = f.validate("invalid")
        assert not ok
        assert "must be one of" in msg

    def test_field_validation_string(self):
        f = FieldDef(name="title", type="string")
        ok, _ = f.validate("hello")
        assert ok
        ok, _ = f.validate(123)
        assert not ok

    def test_item_type_validate_data(self):
        fields = {
            "title": FieldDef(name="title", type="string", required=True),
            "status": FieldDef(name="status", type="enum", values=["todo", "done"]),
        }
        td = ItemTypeDef(name="story", id_prefix="STORY", fields=fields)
        ok, errors = td.validate_data({"title": "Test", "status": "todo"})
        assert ok

    def test_item_type_apply_defaults(self):
        fields = {
            "status": FieldDef(name="status", type="enum", values=["todo", "done"], default="todo"),
        }
        td = ItemTypeDef(name="story", id_prefix="STORY", fields=fields)
        data = td.apply_defaults({})
        assert data["status"] == "todo"

    def test_agents_parsed(self):
        config = BoardConfig.load()
        assert "po" in config.agents
        assert config.agents["po"].name == "Product Owner"

    def test_events_parsed(self):
        config = BoardConfig.load()
        assert "item_created" in config.events
        assert len(config.events["item_created"]) > 0


# =============================================================================
# Database
# =============================================================================

class TestDatabase:
    @pytest.fixture
    def db(self, tmp_path):
        config = BoardConfig.load()
        database = Database(str(tmp_path / "test.db"), config)
        database.connect()
        yield database
        database.close()

    def test_create_item(self, db):
        item = db.create_item("story", {"title": "Test story"}, created_by="po")
        assert item["id"].startswith("STORY-")
        assert item["title"] == "Test story"
        assert item["status"] == "todo"  # default

    def test_get_item(self, db):
        created = db.create_item("story", {"title": "Test"})
        fetched = db.get_item(created["id"])
        assert fetched is not None
        assert fetched["title"] == "Test"

    def test_get_item_not_found(self, db):
        assert db.get_item("STORY-999") is None

    def test_list_items(self, db):
        db.create_item("story", {"title": "Story 1"})
        db.create_item("story", {"title": "Story 2"})
        db.create_item("bug", {"title": "Bug 1"})
        assert len(db.list_items()) == 3
        assert len(db.list_items(item_type="story")) == 2
        assert len(db.list_items(item_type="bug")) == 1

    def test_list_items_filter_status(self, db):
        db.create_item("story", {"title": "S1", "status": "todo"})
        db.create_item("story", {"title": "S2", "status": "done"})
        assert len(db.list_items(status="todo")) == 1
        assert len(db.list_items(status="done")) == 1

    def test_update_item(self, db):
        item = db.create_item("story", {"title": "Old"})
        updated = db.update_item(item["id"], {"title": "New", "status": "in_progress"})
        assert updated["title"] == "New"
        assert updated["status"] == "in_progress"
        assert "status" in updated.get("_changes", {})

    def test_update_item_not_found(self, db):
        assert db.update_item("STORY-999", {"title": "X"}) is None

    def test_delete_item(self, db):
        item = db.create_item("story", {"title": "Delete me"})
        assert db.delete_item(item["id"]) is True
        assert db.get_item(item["id"]) is None

    def test_sequential_ids(self, db):
        s1 = db.create_item("story", {"title": "First"})
        s2 = db.create_item("story", {"title": "Second"})
        b1 = db.create_item("bug", {"title": "Bug"})
        assert s1["id"] == "STORY-001"
        assert s2["id"] == "STORY-002"
        assert b1["id"] == "BUG-001"

    def test_validation_rejects_bad_data(self, db):
        with pytest.raises(ValueError, match="required"):
            db.create_item("story", {})  # missing required title

    def test_validation_rejects_bad_enum(self, db):
        with pytest.raises(ValueError, match="must be one of"):
            db.create_item("story", {"title": "T", "status": "banana"})

    # ----- Comments -----

    def test_add_comment(self, db):
        item = db.create_item("story", {"title": "S"})
        comment = db.add_comment(item["id"], "dev1", "Looks good!")
        assert comment["author"] == "dev1"
        assert comment["body"] == "Looks good!"

    def test_get_comments(self, db):
        item = db.create_item("story", {"title": "S"})
        db.add_comment(item["id"], "dev1", "Comment 1")
        db.add_comment(item["id"], "dev2", "Comment 2")
        comments = db.get_comments(item["id"])
        assert len(comments) == 2
        assert comments[0]["body"] == "Comment 1"

    # ----- Inbox -----

    def test_send_and_get_inbox(self, db):
        db.send_inbox("dev1", "Hello dev1!", from_agent="pm")
        messages = db.get_inbox("dev1")
        assert len(messages) == 1
        assert messages[0]["message"] == "Hello dev1!"
        assert messages[0]["from_agent"] == "pm"

    def test_inbox_unread_filter(self, db):
        db.send_inbox("dev1", "Msg 1")
        db.send_inbox("dev1", "Msg 2")
        assert len(db.get_inbox("dev1", unread_only=True)) == 2
        db.mark_inbox_read("dev1")
        assert len(db.get_inbox("dev1", unread_only=True)) == 0
        assert len(db.get_inbox("dev1", unread_only=False)) == 2

    # ----- Board view -----

    def test_get_board(self, db):
        db.create_item("story", {"title": "S1", "status": "todo"})
        db.create_item("story", {"title": "S2", "status": "in_progress"})
        db.create_item("story", {"title": "S3", "status": "todo"})
        board = db.get_board()
        assert len(board.get("todo", [])) == 2
        assert len(board.get("in_progress", [])) == 1

    # ----- Events -----

    def test_log_event(self, db):
        db.log_event("test_event", agent_id="dev1", data={"key": "value"})
        events = db.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"


# =============================================================================
# Events
# =============================================================================

class TestEvents:
    @pytest.fixture
    def processor(self, tmp_path):
        config = BoardConfig.load()
        db = Database(str(tmp_path / "test.db"), config)
        db.connect()
        yield EventProcessor(db, config)
        db.close()

    def test_fire_logs_event(self, processor):
        processor.fire("item_created", {"item_id": "STORY-001", "title": "Test"})
        events = processor.db.get_events()
        assert len(events) == 1

    def test_fire_sends_inbox_notification(self, processor):
        processor.fire("item_created", {"item_id": "STORY-001", "title": "Test"})
        # Default config sends item_created to po
        inbox = processor.db.get_inbox("po")
        assert len(inbox) >= 1
        assert "STORY-001" in inbox[0]["message"]


# =============================================================================
# API (integration test with real HTTP server)
# =============================================================================

class TestAPI:
    @pytest.fixture
    def server_url(self, tmp_path):
        config = BoardConfig.load()
        config.port = 0  # Let OS pick a free port
        config.db_path = str(tmp_path / "test.db")
        db = Database(config.db_path, config)
        db.connect()
        server = create_server(config, db)

        # Get the actual port
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)  # Wait for server to be ready

        yield url

        server.shutdown()
        db.close()

    def _api(self, url, method, path, body=None, agent="human"):
        data = json.dumps(body).encode() if body else None
        req = Request(
            f"{url}/api{path}",
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-Agent-Id": agent,
            },
        )
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())

    def test_create_and_get_item(self, server_url):
        item = self._api(server_url, "POST", "/items", {"type": "story", "title": "Test"})
        assert item["id"] == "STORY-001"

        fetched = self._api(server_url, "GET", f"/items/{item['id']}")
        assert fetched["title"] == "Test"

    def test_list_items(self, server_url):
        self._api(server_url, "POST", "/items", {"type": "story", "title": "S1"})
        self._api(server_url, "POST", "/items", {"type": "story", "title": "S2"})
        items = self._api(server_url, "GET", "/items")
        assert len(items) == 2

    def test_update_item(self, server_url):
        item = self._api(server_url, "POST", "/items", {"type": "story", "title": "Old"})
        updated = self._api(server_url, "PATCH", f"/items/{item['id']}", {"status": "in_progress"})
        assert updated["status"] == "in_progress"

    def test_add_comment(self, server_url):
        item = self._api(server_url, "POST", "/items", {"type": "story", "title": "S"})
        comment = self._api(server_url, "POST", f"/items/{item['id']}/comments", {"body": "Nice!"}, agent="dev1")
        assert comment["author"] == "dev1"
        assert comment["body"] == "Nice!"

    def test_inbox(self, server_url):
        self._api(server_url, "POST", "/inbox/dev1", {"message": "Hello!"}, agent="pm")
        messages = self._api(server_url, "GET", "/inbox/dev1")
        assert len(messages) >= 1  # May include event-generated messages

    def test_board_view(self, server_url):
        self._api(server_url, "POST", "/items", {"type": "story", "title": "S1", "status": "todo"})
        self._api(server_url, "POST", "/items", {"type": "story", "title": "S2", "status": "done"})
        board = self._api(server_url, "GET", "/board")
        assert "todo" in board
        assert "done" in board

    def test_schema_endpoint(self, server_url):
        schema = self._api(server_url, "GET", "/schema")
        assert "story" in schema
        assert "title" in schema["story"]["fields"]

    def test_agents_endpoint(self, server_url):
        agents = self._api(server_url, "GET", "/agents")
        ids = [a["id"] for a in agents]
        assert "po" in ids
        assert "dev1" in ids

    def test_agent_identification(self, server_url):
        item = self._api(server_url, "POST", "/items", {"type": "story", "title": "T"}, agent="po")
        assert item["created_by"] == "po"

    def test_validation_error(self, server_url):
        try:
            self._api(server_url, "POST", "/items", {"type": "story"})  # missing title
            assert False, "Should have raised"
        except HTTPError as e:
            assert e.code == 400
