"""
Tests for Plane.so integration — adapter, provider, client, and mappings.

Uses a mock Plane server (no external API calls).
"""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from tests.mock_plane_server import start_mock_plane_server, PlaneStore

from opensepia.integrations.providers.plane_client import PlaneClient, PlaneConfig, PlaneCache, RateLimiter
from opensepia.integrations.providers.plane_mapping import (
    map_plane_state_to_status,
    find_state_id_for_status,
    map_plane_priority,
    map_opensepia_priority,
    extract_story_id_from_title,
    build_title,
    strip_title_prefix,
)
from opensepia.integrations.providers.plane import PlaneProvider
from opensepia.board_adapter_plane import PlaneBoardAdapter
from opensepia.agents.parser import ParsedFile


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def plane_env(tmp_path):
    """Start mock Plane server and return configured adapter + provider."""
    store = PlaneStore()
    server, url, store = start_mock_plane_server(store)

    config = PlaneConfig(
        api_key="test_key",
        workspace_slug="test-ws",
        project_id="test-proj",
        base_url=url,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    project_dir = tmp_path
    (project_dir / "board").mkdir(exist_ok=True)
    (project_dir / "logs" / "runs").mkdir(parents=True, exist_ok=True)

    provider = PlaneProvider(config)
    adapter = PlaneBoardAdapter(workspace, project_dir, config)

    agents_config = {
        "agents": {
            "po": {"name": "Product Owner", "color": "P", "system_prompt": "PO."},
            "dev1": {"name": "Developer 1", "color": "D", "system_prompt": "Dev."},
        },
        "global": {"standup_instruction": "", "communication_rules": ""},
        "execution": {"timeout": 30, "max_retries": 0, "retry_delay": 5},
    }
    project_config = {
        "sprint": {"current_sprint": 1, "current_cycle": 1, "cycles_per_sprint": 10},
        "project": {"name": "Test Project", "description": "A test project"},
    }

    yield {
        "server": server,
        "url": url,
        "store": store,
        "config": config,
        "provider": provider,
        "adapter": adapter,
        "agents_config": agents_config,
        "project_config": project_config,
        "workspace": workspace,
        "project_dir": project_dir,
    }

    server.shutdown()


# ============================================================================
# Mapping tests
# ============================================================================

class TestPlaneMapping:
    def test_state_group_to_status_unstarted(self):
        assert map_plane_state_to_status("Todo", "unstarted") == "todo"

    def test_state_group_to_status_started(self):
        assert map_plane_state_to_status("In Progress", "started") == "in_progress"

    def test_state_name_override_review(self):
        assert map_plane_state_to_status("Review", "started") == "review"

    def test_state_name_override_testing(self):
        assert map_plane_state_to_status("Testing", "started") == "testing"

    def test_state_name_override_blocked(self):
        assert map_plane_state_to_status("Blocked", "started") == "blocked"

    def test_state_group_completed(self):
        assert map_plane_state_to_status("Shipped", "completed") == "done"

    def test_state_group_cancelled(self):
        assert map_plane_state_to_status("Wont Fix", "cancelled") == "done"

    def test_priority_urgent_to_critical(self):
        assert map_plane_priority(1) == "critical"

    def test_priority_high(self):
        assert map_plane_priority(2) == "high"

    def test_priority_medium(self):
        assert map_plane_priority(3) == "medium"

    def test_priority_low(self):
        assert map_plane_priority(4) == "low"

    def test_priority_none_to_low(self):
        assert map_plane_priority(0) == "low"

    def test_priority_null_to_medium(self):
        assert map_plane_priority(None) == "medium"

    def test_reverse_priority(self):
        assert map_opensepia_priority("critical") == "urgent"
        assert map_opensepia_priority("high") == "high"
        assert map_opensepia_priority("medium") == "medium"
        assert map_opensepia_priority("low") == "low"

    def test_plane_string_priority(self):
        assert map_plane_priority("urgent") == "critical"
        assert map_plane_priority("high") == "high"
        assert map_plane_priority("medium") == "medium"
        assert map_plane_priority("low") == "low"
        assert map_plane_priority("none") == "low"

    def test_extract_story_id(self):
        assert extract_story_id_from_title("[STORY-001] Login page") == "STORY-001"
        assert extract_story_id_from_title("[BUG-042] Fix crash") == "BUG-042"
        assert extract_story_id_from_title("No prefix here") is None

    def test_build_title(self):
        assert build_title("STORY-001", "Login") == "[STORY-001] Login"
        assert "[BUG-001]" in build_title("BUG-001", "Fix crash")

    def test_build_title_strips_existing_prefix(self):
        result = build_title("STORY-001", "[STORY-001] Login")
        assert result.count("[STORY-001]") == 1

    def test_strip_title_prefix(self):
        assert strip_title_prefix("[STORY-001] Login page") == "Login page"
        assert strip_title_prefix("No prefix") == "No prefix"

    def test_find_state_id_by_name(self):
        states = [
            {"id": "a", "name": "Todo", "group": "unstarted"},
            {"id": "b", "name": "Review", "group": "started"},
        ]
        assert find_state_id_for_status(states, "review") == "b"

    def test_find_state_id_by_group(self):
        states = [
            {"id": "a", "name": "Backlog", "group": "unstarted"},
        ]
        assert find_state_id_for_status(states, "todo") == "a"


# ============================================================================
# Cache tests
# ============================================================================

class TestPlaneCache:
    def test_set_and_get(self):
        cache = PlaneCache()
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_miss(self):
        cache = PlaneCache()
        assert cache.get("missing") is None

    def test_invalidate(self):
        cache = PlaneCache()
        cache.set("key", "value")
        cache.invalidate("key")
        assert cache.get("key") is None

    def test_invalidate_prefix(self):
        cache = PlaneCache()
        cache.set("work_items:all", [1])
        cache.set("work_items:cycle:x", [2])
        cache.set("states", [3])
        cache.invalidate_prefix("work_items")
        assert cache.get("work_items:all") is None
        assert cache.get("work_items:cycle:x") is None
        assert cache.get("states") is not None

    def test_clear(self):
        cache = PlaneCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


# ============================================================================
# Rate limiter tests
# ============================================================================

class TestRateLimiter:
    def test_no_wait_when_under_limit(self):
        rl = RateLimiter(max_requests=10, window=60)
        start = time.time()
        for _ in range(5):
            rl.wait_if_needed()
        elapsed = time.time() - start
        assert elapsed < 0.5  # Should be near-instant


# ============================================================================
# PlaneClient tests
# ============================================================================

class TestPlaneClient:
    def test_api_get_states(self, plane_env):
        client = plane_env["provider"]._client
        result = client.api("GET", "/states/")
        assert isinstance(result, dict)
        assert "results" in result
        assert len(result["results"]) == 6  # 6 seeded states

    def test_api_get_work_items(self, plane_env):
        client = plane_env["provider"]._client
        result = client.api("GET", "/work-items/")
        assert isinstance(result, dict)
        assert len(result["results"]) == 5  # 5 seeded work items

    def test_api_post_work_item(self, plane_env):
        client = plane_env["provider"]._client
        result = client.api("POST", "/work-items/", data={
            "name": "[STORY-999] Test item",
            "priority": 3,
        })
        assert isinstance(result, dict)
        assert "id" in result

    def test_get_cached(self, plane_env):
        client = plane_env["provider"]._client
        # First call fetches
        r1 = client.get_cached("states", "/states/")
        # Second call returns cached
        r2 = client.get_cached("states", "/states/")
        assert r1 == r2

    def test_paginate(self, plane_env):
        client = plane_env["provider"]._client
        result = client.paginate("/work-items/")
        assert isinstance(result, list)
        assert len(result) == 5


# ============================================================================
# PlaneProvider tests
# ============================================================================

class TestPlaneProvider:
    def test_name(self, plane_env):
        assert plane_env["provider"].name == "plane"

    def test_enabled(self, plane_env):
        assert plane_env["provider"].enabled is True

    def test_get_states(self, plane_env):
        states = plane_env["provider"]._get_states()
        assert len(states) == 6

    def test_get_labels(self, plane_env):
        labels = plane_env["provider"]._get_labels()
        assert len(labels) >= 10

    def test_get_board_state(self, plane_env):
        board = plane_env["provider"].get_board_state()
        assert "todo" in board
        assert "in_progress" in board
        assert "done" in board
        # STORY-001 and BUG-001 should be in todo
        todo_ids = [i["id"] for i in board["todo"]]
        assert "STORY-001" in todo_ids
        assert "BUG-001" in todo_ids

    def test_find_issue_by_id(self, plane_env):
        uuid = plane_env["provider"].find_issue_by_id("STORY-001")
        assert uuid is not None

    def test_find_issue_by_id_not_found(self, plane_env):
        uuid = plane_env["provider"].find_issue_by_id("STORY-999")
        assert uuid is None

    def test_create_work_item(self, plane_env):
        result = plane_env["provider"].create_work_item(
            "STORY-010", "New feature", status="todo", priority="high",
        )
        assert "id" in result or "error" not in result

    def test_update_work_item(self, plane_env):
        uuid = plane_env["provider"].find_issue_by_id("STORY-001")
        assert uuid is not None
        result = plane_env["provider"].update_work_item(uuid, {"priority": 1})
        assert isinstance(result, dict)

    def test_comment_on_issue(self, plane_env):
        uuid = plane_env["provider"].find_issue_by_id("STORY-001")
        result = plane_env["provider"].comment_on_issue(uuid, "dev1", "LGTM!")
        assert isinstance(result, dict)
        assert "error" not in result

    def test_get_issue_comments(self, plane_env):
        uuid = plane_env["provider"].find_issue_by_id("STORY-001")
        # Post a comment first
        plane_env["provider"].comment_on_issue(uuid, "dev1", "Test comment")
        comments = plane_env["provider"].get_issue_comments(uuid)
        assert len(comments) >= 1
        assert comments[-1]["body"] != ""

    def test_list_issues_opened(self, plane_env):
        issues = plane_env["provider"].list_issues(state="opened")
        # STORY-004 is Done, should be excluded
        story_ids = [i.get("story_id") for i in issues]
        assert "STORY-004" not in story_ids
        assert "STORY-001" in story_ids

    def test_list_issues_closed(self, plane_env):
        issues = plane_env["provider"].list_issues(state="closed")
        story_ids = [i.get("story_id") for i in issues]
        assert "STORY-004" in story_ids

    def test_close_issue(self, plane_env):
        uuid = plane_env["provider"].find_issue_by_id("STORY-001")
        result = plane_env["provider"].close_issue(uuid)
        assert isinstance(result, dict)

    def test_reopen_issue(self, plane_env):
        uuid = plane_env["provider"].find_issue_by_id("STORY-001")
        result = plane_env["provider"].reopen_issue(uuid)
        assert isinstance(result, dict)

    def test_get_or_create_cycle(self, plane_env):
        # Sprint 1 already exists
        cid = plane_env["provider"].get_or_create_cycle(1)
        assert cid is not None

    def test_get_or_create_cycle_new(self, plane_env):
        cid = plane_env["provider"].get_or_create_cycle(99)
        assert cid is not None

    def test_page_crud(self, plane_env):
        # Create
        plane_env["provider"].create_page("test-page", "Hello")
        # Read
        content = plane_env["provider"].get_page_content("test-page")
        assert "Hello" in content
        # Update
        plane_env["provider"].update_page("test-page", "Updated")
        content = plane_env["provider"].get_page_content("test-page")
        assert "Updated" in content

    def test_get_board_summary_md(self, plane_env):
        md = plane_env["provider"].get_board_summary_md()
        assert "Board Summary" in md

    def test_mr_methods_return_not_supported(self, plane_env):
        p = plane_env["provider"]
        assert "error" in p.create_mr("a", "b", "c")
        assert p.list_mrs() == []
        assert "error" in p.get_mr("x")
        assert "error" in p.approve_mr("x")
        assert "error" in p.merge_mr("x")
        assert "error" in p.close_mr("x")
        assert p.get_open_mrs_md() == ""

    def test_clear_cache(self, plane_env):
        p = plane_env["provider"]
        # Populate cache
        p._get_states()
        p.clear_cache()
        assert p._client.cache.get("states") is None


# ============================================================================
# PlaneBoardAdapter tests
# ============================================================================

class TestPlaneBoardAdapter:
    def test_get_agent_context(self, plane_env):
        ctx = plane_env["adapter"].get_agent_context(
            "po", plane_env["agents_config"], plane_env["project_config"],
        )
        assert ctx.sprint_num == 1
        assert ctx.cycle_num == 1
        assert "Sprint 1" in ctx.sprint_md
        assert "STORY-001" in ctx.sprint_md
        assert "STORY-002" in ctx.sprint_md

    def test_sprint_md_format(self, plane_env):
        ctx = plane_env["adapter"].get_agent_context(
            "po", plane_env["agents_config"], plane_env["project_config"],
        )
        # Check status sections exist
        assert "## TODO" in ctx.sprint_md
        assert "## IN PROGRESS" in ctx.sprint_md
        assert "## REVIEW" in ctx.sprint_md
        assert "## DONE" in ctx.sprint_md

    def test_backlog_md_format(self, plane_env):
        ctx = plane_env["adapter"].get_agent_context(
            "po", plane_env["agents_config"], plane_env["project_config"],
        )
        assert "# Backlog" in ctx.backlog_md

    def test_project_description_from_page(self, plane_env):
        ctx = plane_env["adapter"].get_agent_context(
            "po", plane_env["agents_config"], plane_env["project_config"],
        )
        assert "Test Project" in ctx.project_description

    def test_workspace_tree(self, plane_env):
        # Create a file in workspace
        (plane_env["workspace"] / "src" / "app.py").write_text("print('hi')")
        ctx = plane_env["adapter"].get_agent_context(
            "po", plane_env["agents_config"], plane_env["project_config"],
        )
        assert "app.py" in ctx.workspace_tree

    def test_apply_agent_output_workspace_file(self, plane_env):
        files = [
            ParsedFile(
                path="workspace/src/main.py",
                content="print('hello')",
                action="overwrite",
            ),
        ]
        written = plane_env["adapter"].apply_agent_output("dev1", files, plane_env["agents_config"])
        assert written == 1
        assert (plane_env["workspace"] / "src" / "main.py").read_text() == "print('hello')"

    def test_apply_agent_output_sprint_update(self, plane_env):
        sprint_md = """# Sprint 1

## TODO
- [ ] STORY-001: User login page (dev1)

## IN PROGRESS
- [ ] STORY-002: Dashboard (dev2)
- [ ] STORY-003: API endpoints (dev1)

## DONE
- [x] STORY-004: CI/CD pipeline (devops)
"""
        files = [ParsedFile(path="board/sprint.md", content=sprint_md, action="overwrite")]
        written = plane_env["adapter"].apply_agent_output("po", files, plane_env["agents_config"])
        assert written == 1

    def test_apply_agent_output_inbox_message(self, plane_env):
        # Ensure inbox page exists
        plane_env["provider"].create_page("inbox-dev1", "")

        files = [ParsedFile(
            path="board/inbox/dev1.md",
            content="## Message from PO\nPlease start STORY-001.",
            action="append",
        )]
        written = plane_env["adapter"].apply_agent_output("po", files, plane_env["agents_config"])
        assert written == 1

        # Check the message was written to the page
        content = plane_env["provider"].get_page_content("inbox-dev1")
        assert "STORY-001" in content

    def test_apply_agent_output_standup(self, plane_env):
        files = [ParsedFile(
            path="board/standup.md",
            content="## PO\n- Done: reviewed sprint",
            action="append",
        )]
        written = plane_env["adapter"].apply_agent_output("po", files, plane_env["agents_config"])
        assert written == 1

    def test_apply_agent_output_architecture_page(self, plane_env):
        files = [ParsedFile(
            path="board/architecture.md",
            content="# Architecture\n\nNew architecture.",
            action="overwrite",
        )]
        written = plane_env["adapter"].apply_agent_output("dev1", files, plane_env["agents_config"])
        assert written == 1
        content = plane_env["provider"].get_page_content("architecture")
        assert "New architecture" in content

    def test_apply_agent_output_path_traversal_blocked(self, plane_env):
        files = [ParsedFile(
            path="workspace/../../../etc/passwd",
            content="evil",
            action="overwrite",
        )]
        written = plane_env["adapter"].apply_agent_output("dev1", files, plane_env["agents_config"])
        assert written == 0

    def test_init_standup(self, plane_env):
        plane_env["adapter"].init_standup(1, 2)
        text = plane_env["adapter"].get_standup_text()
        assert "Sprint 1" in text
        assert "Cycle 2" in text

    def test_ensure_board_ready(self, plane_env):
        plane_env["adapter"].ensure_board_ready(plane_env["agents_config"])
        # Should have created inbox pages for po and dev1
        assert plane_env["provider"].get_page("inbox-po") is not None
        assert plane_env["provider"].get_page("inbox-dev1") is not None

    def test_get_sprint_text(self, plane_env):
        text = plane_env["adapter"].get_sprint_text()
        assert "STORY-001" in text

    def test_get_backlog_text(self, plane_env):
        text = plane_env["adapter"].get_backlog_text()
        assert "Backlog" in text

    def test_get_active_story_ids(self, plane_env):
        ids = plane_env["adapter"].get_active_story_ids()
        assert "STORY-001" in ids
        assert "STORY-002" in ids
        # STORY-004 is done, should not be active
        assert "STORY-004" not in ids

    def test_get_board_summary(self, plane_env):
        summary = plane_env["adapter"].get_board_summary()
        assert "todo" in summary
        assert "done" in summary
        assert summary["todo"] >= 1

    def test_check_board_health(self, plane_env):
        health = plane_env["adapter"].check_board_health()
        assert health["api_reachable"] is True
        assert health["states_configured"] is True
        assert health["has_work_items"] is True

    def test_create_snapshot(self, plane_env):
        count = plane_env["adapter"].create_snapshot()
        assert count >= 1

    def test_send_inbox_message(self, plane_env):
        plane_env["provider"].create_page("inbox-dev1", "")
        plane_env["adapter"].send_inbox_message("dev1", "PM", "Start working!")
        content = plane_env["provider"].get_page_content("inbox-dev1")
        assert "Start working!" in content
        assert "PM" in content

    def test_get_inbox(self, plane_env):
        plane_env["provider"].create_page("inbox-po", "Hello PO")
        text = plane_env["adapter"].get_inbox("po")
        assert "Hello PO" in text

    def test_archive_inbox(self, plane_env):
        plane_env["provider"].create_page("inbox-po", "Old messages")
        plane_env["adapter"].archive_inbox("po")
        # Inbox should be cleared
        content = plane_env["provider"].get_page_content("inbox-po")
        assert content.strip() == ""
        # Archive should have content
        archive = plane_env["provider"].get_page_content("archive-po")
        assert "Old messages" in archive

    def test_get_sprint_number(self, plane_env):
        num = plane_env["adapter"].get_sprint_number()
        assert num == 1  # "Sprint 1" seeded

    def test_backlog_update_creates_new_item(self, plane_env):
        backlog_md = """# Backlog

## HIGH
### STORY-050: Brand new feature
**Priority**: HIGH
**Status**: TODO
**Assigned**: dev1
"""
        files = [ParsedFile(path="board/backlog.md", content=backlog_md, action="overwrite")]
        plane_env["adapter"].apply_agent_output("po", files, plane_env["agents_config"])

        # Should have created STORY-050
        uuid = plane_env["provider"].find_issue_by_id("STORY-050")
        assert uuid is not None


# ============================================================================
# Factory integration tests
# ============================================================================

class TestAdapterFactory:
    def test_plane_adapter_selected_when_env_set(self, plane_env):
        # Clear BOARD_SERVER_URL so Plane takes priority
        env_overrides = {
            "PLANE_API_KEY": "test",
            "PLANE_WORKSPACE_SLUG": "test-ws",
            "BOARD_SERVER_URL": "",
        }
        with patch.dict(os.environ, env_overrides):
            from opensepia.board_adapter import create_board_adapter
            adapter = create_board_adapter(
                Path("/tmp/board"), Path("/tmp/workspace"), Path("/tmp/project"),
            )
            assert isinstance(adapter, PlaneBoardAdapter)

    def test_markdown_adapter_when_no_plane_env(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PLANE_") and k != "BOARD_SERVER_URL"}
        with patch.dict(os.environ, env, clear=True):
            from opensepia.board_adapter import create_board_adapter
            from opensepia.board_adapter_markdown import MarkdownBoardAdapter
            adapter = create_board_adapter(
                Path("/tmp/board"), Path("/tmp/workspace"), Path("/tmp/project"),
            )
            assert isinstance(adapter, MarkdownBoardAdapter)


# ============================================================================
# Provider detection tests
# ============================================================================

class TestPlaneWorkspaceProject:
    def test_list_workspaces(self, plane_env):
        workspaces = plane_env["provider"].list_workspaces()
        assert len(workspaces) >= 1
        assert workspaces[0]["slug"] == "test-ws"

    def test_find_workspace(self, plane_env):
        ws = plane_env["provider"].find_workspace("test-ws")
        assert ws is not None
        assert ws["slug"] == "test-ws"

    def test_find_workspace_not_found(self, plane_env):
        ws = plane_env["provider"].find_workspace("nonexistent")
        assert ws is None

    def test_create_workspace(self, plane_env):
        result = plane_env["provider"].create_workspace("New WS", "new-ws")
        assert "id" in result
        assert result["slug"] == "new-ws"

    def test_list_projects(self, plane_env):
        projects = plane_env["provider"].list_projects()
        assert len(projects) >= 1

    def test_find_project(self, plane_env):
        proj = plane_env["provider"].find_project("Test Project")
        assert proj is not None

    def test_find_project_not_found(self, plane_env):
        proj = plane_env["provider"].find_project("Nonexistent")
        assert proj is None

    def test_create_project(self, plane_env):
        result = plane_env["provider"].create_project("New Project", "A new project")
        assert "id" in result

    def test_setup_plane_with_existing_workspace(self, plane_env, tmp_path):
        """Test _setup_plane when workspace already exists."""
        from opensepia.commands.project import _setup_plane

        tool_dir = tmp_path / "tool"
        (tool_dir / "config").mkdir(parents=True)
        (tool_dir / "project" / "workspace").mkdir(parents=True)
        (tool_dir / "project" / "board").mkdir(parents=True)

        with patch.dict(os.environ, {
            "PLANE_API_KEY": "test",
            "PLANE_BASE_URL": plane_env["url"],
            "PLANE_WORKSPACE_SLUG": "test-ws",
            "PLANE_PROJECT_ID": "",
        }):
            _setup_plane("My App", "A cool app", tool_dir, ["po", "dev1"])

        # Should have saved config to .env
        env_content = (tool_dir / "config" / ".env").read_text()
        assert "PLANE_WORKSPACE_SLUG=test-ws" in env_content
        assert "PLANE_PROJECT_ID=" in env_content

    def test_update_env_file(self, tmp_path):
        from opensepia.commands.project import _update_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")

        _update_env_file(env_file, {"FOO": "updated", "NEW_KEY": "new_val"})
        content = env_file.read_text()
        assert "FOO=updated" in content
        assert "BAZ=qux" in content
        assert "NEW_KEY=new_val" in content

    def test_update_env_file_creates_new(self, tmp_path):
        from opensepia.commands.project import _update_env_file

        env_file = tmp_path / "config" / ".env"
        _update_env_file(env_file, {"KEY": "val"})
        assert env_file.exists()
        assert "KEY=val" in env_file.read_text()


class TestProviderDetection:
    def test_plane_provider_detected(self, plane_env):
        # Clear BOARD_SERVER_URL so Plane provider is detected
        env_overrides = {
            "PLANE_API_KEY": "test",
            "PLANE_WORKSPACE_SLUG": "test-ws",
            "PLANE_PROJECT_ID": "test-proj",
            "PLANE_BASE_URL": plane_env["url"],
            "BOARD_SERVER_URL": "",
        }
        with patch.dict(os.environ, env_overrides):
            from opensepia.integrations.providers import detect_provider
            provider = detect_provider()
            assert provider is not None
            assert provider.name == "plane"
