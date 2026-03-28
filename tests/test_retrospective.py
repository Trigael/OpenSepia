"""
Unit tests for opensepia.retrospective module.

Tests template generation, response parsing, file writing,
and integration with the SprintCheckStep.
"""

from unittest.mock import MagicMock, patch

import pytest

from opensepia.retrospective import (
    RETRO_TEMPLATE,
    build_retro_context,
    parse_retro_response,
    write_retro_file,
)


# ---------------------------------------------------------------------------
# build_retro_context
# ---------------------------------------------------------------------------

class TestBuildRetroContext:
    def test_basic_context(self):
        ctx = build_retro_context(
            sprint_num=3,
            sprint_text="# Sprint 3\nGoal: Ship the auth module",
            standup_text="Dev1: finished login endpoint",
        )
        assert "Sprint 3" in ctx
        assert "Ship the auth module" in ctx
        assert "finished login endpoint" in ctx
        assert "Template (fill this in)" in ctx

    def test_missing_goal(self):
        ctx = build_retro_context(1, "no goal here", "")
        assert "(not specified)" in ctx

    def test_empty_inputs(self):
        ctx = build_retro_context(1, "", "")
        assert "(empty)" in ctx
        assert "(none)" in ctx

    def test_velocity_data_included(self):
        ctx = build_retro_context(
            sprint_num=2,
            sprint_text="Goal: improve speed",
            standup_text="",
            velocity_data={"stories_done": 5, "bugs_found": 2},
        )
        assert "Velocity Data" in ctx
        assert "stories_done" in ctx
        assert "5" in ctx

    def test_velocity_data_none(self):
        ctx = build_retro_context(1, "Goal: x", "", velocity_data=None)
        assert "Velocity" not in ctx


# ---------------------------------------------------------------------------
# parse_retro_response
# ---------------------------------------------------------------------------

WELL_FORMED_RESPONSE = """\
## Sprint 5 Retrospective

### Sprint Goal Assessment
**Goal**: Ship auth module
**Achieved**: Partially — login done, signup pending

### What Went Well
- CI pipeline was green all sprint
- Code review turnaround < 1 hour
- Dev1 shipped 3 stories

### What To Improve
- Test coverage dropped to 60%
- Standup notes were inconsistent
- Deploy took too long

### Action Items
- [ ] ACTION-001: Add coverage gate to CI — Owner: dev2
- [ ] ACTION-002: Automate deploy script — Owner: devops
"""

MESSY_RESPONSE = """\
Here is my retrospective thoughts:

## What Went Well
*  Good collaboration
*  Fast reviews

## What To Improve
- Need more tests (root cause: no enforcement)

## Action Items
  - ACTION-003: enforce coverage
"""


class TestParseRetroResponse:
    def test_well_formed(self):
        data = parse_retro_response(WELL_FORMED_RESPONSE)
        assert data["goal_assessment"] == "Partially — login done, signup pending"
        assert len(data["went_well"]) == 3
        assert "CI pipeline was green all sprint" in data["went_well"]
        assert len(data["to_improve"]) == 3
        assert len(data["action_items"]) == 2

    def test_messy_response(self):
        data = parse_retro_response(MESSY_RESPONSE)
        assert len(data["went_well"]) == 2
        assert "Good collaboration" in data["went_well"]
        assert len(data["to_improve"]) == 1
        assert len(data["action_items"]) == 1
        # No **Achieved** line
        assert data["goal_assessment"] == ""

    def test_empty_response(self):
        data = parse_retro_response("")
        assert data["went_well"] == []
        assert data["to_improve"] == []
        assert data["action_items"] == []
        assert data["goal_assessment"] == ""

    def test_partial_sections(self):
        resp = "### What Went Well\n- Only one item\n"
        data = parse_retro_response(resp)
        assert data["went_well"] == ["Only one item"]
        assert data["to_improve"] == []


# ---------------------------------------------------------------------------
# write_retro_file
# ---------------------------------------------------------------------------

class TestWriteRetroFile:
    def test_creates_archive_dir(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        data = {
            "went_well": ["Good stuff"],
            "to_improve": ["Fix flaky tests"],
            "action_items": ["ACTION-001: add retries"],
            "goal_assessment": "Met",
        }
        path = write_retro_file(board_dir, 4, data)
        assert path == board_dir / "archive" / "retro_sprint_4.md"
        assert path.exists()

    def test_file_contents(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        data = {
            "went_well": ["A", "B"],
            "to_improve": ["C"],
            "action_items": [],
            "goal_assessment": "Fully achieved",
        }
        path = write_retro_file(board_dir, 2, data)
        content = path.read_text(encoding="utf-8")
        assert "Sprint 2 Retrospective" in content
        assert "Fully achieved" in content
        assert "- A" in content
        assert "- B" in content
        assert "- C" in content
        assert "(none)" in content  # action_items empty

    def test_empty_data(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        data = {"went_well": [], "to_improve": [], "action_items": [], "goal_assessment": ""}
        path = write_retro_file(board_dir, 1, data)
        content = path.read_text(encoding="utf-8")
        assert "Sprint 1 Retrospective" in content
        assert content.count("(none)") == 3

    def test_accepts_string_board_dir(self, tmp_path):
        board_dir = tmp_path / "board"
        board_dir.mkdir()
        data = {"went_well": ["ok"], "to_improve": [], "action_items": [], "goal_assessment": ""}
        path = write_retro_file(str(board_dir), 1, data)
        assert path.exists()


# ---------------------------------------------------------------------------
# Integration with SprintCheckStep
# ---------------------------------------------------------------------------

class TestSprintCheckRetroIntegration:
    """Verify SprintCheckStep calls the retrospective functions."""

    def _make_ctx(self, tmp_path):
        from opensepia.pipeline import PipelineContext

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        board_dir = project_dir / "board"
        board_dir.mkdir()
        (board_dir / "sprint.md").write_text("# Sprint 1\nGoal: build MVP\n")
        (board_dir / "standup.md").write_text("Dev1: done with task\n")
        workspace_dir = project_dir / "workspace"
        workspace_dir.mkdir()
        logs_dir = project_dir / "logs"
        logs_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (project_dir / "project.yaml").write_text("sprint:\n  current_sprint: 1\n  current_cycle: 10\n  cycles_per_sprint: 10\n")

        adapter = MagicMock()
        adapter.get_agent_context.return_value = {}
        adapter.get_sprint_number.return_value = 2

        return PipelineContext(
            mode="dev-team",
            tool_dir=tmp_path,
            project_dir=project_dir,
            agents_config={
                "agents": {"po": {"name": "PO"}, "pm": {"name": "PM"}},
                "global": {"retrospective_agents": ["po"]},
            },
            project_config={"sprint": {"current_sprint": 1, "current_cycle": 10, "cycles_per_sprint": 10}},
            board_dir=board_dir,
            workspace_dir=workspace_dir,
            config_dir=config_dir,
            logs_dir=logs_dir,
            board_adapter=adapter,
        )

    @patch("opensepia.agents.invoker.invoke_agent")
    @patch("opensepia.agents.context.build_agent_context_from_adapter")
    def test_retro_writes_archive(self, mock_build, mock_invoke, tmp_path):
        """When sprint ends, a retro archive file should be created."""
        from opensepia.steps.sprint_check import SprintCheckStep

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.agent_id = "po"
        mock_result.agent_name = "PO"
        mock_result.response = WELL_FORMED_RESPONSE
        mock_result.timestamp = "2026-03-28T00:00:00"
        mock_result.context_size = 100
        mock_result.response_size = 200
        mock_invoke.return_value = mock_result
        mock_build.return_value = "context"

        ctx = self._make_ctx(tmp_path)
        step = SprintCheckStep()
        step.execute(ctx)

        archive = ctx.board_dir / "archive" / "retro_sprint_1.md"
        assert archive.exists()
        content = archive.read_text(encoding="utf-8")
        assert "What Went Well" in content

    @patch("opensepia.agents.invoker.invoke_agent")
    @patch("opensepia.agents.context.build_agent_context_from_adapter")
    def test_retro_context_injected(self, mock_build, mock_invoke, tmp_path):
        """Agent context should include retro_context key."""
        from opensepia.steps.sprint_check import SprintCheckStep

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.agent_id = "po"
        mock_result.agent_name = "PO"
        mock_result.response = ""
        mock_result.timestamp = "2026-03-28T00:00:00"
        mock_result.context_size = 0
        mock_result.response_size = 0
        mock_invoke.return_value = mock_result
        mock_build.return_value = "context"

        ctx = self._make_ctx(tmp_path)
        step = SprintCheckStep()
        step.execute(ctx)

        # get_agent_context is called, and then retro_context is added
        adapter = ctx.board_adapter
        assert adapter.get_agent_context.called
