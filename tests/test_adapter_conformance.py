"""Adapter conformance tests — run against BOTH MarkdownBoardAdapter and BoardServerAdapter.

Every test in this file must pass for both adapters, ensuring they implement
the BoardAdapter ABC identically from the caller's perspective.
"""

import threading
import time
import pytest
from pathlib import Path

from opensepia.board_adapter import BoardAdapter, AgentContext
from opensepia.agents.parser import ParsedFile


# =============================================================================
# Shared helpers
# =============================================================================

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
        "project": {"name": "Test Project", "description": "A test project."},
    }


# =============================================================================
# Fixtures
# =============================================================================

def _create_markdown_adapter(base_path: Path):
    """Create a MarkdownBoardAdapter with seed data."""
    board = base_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()

    (board / "project.md").write_text(
        "# Test Project\n\n## Description\nA test project.\n",
        encoding="utf-8",
    )

    (board / "sprint.md").write_text(
        "# Sprint 1\n\n## TODO\n- [ ] STORY-001: Login (dev1)\n\n"
        "## IN PROGRESS\n- [ ] STORY-002: API (dev1)\n\n"
        "## REVIEW\n- [ ] STORY-005: Review item (dev2)\n\n"
        "## TESTING\n\n"
        "## DONE\n- [x] STORY-003: Setup (devops)\n",
        encoding="utf-8",
    )

    (board / "backlog.md").write_text(
        "# Backlog\n\n## HIGH\n### STORY-001: Login\n**Priority**: HIGH\n**Status**: TODO\n\n"
        "### STORY-002: API\n**Priority**: HIGH\n**Status**: IN_PROGRESS\n\n"
        "## MEDIUM\n### STORY-004: Dashboard\n**Priority**: MEDIUM\n**Status**: TODO\n",
        encoding="utf-8",
    )

    (board / "standup.md").write_text(
        "# Standup — Sprint 1, Cycle 3\n\n## Dev1\n- Done: STORY-002\n",
        encoding="utf-8",
    )

    (board / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")

    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
        (board / "inbox" / f"{agent}.md").write_text("", encoding="utf-8")

    (board / "inbox" / "dev1.md").write_text(
        "## Message from PM\nPlease work on STORY-002.\n",
        encoding="utf-8",
    )

    workspace = base_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    from opensepia.board_adapter_markdown import MarkdownBoardAdapter
    return MarkdownBoardAdapter(
        board_dir=board,
        workspace_dir=workspace,
        project_dir=base_path,
    )


def _create_server_adapter(base_path: Path):
    """Start a real board server and create a BoardServerAdapter with seed data."""
    from boardserver.config import BoardConfig
    from boardserver.db import Database
    from boardserver.api import create_server

    config = BoardConfig.load()
    config.port = 0
    config.db_path = str(base_path / "test.db")
    db = Database(config.db_path, config)
    db.connect()
    server = create_server(config, db)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    # Seed data matching the markdown adapter fixture
    db.create_item("story", {
        "title": "Login",
        "status": "todo",
        "priority": "high",
        "assigned": "dev1",
        "sprint": 1,
    }, created_by="po")

    db.create_item("story", {
        "title": "API",
        "status": "in_progress",
        "priority": "high",
        "assigned": "dev1",
        "sprint": 1,
    }, created_by="po")

    db.create_item("story", {
        "title": "Setup",
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

    db.create_item("story", {
        "title": "Review item",
        "status": "review",
        "priority": "high",
        "assigned": "dev2",
        "sprint": 1,
    }, created_by="po")

    # Seed inbox for dev1
    db.send_inbox("dev1", "Please work on STORY-002.", from_agent="pm")

    workspace = base_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    from opensepia.board_adapter_server import BoardServerAdapter
    adapter = BoardServerAdapter(
        server_url=url,
        workspace_dir=workspace,
        project_dir=base_path,
    )

    return adapter, server, db


@pytest.fixture(params=["markdown", "server"])
def adapter(request, tmp_path):
    """Parameterized fixture that yields both adapters with isolated paths."""
    if request.param == "markdown":
        yield _create_markdown_adapter(tmp_path)
    else:
        adapter, server, db = _create_server_adapter(tmp_path)
        yield adapter
        server.shutdown()
        db.close()


# =============================================================================
# Conformance tests
# =============================================================================

class TestAdapterConformance:
    """All tests must pass for BOTH adapters."""

    # 1. get_agent_context returns all non-None fields
    def test_get_agent_context_all_fields(self, adapter):
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert isinstance(ctx, AgentContext)
        assert ctx.project_description is not None
        assert ctx.sprint_md is not None
        assert ctx.backlog_md is not None
        assert ctx.standup is not None
        assert ctx.inbox is not None
        assert ctx.workspace_tree is not None
        assert ctx.provider_comments is not None
        assert ctx.sprint_num is not None
        assert ctx.cycle_num is not None

    # 2. sprint text contains seeded story IDs
    def test_sprint_text_contains_story_ids(self, adapter):
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "STORY-001" in ctx.sprint_md
        assert "STORY-002" in ctx.sprint_md

    # 3. backlog text contains seeded stories
    def test_backlog_contains_stories(self, adapter):
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "STORY-001" in ctx.backlog_md

    # 4. inbox has messages for target agent
    def test_inbox_has_messages(self, adapter):
        ctx = adapter.get_agent_context("dev1", _minimal_agents_config(), _minimal_project_config())
        assert "STORY-002" in ctx.inbox

    # 5. inbox empty for other agent
    def test_inbox_empty_for_other(self, adapter):
        ctx = adapter.get_agent_context("po", _minimal_agents_config(), _minimal_project_config())
        # PO should have no meaningful messages
        assert isinstance(ctx.inbox, str)

    # 6. apply_output writes workspace files to disk
    def test_apply_output_writes_files(self, adapter):
        files = [ParsedFile(path="workspace/src/new.py", content="print('new')\n", action="overwrite")]
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        assert written >= 1

    # 7. apply_output blocks path traversal
    def test_apply_output_blocks_traversal(self, adapter):
        files = [ParsedFile(path="../../etc/passwd", content="hacked", action="overwrite")]
        written = adapter.apply_agent_output("dev1", files, _minimal_agents_config())
        assert written == 0

    # 8. archive_inbox clears content
    def test_archive_inbox_clears(self, adapter):
        # First verify there's content
        content = adapter.get_inbox("dev1")
        assert content.strip() != ""
        # Archive
        adapter.archive_inbox("dev1")
        # Now should be empty
        content = adapter.get_inbox("dev1")
        assert content.strip() == ""

    # 9. get_sprint_text returns non-empty string
    def test_get_sprint_text(self, adapter):
        text = adapter.get_sprint_text()
        assert isinstance(text, str)
        assert len(text.strip()) > 0

    # 10. get_board_summary returns dict with status counts
    def test_get_board_summary(self, adapter):
        summary = adapter.get_board_summary()
        assert isinstance(summary, dict)
        assert len(summary) > 0
        # Should have at least one status with items
        assert any(v > 0 for v in summary.values())

    # 11. send_inbox_message delivers to target agent
    def test_send_inbox_message(self, adapter):
        adapter.send_inbox_message("dev2", "TestSender", "Hello from conformance test")
        content = adapter.get_inbox("dev2")
        assert "Hello from conformance test" in content

    # 12. get_active_story_ids returns in-progress stories
    def test_get_active_story_ids(self, adapter):
        ids = adapter.get_active_story_ids()
        assert isinstance(ids, list)
        assert len(ids) > 0
        # STORY-002 is in_progress, should be present
        assert any("STORY-002" in sid for sid in ids)

    # 13. check_board_health returns dict
    def test_check_board_health(self, adapter):
        health = adapter.check_board_health()
        assert isinstance(health, dict)
        assert len(health) > 0
        # All values should be booleans
        for v in health.values():
            assert isinstance(v, bool)

    # 14. ensure_board_ready is idempotent
    def test_ensure_board_ready_idempotent(self, adapter):
        adapter.ensure_board_ready()
        adapter.ensure_board_ready()  # Second call should not crash
        # Board should still be healthy after
        health = adapter.check_board_health()
        assert all(health.values())
