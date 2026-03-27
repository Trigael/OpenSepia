"""Chaos and edge-case tests for per-agent pipeline code.

Covers AgentStep, AgentCommitStep, AgentSyncStep, InitStandupStep,
and build_pipeline expansion logic under adversarial conditions.
"""

import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

from opensepia.pipeline import PipelineContext, Pipeline
from opensepia.board_adapter_markdown import MarkdownBoardAdapter
from opensepia.steps.agent_step import (
    AgentStep, AgentCommitStep, AgentSyncStep, InitStandupStep,
)
from opensepia.commands.run import build_pipeline, STEP_REGISTRY, PARAMETERIZED_REGISTRY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_test_env(tmp_path, init_git=True):
    """Create a full test environment with board, workspace, adapter."""
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()

    (board / "sprint.md").write_text(
        "# Sprint 1\n\n## TODO\n- [ ] STORY-001: Login (dev1)\n\n## DONE\n",
        encoding="utf-8",
    )
    (board / "backlog.md").write_text(
        "# Backlog\n\n## HIGH\n### STORY-001: Login\n**Priority**: HIGH\n**Status**: TODO\n",
        encoding="utf-8",
    )
    (board / "project.md").write_text("# Test\n", encoding="utf-8")
    (board / "standup.md").write_text("", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")

    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
        (board / "inbox" / f"{agent}.md").write_text("", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()

    if init_git:
        subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(workspace), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(workspace), capture_output=True)
        (workspace / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(workspace), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(workspace), capture_output=True)

    adapter = MarkdownBoardAdapter(board_dir=board, workspace_dir=workspace, project_dir=tmp_path)

    agents_config = {
        "agents": {
            "po": {"name": "Product Owner", "color": "P", "system_prompt": "You are PO."},
            "dev1": {"name": "Developer 1", "color": "D", "system_prompt": "You are Dev1."},
            "tester": {"name": "Tester", "color": "T", "system_prompt": "You are Tester."},
        },
        "global": {"standup_instruction": "Write standup.", "communication_rules": "Use inbox."},
        "execution": {"timeout": 30, "max_retries": 0, "retry_delay": 0, "pause_between_agents": 0},
    }
    project_config = {
        "sprint": {"current_sprint": 1, "current_cycle": 1},
        "project": {"name": "Test"},
    }

    # Ensure logs dir exists for cycle state
    (tmp_path / "logs").mkdir(exist_ok=True)

    ctx = PipelineContext(
        mode="minimal",
        tool_dir=tmp_path,
        project_dir=tmp_path,
        agents_config=agents_config,
        project_config=project_config,
        board_dir=board,
        workspace_dir=workspace,
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs" / "runs",
        sprint_num=1,
        cycle_num=1,
        agent_ids=["po", "dev1", "tester"],
        execution_params={"timeout": 30, "max_retries": 0, "retry_delay": 0, "pause_between_agents": 0},
        board_adapter=adapter,
    )

    return ctx, adapter, board, workspace


def _mock_agent_result(agent_id="po", response="OK", error=None):
    """Create a mock AgentResult."""
    mock = MagicMock()
    mock.agent_id = agent_id
    mock.agent_name = agent_id
    mock.response = response
    mock.timestamp = datetime.now().isoformat()
    mock.context_size = len(response)
    mock.response_size = len(response)
    mock.error = error
    return mock


MOCK_RESPONSE = """\
## Report

---FILES---
path: board/sprint.md
content:
# Sprint 1

## TODO
- [ ] STORY-001: Login (dev1)

## DONE

---END---
"""

MALFORMED_RESPONSE = """\
I did some stuff but forgot to use the right format.
Here are my thoughts about the sprint.
No FILES section at all.
"""


# ===========================================================================
# AgentStep chaos
# ===========================================================================

class TestAgentStepChaos:
    """Chaos tests for AgentStep."""

    def test_agent_not_in_config(self, tmp_path):
        """1. Agent ID doesn't exist in agents_config — should warn and return."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        step = AgentStep("nonexistent_agent")
        result = step.execute(ctx)
        # Should not crash, should return ctx with no results added
        assert len(result.agent_results) == 0

    def test_adapter_get_agent_context_raises(self, tmp_path):
        """2. adapter.get_agent_context raises — should be caught by retry/exception handler."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        ctx.board_adapter = MagicMock()
        ctx.board_adapter.get_agent_context.side_effect = RuntimeError("DB connection lost")

        step = AgentStep("po")
        result = step.execute(ctx)
        # Should record error result, not crash
        assert len(result.agent_results) == 1
        assert result.agent_results[0].get("error") is not None
        assert "DB connection lost" in result.agent_results[0]["error"]

    def test_invoke_agent_returns_empty_response(self, tmp_path):
        """3. invoke_agent returns empty response string."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        mock_result = _mock_agent_result("po", response="", error=None)

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            step = AgentStep("po")
            result = step.execute(ctx)

        assert len(result.agent_results) == 1
        # Empty response is not an error by itself, just no files written
        assert result.agent_results[0]["response"] == ""

    def test_invoke_agent_raises_timeout(self, tmp_path):
        """4. invoke_agent raises a timeout exception."""
        ctx, _, _, _ = _create_test_env(tmp_path)

        with patch("opensepia.steps.agent_step.invoke_agent",
                    side_effect=TimeoutError("Claude CLI timed out after 30s")):
            step = AgentStep("po")
            result = step.execute(ctx)

        assert len(result.agent_results) == 1
        assert "timed out" in result.agent_results[0]["error"]

    def test_parse_files_section_returns_empty(self, tmp_path):
        """5. parse_files_section returns empty list — no files to write."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        mock_result = _mock_agent_result("po", response="Just a text response, no files.")

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            step = AgentStep("po")
            result = step.execute(ctx)

        assert len(result.agent_results) == 1
        # Should succeed but write 0 files
        assert result.agent_results[0].get("files_written", 0) == 0

    def test_apply_agent_output_raises(self, tmp_path):
        """6. apply_agent_output raises exception during file writing."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        mock_result = _mock_agent_result("po", response=MOCK_RESPONSE)

        ctx.board_adapter = MagicMock()
        ctx.board_adapter.get_agent_context.return_value = MagicMock()
        ctx.board_adapter.apply_agent_output.side_effect = OSError("Disk full")

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result), \
             patch("opensepia.steps.agent_step.build_agent_context_from_adapter", return_value="context"):
            step = AgentStep("po")
            result = step.execute(ctx)

        # Should catch the error (max_retries=0 so after 1 attempt)
        assert len(result.agent_results) == 1
        assert "Disk full" in result.agent_results[0]["error"]

    def test_multiple_agent_steps_same_agent(self, tmp_path):
        """7. Running PO step twice — should produce two results."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        mock_result = _mock_agent_result("po", response=MOCK_RESPONSE)

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            AgentStep("po").execute(ctx)
            AgentStep("po").execute(ctx)

        assert len(ctx.agent_results) == 2
        assert all(r["agent_id"] == "po" for r in ctx.agent_results)

    def test_skip_when_skip_agents_true(self, tmp_path):
        """8. skip_agents=True should bypass execution entirely."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        ctx.skip_agents = True

        step = AgentStep("po")
        result = step.execute(ctx)
        assert len(result.agent_results) == 0


# ===========================================================================
# AgentCommitStep chaos
# ===========================================================================

class TestAgentCommitStepChaos:
    """Chaos tests for AgentCommitStep."""

    def test_workspace_no_git(self, tmp_path):
        """9. Workspace has no .git directory — should silently skip."""
        ctx, _, _, workspace = _create_test_env(tmp_path, init_git=False)
        (workspace / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

        step = AgentCommitStep("dev1")
        result = step.execute(ctx)
        # Should not crash
        assert result is ctx

    def test_git_commit_fails(self, tmp_path):
        """10. Git commit fails — should warn but not crash."""
        ctx, _, _, workspace = _create_test_env(tmp_path)
        (workspace / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

        # Make git commit fail by using subprocess side_effect
        original_run = subprocess.run

        call_count = 0
        def failing_git(*args, **kwargs):
            nonlocal call_count
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "commit" in cmd:
                raise subprocess.SubprocessError("Git commit failed: lock file exists")
            return original_run(*args, **kwargs)

        with patch("opensepia.steps.agent_step.subprocess.run", side_effect=failing_git):
            step = AgentCommitStep("dev1")
            result = step.execute(ctx)

        # Should not crash, returns ctx
        assert result is ctx

    def test_very_long_filenames(self, tmp_path):
        """11. Very long filenames in workspace — git should handle gracefully."""
        ctx, _, _, workspace = _create_test_env(tmp_path)
        long_name = "a" * 200 + ".py"
        try:
            (workspace / "src" / long_name).write_text("x = 1\n", encoding="utf-8")
        except OSError:
            pytest.skip("OS does not support long filenames")

        step = AgentCommitStep("dev1")
        result = step.execute(ctx)
        assert result is ctx

    def test_binary_files_in_workspace(self, tmp_path):
        """12. Binary files in workspace — git add/commit should handle them."""
        ctx, _, _, workspace = _create_test_env(tmp_path)
        (workspace / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        step = AgentCommitStep("dev1")
        result = step.execute(ctx)

        # Verify commit happened
        log = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        assert "dev1" in log.stdout.lower() or "developer" in log.stdout.lower()

    def test_empty_workspace_no_changes(self, tmp_path):
        """13. Empty workspace (nothing changed) — should be a no-op."""
        ctx, _, _, workspace = _create_test_env(tmp_path)

        step = AgentCommitStep("dev1")
        result = step.execute(ctx)
        assert result is ctx

        # Only initial commit should exist
        log = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        lines = [l for l in log.stdout.strip().split("\n") if l.strip()]
        assert len(lines) == 1  # just "init"


# ===========================================================================
# AgentSyncStep chaos
# ===========================================================================

class TestAgentSyncStepChaos:
    """Chaos tests for AgentSyncStep."""

    def test_archive_inbox_no_inbox_dir(self, tmp_path):
        """14. Inbox directory doesn't exist — adapter should handle gracefully."""
        ctx, _, board, _ = _create_test_env(tmp_path)
        import shutil
        shutil.rmtree(board / "inbox")

        step = AgentSyncStep("po")
        # MarkdownBoardAdapter.archive_inbox reads inbox file - may raise
        # The step itself doesn't catch exceptions (non-critical in pipeline)
        # but the adapter might handle missing files. Let's verify behavior.
        try:
            result = step.execute(ctx)
            # If adapter handles it gracefully, we get ctx back
            assert result is ctx
        except (FileNotFoundError, OSError):
            # Also acceptable: exception propagates (pipeline marks non-critical)
            pass

    def test_archive_inbox_no_board_dir(self, tmp_path):
        """15. Board dir doesn't exist — should not crash the pipeline."""
        ctx, _, board, _ = _create_test_env(tmp_path)
        import shutil
        shutil.rmtree(board)

        step = AgentSyncStep("po")
        try:
            result = step.execute(ctx)
            assert result is ctx
        except (FileNotFoundError, OSError):
            # Exception is acceptable; pipeline wraps non-critical steps
            pass


# ===========================================================================
# InitStandupStep chaos
# ===========================================================================

class TestInitStandupStepChaos:
    """Chaos tests for InitStandupStep."""

    def test_skip_when_skip_agents_true(self, tmp_path):
        """16. skip_agents=True should bypass init_standup."""
        ctx, _, board, _ = _create_test_env(tmp_path)
        ctx.skip_agents = True

        step = InitStandupStep()
        result = step.execute(ctx)
        # Standup should remain empty
        assert (board / "standup.md").read_text(encoding="utf-8") == ""

    def test_adapter_init_standup_raises(self, tmp_path):
        """17. adapter.init_standup raises — should propagate (let pipeline handle)."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        ctx.board_adapter = MagicMock()
        ctx.board_adapter.init_standup.side_effect = RuntimeError("Board locked")

        step = InitStandupStep()
        with pytest.raises(RuntimeError, match="Board locked"):
            step.execute(ctx)


# ===========================================================================
# Pipeline expansion chaos
# ===========================================================================

def _minimal_config(pipeline=None):
    cfg = {
        "agents": {
            "po": {"name": "PO", "color": "P", "system_prompt": "PO"},
            "dev1": {"name": "Dev1", "color": "D", "system_prompt": "Dev1"},
        },
        "global": {},
    }
    if pipeline is not None:
        cfg["pipeline"] = pipeline
    return cfg


class TestPipelineExpansionChaos:
    """Chaos tests for build_pipeline."""

    def test_empty_agent_ids(self):
        """18. Empty agent_ids — agent_runner expands to just init_standup."""
        config = _minimal_config(["agent_runner"])
        pipeline = build_pipeline(config, agent_ids=[])

        step_names = [s.name for s in pipeline.steps]
        assert step_names == ["init_standup"]

    def test_empty_pipeline_yaml(self):
        """19. Pipeline YAML is an empty list — no steps at all."""
        config = _minimal_config([])
        pipeline = build_pipeline(config, agent_ids=["po"])

        assert len(pipeline.steps) == 0

    def test_agent_runner_listed_twice(self):
        """20. Pipeline has agent_runner twice — should produce two expansions."""
        config = _minimal_config(["agent_runner", "agent_runner"])
        pipeline = build_pipeline(config, agent_ids=["po"])

        step_names = [s.name for s in pipeline.steps]
        # Two init_standup, two run_agent:po, two commit:po, two sync:po
        assert step_names.count("init_standup") == 2
        assert step_names.count("run_agent:po") == 2

    def test_parameterized_step_unknown_agent(self):
        """21. Parameterized step references agent not in config — still creates step."""
        config = _minimal_config(["run_agent:ghost_agent"])
        pipeline = build_pipeline(config, agent_ids=[])

        # The step is created — it's up to AgentStep.execute to handle missing agent
        assert len(pipeline.steps) == 1
        assert pipeline.steps[0].name == "run_agent:ghost_agent"

    def test_parameterized_step_empty_param(self):
        """22. Parameterized step with empty param 'run_agent:' — creates step with empty id."""
        config = _minimal_config(["run_agent:"])
        pipeline = build_pipeline(config, agent_ids=[])

        assert len(pipeline.steps) == 1
        assert pipeline.steps[0].name == "run_agent:"

    def test_mix_regular_and_parameterized(self):
        """23. Mix of regular and parameterized steps — all created correctly."""
        config = _minimal_config([
            "board_health",
            "init_standup",
            "run_agent:po",
            "commit:po",
            "sync:po",
            "cycle_log",
        ])
        pipeline = build_pipeline(config, agent_ids=["po"])

        step_names = [s.name for s in pipeline.steps]
        assert step_names == [
            "board_health", "init_standup",
            "run_agent:po", "commit:po", "sync:po",
            "cycle_log",
        ]

    def test_unknown_step_name_skipped(self):
        """Unknown step names are skipped with a warning."""
        config = _minimal_config(["board_health", "does_not_exist", "cycle_log"])
        pipeline = build_pipeline(config, agent_ids=[])

        step_names = [s.name for s in pipeline.steps]
        assert "does_not_exist" not in step_names
        assert step_names == ["board_health", "cycle_log"]

    def test_unknown_parameterized_type_skipped(self):
        """Unknown parameterized step type is skipped."""
        config = _minimal_config(["nope:dev1"])
        pipeline = build_pipeline(config, agent_ids=[])

        assert len(pipeline.steps) == 0

    def test_non_string_entry_skipped(self):
        """Non-string entries in pipeline are skipped."""
        config = _minimal_config([42, {"step": "board_health"}, "cycle_log"])
        pipeline = build_pipeline(config, agent_ids=[])

        step_names = [s.name for s in pipeline.steps]
        assert step_names == ["cycle_log"]

    def test_none_agent_ids_defaults_to_empty(self):
        """None agent_ids should default to empty list."""
        config = _minimal_config(["agent_runner"])
        pipeline = build_pipeline(config, agent_ids=None)

        step_names = [s.name for s in pipeline.steps]
        assert step_names == ["init_standup"]

    def test_no_config_uses_defaults(self):
        """No agents_config uses DEFAULT_PIPELINE."""
        pipeline = build_pipeline(None, agent_ids=["po"])
        step_names = [s.name for s in pipeline.steps]
        assert "board_health" in step_names
        assert "run_agent:po" in step_names


# ===========================================================================
# Integration chaos
# ===========================================================================

class TestIntegrationChaos:
    """Integration-level chaos tests combining steps in a pipeline."""

    def test_full_pipeline_malformed_response(self, tmp_path):
        """24. Full pipeline with agent returning malformed (no ---FILES---) response."""
        ctx, _, board, _ = _create_test_env(tmp_path)
        mock_result = _mock_agent_result("po", response=MALFORMED_RESPONSE)

        with patch("opensepia.steps.agent_step.invoke_agent", return_value=mock_result):
            pipeline = build_pipeline(ctx.agents_config, agent_ids=["po"])
            # Run just the agent-related steps
            for step in pipeline.steps:
                if step.name in ("init_standup", "run_agent:po", "commit:po", "sync:po"):
                    ctx = step.execute(ctx)

        assert len(ctx.agent_results) == 1
        # Should succeed but write 0 files (no ---FILES--- block)
        assert ctx.agent_results[0].get("files_written", 0) == 0

    def test_one_agent_fails_others_succeed(self, tmp_path):
        """25. One agent fails, others succeed — all non-critical, pipeline continues."""
        ctx, _, _, _ = _create_test_env(tmp_path)

        good_result = _mock_agent_result("po", response=MOCK_RESPONSE)
        tester_result = _mock_agent_result("tester", response="Looks good, no files.")

        call_count = 0
        def mock_invoke(**kwargs):
            nonlocal call_count
            call_count += 1
            aid = kwargs.get("agent_id", "")
            if aid == "dev1":
                raise ConnectionError("API unreachable")
            elif aid == "tester":
                return tester_result
            return good_result

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=mock_invoke):
            steps = [
                AgentStep("po"),
                AgentStep("dev1"),
                AgentStep("tester"),
            ]
            for step in steps:
                ctx = step.execute(ctx)

        # All three agents should have results (two success, one error)
        assert len(ctx.agent_results) == 3
        errors = [r for r in ctx.agent_results if r.get("error")]
        assert len(errors) == 1
        assert "API unreachable" in errors[0]["error"]

    def test_pipeline_resume_skips_completed(self, tmp_path):
        """26. Pipeline resume skips already-completed per-agent steps."""
        ctx, _, _, _ = _create_test_env(tmp_path)

        mock_result = _mock_agent_result("po", response=MOCK_RESPONSE)

        from opensepia.cycle_state import CycleState

        # Simulate an interrupted cycle where init_standup and run_agent:po were done
        resume_state = CycleState(
            cycle_id="s1c1",
            sprint=1,
            cycle=1,
            mode="minimal",
            status="in_progress",
            completed_steps=["init_standup", "run_agent:po", "commit:po", "sync:po"],
            agent_ids=["po", "dev1"],
            started_at=datetime.now().isoformat(),
        )

        # Only dev1 steps should actually run
        invoke_calls = []
        def tracking_invoke(**kwargs):
            invoke_calls.append(kwargs.get("agent_id"))
            return _mock_agent_result(kwargs.get("agent_id", ""), response="OK")

        pipeline = Pipeline(steps=[
            InitStandupStep(),
            AgentStep("po"),
            AgentCommitStep("po"),
            AgentSyncStep("po"),
            AgentStep("dev1"),
            AgentCommitStep("dev1"),
            AgentSyncStep("dev1"),
        ])

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=tracking_invoke):
            result = pipeline.run(ctx, resume_state=resume_state)

        # Only dev1 should have been invoked (po was in completed_steps)
        assert invoke_calls == ["dev1"]

    def test_agent_step_with_retries_on_error_response(self, tmp_path):
        """Agent step retries when response contains ERROR keyword."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        # Allow 1 retry
        ctx.agents_config["execution"]["max_retries"] = 1
        ctx.agents_config["execution"]["retry_delay"] = 0

        error_result = _mock_agent_result("po", response="ERROR: something broke")
        ok_result = _mock_agent_result("po", response=MOCK_RESPONSE)

        calls = []
        def mock_invoke(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                return error_result
            return ok_result

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=mock_invoke):
            step = AgentStep("po")
            result = step.execute(ctx)

        # Should have retried once and succeeded
        assert len(calls) == 2
        assert len(result.agent_results) == 1
        assert result.agent_results[0].get("error") is None

    def test_agent_step_retries_on_exception_then_succeeds(self, tmp_path):
        """Agent step retries on exception and succeeds on second attempt."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        ctx.agents_config["execution"]["max_retries"] = 1
        ctx.agents_config["execution"]["retry_delay"] = 0

        ok_result = _mock_agent_result("po", response=MOCK_RESPONSE)

        calls = []
        def mock_invoke(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionError("Network blip")
            return ok_result

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=mock_invoke):
            step = AgentStep("po")
            result = step.execute(ctx)

        assert len(calls) == 2
        assert len(result.agent_results) == 1
        assert result.agent_results[0].get("error") is None

    def test_dry_run_agent_step_prints_context(self, tmp_path, capsys):
        """Dry run should print context preview without invoking agent."""
        ctx, _, _, _ = _create_test_env(tmp_path)
        ctx.dry_run = True

        step = AgentStep("po")
        result = step.execute(ctx)

        assert len(result.agent_results) == 0
        # Should have printed something to stdout
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_commit_step_skip_on_dry_run(self, tmp_path):
        """AgentCommitStep should no-op on dry_run."""
        ctx, _, _, workspace = _create_test_env(tmp_path)
        ctx.dry_run = True
        (workspace / "src" / "new.py").write_text("x = 1\n", encoding="utf-8")

        step = AgentCommitStep("dev1")
        result = step.execute(ctx)
        assert result is ctx

        # File should NOT have been committed
        log = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        assert "dev1" not in log.stdout.lower()

    def test_sync_step_skip_on_dry_run(self, tmp_path):
        """AgentSyncStep should no-op on dry_run."""
        ctx, _, board, _ = _create_test_env(tmp_path)
        ctx.dry_run = True
        (board / "inbox" / "po.md").write_text("## Hello\n", encoding="utf-8")

        step = AgentSyncStep("po")
        result = step.execute(ctx)
        assert result is ctx
        # Inbox should NOT have been archived
        assert (board / "inbox" / "po.md").read_text(encoding="utf-8") == "## Hello\n"

    def test_commit_step_agent_not_in_config_uses_agent_id(self, tmp_path):
        """AgentCommitStep with unknown agent uses agent_id as fallback author."""
        ctx, _, _, workspace = _create_test_env(tmp_path)
        (workspace / "src" / "file.py").write_text("y = 2\n", encoding="utf-8")

        step = AgentCommitStep("unknown_agent")
        result = step.execute(ctx)
        assert result is ctx

        # Should have used "unknown_agent" as fallback name
        log_out = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            capture_output=True, text=True, cwd=str(workspace),
        )
        assert "unknown_agent@opensepia.ai" in log_out.stdout
