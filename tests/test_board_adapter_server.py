"""Tests for BoardServerAdapter — board server as agent backend.

Spins up a real board server, seeds it with test data, and verifies
the adapter produces the same AgentContext structure as the
MarkdownBoardAdapter.
"""

import threading
import time
import pytest
from pathlib import Path

from boardserver.config import BoardConfig
from boardserver.db import Database
from boardserver.api import create_server

from opensepia.board_adapter import BoardAdapter, AgentContext
from opensepia.board_adapter_server import BoardServerAdapter
from opensepia.agents.parser import ParsedFile


def _minimal_agents_config() -> dict:
    return {
        "agents": {
            "po": {"name": "Product Owner", "color": "P", "system_prompt": "You are PO."},
            "pm": {"name": "Project Manager", "color": "M", "system_prompt": "You are PM."},
            "dev1": {"name": "Developer 1", "color": "D", "system_prompt": "You are Dev1."},
            "dev2": {"name": "Developer 2", "color": "D", "system_prompt": "You are Dev2."},
            "devops": {"name": "DevOps", "color": "O", "system_prompt": "You are DevOps."},
            "tester": {"name": "Tester", "color": "T", "system_prompt": "You are Tester."},
        },
        "global": {
            "standup_instruction": "Write a standup.",
            "communication_rules": "Use inbox files.",
        },
    }


def _minimal_project_config() -> dict:
    return {
        "sprint": {"current_sprint": 1, "current_cycle": 3},
        "project": {"name": "Test Project", "description": "A test."},
    }


@pytest.fixture
def adapter_env(tmp_path):
    """Start a board server, seed it, and return the adapter."""
    config = BoardConfig.load()
    config.port = 0
    config.db_path = str(tmp_path / "test.db")
    db = Database(config.db_path, config)
    db.connect()
    server = create_server(config, db)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    # Seed test data
    db.create_item("story", {
        "title": "User login",
        "status": "todo",
        "priority": "high",
        "assigned": "dev1",
        "sprint": 1,
    }, created_by="po")

    db.create_item("story", {
        "title": "API scaffold",
        "status": "in_progress",
        "priority": "high",
        "assigned": "dev1",
        "sprint": 1,
    }, created_by="po")

    db.create_item("story", {
        "title": "Setup done",
        "status": "done",
        "priority": "medium",
        "sprint": 1,
    }, created_by="po")

    db.create_item("story", {
        "title": "Dashboard",
        "status": "todo",
        "priority": "medium",
        "sprint": 1,
    }, created_by="po")

    # Seed inbox
    db.send_inbox("dev1", "Please work on STORY-002.", from_agent="pm")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    adapter = BoardServerAdapter(
        server_url=url,
        workspace_dir=workspace,
        project_dir=tmp_path,
    )

    yield adapter, db, url

    server.shutdown()
    db.close()


# =============================================================================
# get_agent_context
# =============================================================================

class TestGetAgentContext:
    def test_returns_agent_context(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert isinstance(ctx, AgentContext)

    def test_sprint_md_contains_stories(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "STORY-001" in ctx.sprint_md
        assert "User login" in ctx.sprint_md

    def test_sprint_md_has_status_sections(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "TODO" in ctx.sprint_md
        assert "IN PROGRESS" in ctx.sprint_md or "IN_PROGRESS" in ctx.sprint_md
        assert "DONE" in ctx.sprint_md

    def test_backlog_contains_all_stories(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "STORY-001" in ctx.backlog_md
        assert "STORY-004" in ctx.backlog_md

    def test_backlog_has_priorities(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "HIGH" in ctx.backlog_md or "high" in ctx.backlog_md

    def test_inbox_has_messages(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "STORY-002" in ctx.inbox

    def test_empty_inbox(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("po", _minimal_agents_config(), _minimal_project_config())
        # PO inbox may have system event messages, but no agent messages
        # Just check it doesn't crash
        assert isinstance(ctx.inbox, str)

    def test_workspace_tree(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "main.py" in ctx.workspace_tree

    def test_project_description(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "Test Project" in ctx.project_description

    def test_sprint_and_cycle(self, adapter_env):
        adapter, _, _ = adapter_env
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert ctx.sprint_num == 1
        assert ctx.cycle_num == 3


# =============================================================================
# apply_agent_output
# =============================================================================

class TestApplyAgentOutput:
    def test_write_workspace_file(self, adapter_env):
        adapter, _, _ = adapter_env
        files = [ParsedFile(path="workspace/src/new.py", content="print('new')\n", action="overwrite")]
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        assert written >= 1

    def test_create_story_from_backlog_write(self, adapter_env):
        adapter, db, _ = adapter_env
        # Agent writes a new story to backlog
        backlog = (
            "# Backlog\n\n## HIGH\n"
            "### STORY-005: New feature\n"
            "**Priority**: HIGH\n**Status**: TODO\n"
        )
        files = [ParsedFile(path="board/backlog.md", content=backlog, action="overwrite")]
        adapter.apply_agent_output("po", files, _minimal_agents_config())

        # The adapter should have created the new story in the board server
        items = db.list_items()
        titles = [i.get("title", "") for i in items]
        assert any("New feature" in t for t in titles)

    def test_update_status_from_sprint_write(self, adapter_env):
        adapter, db, _ = adapter_env
        # Agent writes sprint with STORY-001 moved to IN_PROGRESS
        sprint = "# Sprint 1\n\n## IN PROGRESS\n- [ ] STORY-001: User login\n"
        files = [ParsedFile(path="board/sprint.md", content=sprint, action="overwrite")]
        adapter.apply_agent_output("pm", files, _minimal_agents_config())

        item = db.get_item("STORY-001")
        assert item is not None
        assert item.get("status") == "in_progress"

    def test_inbox_message_sent(self, adapter_env):
        adapter, db, _ = adapter_env
        files = [ParsedFile(
            path="board/inbox/dev1.md",
            content="## Message from PM\nWork on STORY-001 please.",
            action="append",
        )]
        adapter.apply_agent_output("pm", files, _minimal_agents_config())

        inbox = db.get_inbox("dev1")
        assert any("STORY-001" in m["message"] for m in inbox)

    def test_path_traversal_blocked(self, adapter_env):
        adapter, _, _ = adapter_env
        files = [ParsedFile(path="../../etc/passwd", content="hacked", action="overwrite")]
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        assert written == 0


# =============================================================================
# Inbox
# =============================================================================

class TestInbox:
    def test_get_inbox(self, adapter_env):
        adapter, _, _ = adapter_env
        content = adapter.get_inbox("dev1")
        assert "STORY-002" in content

    def test_archive_inbox(self, adapter_env):
        adapter, _, _ = adapter_env
        adapter.archive_inbox("dev1")
        content = adapter.get_inbox("dev1")
        assert content.strip() == ""


# =============================================================================
# Standup
# =============================================================================

class TestStandup:
    def test_init_standup(self, adapter_env):
        adapter, _, _ = adapter_env
        adapter.init_standup(1, 4)
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        # Standup should mention the cycle
        assert isinstance(ctx.standup, str)


# =============================================================================
# Board readiness
# =============================================================================

class TestBoardReady:
    def test_ensure_board_ready(self, adapter_env):
        adapter, _, _ = adapter_env
        adapter.ensure_board_ready()  # Should not crash
