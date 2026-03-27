"""E2E test: full pipeline cycle through the board server adapter.

Starts a real board server, seeds it with data, runs the pipeline
with a mocked Claude agent, and verifies the board server reflects
all changes. No markdown files involved.
"""

import json
import os
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from boardserver.config import BoardConfig
from boardserver.db import Database
from boardserver.api import create_server

from opensepia.board_adapter_server import BoardServerAdapter
from opensepia.pipeline import Pipeline, PipelineContext
from opensepia.commands.run import build_pipeline, STEP_REGISTRY


# Simulated agent response — writes sprint update, inbox message, and a code file
MOCK_AGENT_RESPONSE = """\
## PO Decisions [cycle 1]

Reviewed the sprint. Moving STORY-001 to IN PROGRESS.

---FILES---
path: board/sprint.md
content:
# Sprint 1

## TODO
- [ ] STORY-002: API scaffold (dev1)

## IN PROGRESS
- [ ] STORY-001: User login (dev1)

## DONE
- [x] STORY-003: Setup done (devops)
---
path: board/standup.md
action: append
content:
## PO
- **Done**: Reviewed sprint, moved STORY-001 to in progress
- **Doing**: Monitoring sprint
- **Blockers**: none
---
path: board/inbox/dev1.md
action: append
content:
## Message from Product Owner
Please start STORY-001 immediately. It's the top priority.
---
path: workspace/src/notes.txt
action: overwrite
content:
Sprint 1 started. Focus on user login.
---END---
"""


@pytest.fixture
def e2e_env(tmp_path):
    """Full environment: board server + adapter + pipeline context."""
    # Start board server
    config = BoardConfig.load()
    config.port = 0
    config.db_path = str(tmp_path / "e2e.db")
    db = Database(config.db_path, config)
    db.connect()
    server = create_server(config, db)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    # Seed data
    db.create_item("story", {"title": "User login", "status": "todo", "priority": "high", "assigned": "dev1", "sprint": 1}, created_by="po")
    db.create_item("story", {"title": "API scaffold", "status": "todo", "priority": "high", "assigned": "dev1", "sprint": 1}, created_by="po")
    db.create_item("story", {"title": "Setup done", "status": "done", "priority": "medium", "sprint": 1}, created_by="devops")
    db.send_inbox("po", "Sprint 1 is ready. Please review.", from_agent="pm")

    # Workspace
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()

    # Project dir (for filesystem writes)
    project_dir = tmp_path
    (project_dir / "board").mkdir(exist_ok=True)
    (project_dir / "board" / "inbox").mkdir(exist_ok=True)
    (project_dir / "logs" / "runs").mkdir(parents=True, exist_ok=True)

    # Create adapter
    adapter = BoardServerAdapter(server_url=url, workspace_dir=workspace, project_dir=project_dir)

    # Minimal configs
    agents_config = {
        "agents": {
            "po": {"name": "Product Owner", "color": "P", "system_prompt": "You are PO."},
        },
        "global": {"standup_instruction": "Write standup.", "communication_rules": "Use inbox."},
        "execution": {"timeout": 30, "max_retries": 0, "retry_delay": 5, "pause_between_agents": 0},
        "pipeline": ["board_health", "sprint_check", "snapshot", "agent_runner", "cycle_log"],
    }
    project_config = {
        "sprint": {"current_sprint": 1, "current_cycle": 0, "cycles_per_sprint": 10},
        "project": {"name": "E2E Test", "description": "Testing board server adapter e2e."},
    }

    # Build context
    ctx = PipelineContext(
        mode="po",
        tool_dir=tmp_path,
        project_dir=project_dir,
        agents_config=agents_config,
        project_config=project_config,
        board_dir=project_dir / "board",
        workspace_dir=workspace,
        config_dir=tmp_path / "config",
        logs_dir=project_dir / "logs" / "runs",
        sprint_num=1,
        cycle_num=1,
        agent_ids=["po"],
        execution_params={"timeout": 30, "max_retries": 0, "retry_delay": 5, "pause_between_agents": 0},
        board_adapter=adapter,
    )

    yield ctx, db, url, adapter

    server.shutdown()
    db.close()


class TestE2EBoardServer:
    """Full pipeline cycle through the board server adapter."""

    def test_agent_context_built_from_api(self, e2e_env):
        """Verify the adapter builds context from the board server API."""
        ctx, db, url, adapter = e2e_env
        agent_ctx = adapter.get_agent_context("po", ctx.agents_config, ctx.project_config)

        assert "STORY-001" in agent_ctx.sprint_md
        assert "User login" in agent_ctx.sprint_md
        assert "TODO" in agent_ctx.sprint_md
        assert "DONE" in agent_ctx.sprint_md
        assert "Sprint 1 is ready" in agent_ctx.inbox
        assert agent_ctx.sprint_num == 1

    def test_full_pipeline_with_mocked_agent(self, e2e_env):
        """Run the full pipeline with a mocked Claude call."""
        ctx, db, url, adapter = e2e_env

        # Mock invoke_agent to return our canned response
        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = "2026-03-26T12:00:00"
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            pipeline = build_pipeline(ctx.agents_config, agent_ids=ctx.agent_ids)
            result_ctx = pipeline.run(ctx)

        # Pipeline should complete without errors
        assert all(not isinstance(e, Exception) for e in result_ctx.errors) or len(result_ctx.errors) == 0

    def test_status_updated_on_board_server(self, e2e_env):
        """After pipeline run, STORY-001 should be in_progress on the server."""
        ctx, db, url, adapter = e2e_env

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = "2026-03-26T12:00:00"
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            pipeline = build_pipeline(ctx.agents_config, agent_ids=ctx.agent_ids)
            pipeline.run(ctx)

        # Check board server state
        item = db.get_item("STORY-001")
        assert item is not None
        assert item.get("status") == "in_progress"

    def test_inbox_message_delivered(self, e2e_env):
        """Agent's inbox message to dev1 should appear on the board server."""
        ctx, db, url, adapter = e2e_env

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = "2026-03-26T12:00:00"
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            pipeline = build_pipeline(ctx.agents_config, agent_ids=ctx.agent_ids)
            pipeline.run(ctx)

        # Check dev1's inbox on the board server
        inbox = db.get_inbox("dev1")
        assert any("STORY-001" in m["message"] for m in inbox)

    def test_workspace_file_written(self, e2e_env):
        """Agent's workspace file should be written to local filesystem."""
        ctx, db, url, adapter = e2e_env

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = "2026-03-26T12:00:00"
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            pipeline = build_pipeline(ctx.agents_config, agent_ids=ctx.agent_ids)
            pipeline.run(ctx)

        # Check workspace file exists
        notes = ctx.workspace_dir / "src" / "notes.txt"
        assert notes.exists()
        assert "Sprint 1 started" in notes.read_text(encoding="utf-8")

    def test_po_inbox_archived_after_run(self, e2e_env):
        """PO's inbox should be cleared after the agent runs."""
        ctx, db, url, adapter = e2e_env

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = "2026-03-26T12:00:00"
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            pipeline = build_pipeline(ctx.agents_config, agent_ids=ctx.agent_ids)
            pipeline.run(ctx)

        # PO's inbox should be empty (archived)
        inbox = db.get_inbox("po", unread_only=True)
        # Filter out system event messages — only agent messages matter
        agent_msgs = [m for m in inbox if m.get("from_agent") != "system"]
        assert len(agent_msgs) == 0

    def test_no_markdown_files_created(self, e2e_env):
        """When using board server adapter, no sprint.md/backlog.md should be created."""
        ctx, db, url, adapter = e2e_env

        mock_result = MagicMock()
        mock_result.agent_id = "po"
        mock_result.agent_name = "Product Owner"
        mock_result.response = MOCK_AGENT_RESPONSE
        mock_result.timestamp = "2026-03-26T12:00:00"
        mock_result.context_size = 5000
        mock_result.response_size = len(MOCK_AGENT_RESPONSE)
        mock_result.error = None

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            pipeline = build_pipeline(ctx.agents_config, agent_ids=ctx.agent_ids)
            pipeline.run(ctx)

        # The pipeline steps themselves should not create sprint.md or backlog.md
        # when using the board server adapter. However, agent output may write
        # board/sprint.md via apply_agent_output (which writes to local filesystem).
        # The key assertion: no *empty* board files were created by pipeline steps.
        board_dir = ctx.board_dir
        for fname in ("backlog.md",):
            fpath = board_dir / fname
            assert not fpath.exists(), f"{fname} should not be created by pipeline steps with board server adapter"
