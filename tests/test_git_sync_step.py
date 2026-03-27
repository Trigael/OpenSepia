"""Tests for steps/git_sync.py — GitSyncStep."""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from opensepia.steps.git_sync import GitSyncStep
from opensepia.pipeline import PipelineContext
from opensepia.errors import GitSyncError


def _make_ctx(tmp_path, **overrides):
    """Create a minimal PipelineContext for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    board_dir = tmp_path / "board"
    board_dir.mkdir(exist_ok=True)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)

    defaults = dict(
        mode="dev-team",
        tool_dir=tmp_path,
        project_dir=tmp_path,
        agents_config={"agents": {}, "execution": {}},
        project_config={},
        board_dir=board_dir,
        workspace_dir=workspace,
        config_dir=tmp_path / "config",
        logs_dir=logs_dir,
        sprint_num=1,
        cycle_num=1,
        agent_ids=["dev1", "dev2"],
        dry_run=False,
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


class TestGitSyncStepExecute:
    def test_dry_run_returns_ctx(self, tmp_path):
        ctx = _make_ctx(tmp_path, dry_run=True)
        step = GitSyncStep()
        result = step.execute(ctx)
        assert result is ctx

    def test_no_workspace_returns_ctx(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        # Remove workspace
        ctx.workspace_dir.rmdir()
        step = GitSyncStep()
        result = step.execute(ctx)
        assert result is ctx

    def test_no_git_dir_returns_ctx(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        # workspace exists but no .git
        step = GitSyncStep()
        result = step.execute(ctx)
        assert result is ctx

    def test_no_repo_url_returns_ctx(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        (ctx.workspace_dir / ".git").mkdir()
        step = GitSyncStep()
        with patch.dict(os.environ, {"GIT_REPO_URL": "", "GIT_TOKEN": ""}, clear=False):
            result = step.execute(ctx)
        assert result is ctx

    @patch("opensepia.steps.git_sync.subprocess.run")
    @patch("opensepia.steps.git_sync._AskPassHelper")
    def test_full_commit_and_push(self, mock_askpass, mock_run, tmp_path):
        ctx = _make_ctx(tmp_path, agents_config={
            "agents": {
                "dev1": {"name": "Developer 1"},
                "dev2": {"name": "Developer 2"},
            },
            "execution": {},
        })
        (ctx.workspace_dir / ".git").mkdir()

        # Mock AskPassHelper context manager
        mock_askpass.return_value.__enter__ = MagicMock(return_value={"GIT_ASKPASS": "/tmp/ask"})
        mock_askpass.return_value.__exit__ = MagicMock(return_value=False)

        def run_side_effect(args, **kwargs):
            cmd = " ".join(args)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""

            if "diff --cached --quiet" in cmd:
                # Changes exist
                result.returncode = 1
            elif "diff --cached --name-only" in cmd:
                result.stdout = "src/main.py\ntests/test_main.py"
            return result

        mock_run.side_effect = run_side_effect

        env_vars = {
            "GIT_REPO_URL": "https://github.com/test/repo.git",
            "GIT_TOKEN": "test-token",
            "GITLAB_URL": "",
            "GITLAB_TOKEN": "",
            "GITLAB_PROJECT_ID": "",
        }
        step = GitSyncStep()
        with patch.dict(os.environ, env_vars, clear=False):
            result = step.execute(ctx)

        assert result is ctx
        # Verify git commands were called
        git_calls = [c for c in mock_run.call_args_list]
        git_cmds = [" ".join(c[0][0]) for c in git_calls]

        assert any("git fetch" in cmd for cmd in git_cmds)
        assert any("git checkout main" in cmd for cmd in git_cmds)
        assert any("git add -A" in cmd for cmd in git_cmds)
        assert any("git commit" in cmd for cmd in git_cmds)
        assert any("git push" in cmd for cmd in git_cmds)

    @patch("opensepia.steps.git_sync.subprocess.run")
    @patch("opensepia.steps.git_sync._AskPassHelper")
    def test_no_changes_to_commit(self, mock_askpass, mock_run, tmp_path):
        ctx = _make_ctx(tmp_path)
        (ctx.workspace_dir / ".git").mkdir()

        mock_askpass.return_value.__enter__ = MagicMock(return_value={})
        mock_askpass.return_value.__exit__ = MagicMock(return_value=False)

        def run_side_effect(args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = run_side_effect

        env_vars = {
            "GIT_REPO_URL": "https://github.com/test/repo.git",
            "GIT_TOKEN": "",
            "GITLAB_URL": "",
            "GITLAB_TOKEN": "",
            "GITLAB_PROJECT_ID": "",
        }
        step = GitSyncStep()
        with patch.dict(os.environ, env_vars, clear=False):
            result = step.execute(ctx)

        assert result is ctx
        # Should not have called commit (diff --cached --quiet returned 0 = no changes)
        git_cmds = [" ".join(c[0][0]) for c in mock_run.call_args_list]
        assert not any("git commit" in cmd for cmd in git_cmds)

    @patch("opensepia.steps.git_sync.subprocess.run")
    @patch("opensepia.steps.git_sync._AskPassHelper")
    def test_push_failure_is_non_critical(self, mock_askpass, mock_run, tmp_path):
        ctx = _make_ctx(tmp_path)
        (ctx.workspace_dir / ".git").mkdir()

        mock_askpass.return_value.__enter__ = MagicMock(return_value={})
        mock_askpass.return_value.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def run_side_effect(args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            cmd = " ".join(args)

            if "diff --cached --quiet" in cmd:
                result.returncode = 1
            elif "diff --cached --name-only" in cmd:
                result.stdout = "file.py"
            elif "push" in cmd:
                result.returncode = 1
                result.stderr = "rejected"
            return result

        mock_run.side_effect = run_side_effect

        env_vars = {
            "GIT_REPO_URL": "https://github.com/test/repo.git",
            "GIT_TOKEN": "",
            "GITLAB_URL": "",
            "GITLAB_TOKEN": "",
            "GITLAB_PROJECT_ID": "",
        }
        step = GitSyncStep()
        with patch.dict(os.environ, env_vars, clear=False):
            result = step.execute(ctx)
        # Should not raise, push failure is just a warning
        assert result is ctx

    @patch("opensepia.steps.git_sync.subprocess.run")
    @patch("opensepia.steps.git_sync._AskPassHelper")
    def test_git_sync_error_propagates(self, mock_askpass, mock_run, tmp_path):
        ctx = _make_ctx(tmp_path)
        (ctx.workspace_dir / ".git").mkdir()

        mock_askpass.return_value.__enter__ = MagicMock(return_value={})
        mock_askpass.return_value.__exit__ = MagicMock(return_value=False)

        def run_side_effect(args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            cmd = " ".join(args)

            # Make "git add -A" fail with check=True
            if "add" in cmd and "-A" in cmd:
                result.returncode = 1
                result.stderr = "fatal: error"
            return result

        mock_run.side_effect = run_side_effect

        env_vars = {
            "GIT_REPO_URL": "https://github.com/test/repo.git",
            "GIT_TOKEN": "",
            "GITLAB_URL": "",
            "GITLAB_TOKEN": "",
            "GITLAB_PROJECT_ID": "",
        }
        step = GitSyncStep()
        with patch.dict(os.environ, env_vars, clear=False):
            with pytest.raises(GitSyncError):
                step.execute(ctx)

    @patch("opensepia.steps.git_sync.subprocess.run")
    @patch("opensepia.steps.git_sync._AskPassHelper")
    def test_subprocess_error_caught(self, mock_askpass, mock_run, tmp_path):
        """SubprocessError should be caught and not raise."""
        ctx = _make_ctx(tmp_path)
        (ctx.workspace_dir / ".git").mkdir()

        mock_askpass.return_value.__enter__ = MagicMock(return_value={})
        mock_askpass.return_value.__exit__ = MagicMock(return_value=False)

        mock_run.side_effect = subprocess.SubprocessError("timeout")

        env_vars = {
            "GIT_REPO_URL": "https://github.com/test/repo.git",
            "GIT_TOKEN": "",
        }
        step = GitSyncStep()
        with patch.dict(os.environ, env_vars, clear=False):
            result = step.execute(ctx)
        assert result is ctx


class TestComputeBranchName:
    def test_default_branch_name(self, tmp_path):
        ctx = _make_ctx(tmp_path, sprint_num=2, cycle_num=5)
        step = GitSyncStep()
        name = step._compute_branch_name(ctx)
        assert name == "ai-team/sprint-2-cycle-5"

    def test_branch_from_board_adapter(self, tmp_path):
        ctx = _make_ctx(tmp_path, sprint_num=1, cycle_num=3)
        adapter = MagicMock()
        adapter.get_active_story_ids.return_value = ["STORY-001", "BUG-002"]
        ctx.board_adapter = adapter

        step = GitSyncStep()
        name = step._compute_branch_name(ctx)
        assert name == "ai-team/story001-bug002-s1c3"

    def test_branch_from_sprint_md(self, tmp_path):
        ctx = _make_ctx(tmp_path, sprint_num=1, cycle_num=2)
        ctx.board_adapter = None
        sprint_md = ctx.board_dir / "sprint.md"
        sprint_md.write_text(
            "### STORY-010 Login\n**Status**: IN_PROGRESS\n"
            "### BUG-005 Fix crash\n**Status**: REVIEW\n",
            encoding="utf-8",
        )

        step = GitSyncStep()
        name = step._compute_branch_name(ctx)
        assert name == "ai-team/story010-bug005-s1c2"

    def test_branch_adapter_error_falls_back(self, tmp_path):
        ctx = _make_ctx(tmp_path, sprint_num=1, cycle_num=1)
        adapter = MagicMock()
        adapter.get_active_story_ids.side_effect = OSError("fail")
        ctx.board_adapter = adapter

        step = GitSyncStep()
        name = step._compute_branch_name(ctx)
        assert name == "ai-team/sprint-1-cycle-1"

    def test_branch_truncates_to_3_stories(self, tmp_path):
        ctx = _make_ctx(tmp_path, sprint_num=1, cycle_num=1)
        adapter = MagicMock()
        adapter.get_active_story_ids.return_value = [
            "STORY-001", "STORY-002", "STORY-003", "STORY-004",
        ]
        ctx.board_adapter = adapter

        step = GitSyncStep()
        name = step._compute_branch_name(ctx)
        # Only first 3
        assert "story004" not in name
        assert name.startswith("ai-team/story001-story002-story003-")


class TestGitSyncStepProperties:
    def test_name(self):
        step = GitSyncStep()
        assert step.name == "git_sync"

    def test_not_critical(self):
        step = GitSyncStep()
        assert step.critical is False


class TestCreateMr:
    @patch("opensepia.steps.git_sync.urllib.request.urlopen")
    def test_skips_without_config(self, mock_urlopen, tmp_path):
        ctx = _make_ctx(tmp_path)
        step = GitSyncStep()
        env_vars = {"GITLAB_URL": "", "GITLAB_TOKEN": "", "GITLAB_PROJECT_ID": ""}
        with patch.dict(os.environ, env_vars, clear=False):
            step._create_mr(ctx, "ai-team/sprint-1-cycle-1", "file.py")
        mock_urlopen.assert_not_called()

    @patch("opensepia.steps.git_sync.urllib.request.urlopen")
    def test_existing_mr_skips(self, mock_urlopen, tmp_path):
        ctx = _make_ctx(tmp_path)
        step = GitSyncStep()

        import json
        response = MagicMock()
        response.read.return_value = json.dumps([{"iid": 42}]).encode()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = response

        env_vars = {
            "GITLAB_URL": "https://gitlab.example.com",
            "GITLAB_TOKEN": "tok",
            "GITLAB_PROJECT_ID": "123",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            step._create_mr(ctx, "ai-team/sprint-1-cycle-1", "file.py")

        # Only one call (the check), no second call for creation
        assert mock_urlopen.call_count == 1

    @patch("opensepia.steps.git_sync.urllib.request.urlopen")
    def test_creates_new_mr(self, mock_urlopen, tmp_path):
        ctx = _make_ctx(tmp_path)
        step = GitSyncStep()

        import json
        # First call: no existing MR
        check_response = MagicMock()
        check_response.read.return_value = json.dumps([]).encode()
        check_response.__enter__ = MagicMock(return_value=check_response)
        check_response.__exit__ = MagicMock(return_value=False)

        # Second call: create MR
        create_response = MagicMock()
        create_response.read.return_value = json.dumps({"iid": 99, "web_url": "https://example.com/mr/99"}).encode()
        create_response.__enter__ = MagicMock(return_value=create_response)
        create_response.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [check_response, create_response]

        env_vars = {
            "GITLAB_URL": "https://gitlab.example.com",
            "GITLAB_TOKEN": "tok",
            "GITLAB_PROJECT_ID": "my/project",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            step._create_mr(ctx, "ai-team/story001-s1c1", "src/main.py")

        assert mock_urlopen.call_count == 2

    @patch("opensepia.steps.git_sync.urllib.request.urlopen")
    def test_mr_check_error_handled(self, mock_urlopen, tmp_path):
        ctx = _make_ctx(tmp_path)
        step = GitSyncStep()

        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        env_vars = {
            "GITLAB_URL": "https://gitlab.example.com",
            "GITLAB_TOKEN": "tok",
            "GITLAB_PROJECT_ID": "123",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            # Should not raise
            step._create_mr(ctx, "ai-team/sprint-1-cycle-1", "file.py")


class TestTokenInUrl:
    @patch("opensepia.steps.git_sync.subprocess.run")
    @patch("opensepia.steps.git_sync._AskPassHelper")
    def test_https_url_gets_oauth2_prefix(self, mock_askpass, mock_run, tmp_path):
        ctx = _make_ctx(tmp_path)
        (ctx.workspace_dir / ".git").mkdir()

        mock_askpass.return_value.__enter__ = MagicMock(return_value={})
        mock_askpass.return_value.__exit__ = MagicMock(return_value=False)

        # Return no changes so we exit early
        def run_side_effect(args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = run_side_effect

        env_vars = {
            "GIT_REPO_URL": "https://github.com/test/repo.git",
            "GIT_TOKEN": "my-secret-token",
            "GITLAB_URL": "",
            "GITLAB_TOKEN": "",
            "GITLAB_PROJECT_ID": "",
        }
        step = GitSyncStep()
        with patch.dict(os.environ, env_vars, clear=False):
            step.execute(ctx)

        # Check that fetch used oauth2@ URL
        fetch_calls = [
            c for c in mock_run.call_args_list
            if "fetch" in " ".join(c[0][0])
        ]
        assert len(fetch_calls) > 0
        fetch_args = fetch_calls[0][0][0]
        # The URL should contain oauth2@
        assert any("oauth2@" in arg for arg in fetch_args)
