"""Comprehensive unit tests for opensepia.integrations.git_client."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from opensepia.integrations.git_client import (
    GitClient,
    GitConfig,
    _AskPassHelper,
    _redact_credentials,
    sync_workspace_to_repo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], 0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "error", returncode: int = 1) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], returncode, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def git_env(tmp_path, monkeypatch):
    """Set env vars for a fully-configured GitConfig."""
    monkeypatch.setenv("GIT_REPO_URL", "https://example.com/repo.git")
    monkeypatch.setenv("GIT_REPO_PATH", str(tmp_path / "repo"))
    monkeypatch.setenv("GIT_USER_NAME", "Test User")
    monkeypatch.setenv("GIT_USER_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_MAIN_BRANCH", "main")
    monkeypatch.setenv("GIT_AUTO_PUSH", "true")
    monkeypatch.setenv("GIT_TOKEN", "secret-token-123")
    monkeypatch.delenv("GIT_SSH_KEY", raising=False)
    return tmp_path


@pytest.fixture()
def config(git_env):
    return GitConfig()


@pytest.fixture()
def client(config):
    return GitClient(config)


# ---------------------------------------------------------------------------
# _redact_credentials
# ---------------------------------------------------------------------------

class TestRedactCredentials:
    def test_redacts_https_token(self):
        url = "https://oauth2:ghp_secret@github.com/org/repo.git"
        assert _redact_credentials(url) == "https://***@github.com/org/repo.git"

    def test_redacts_http_token(self):
        url = "http://user:pass@host.com/repo"
        assert _redact_credentials(url) == "http://***@host.com/repo"

    def test_no_credentials_unchanged(self):
        url = "https://github.com/org/repo.git"
        assert _redact_credentials(url) == url

    def test_ssh_url_unchanged(self):
        url = "git@github.com:org/repo.git"
        assert _redact_credentials(url) == url

    def test_multiple_urls(self):
        text = "clone https://tok@a.com/r and https://tok@b.com/r"
        result = _redact_credentials(text)
        assert "tok" not in result
        assert "***@a.com" in result
        assert "***@b.com" in result


# ---------------------------------------------------------------------------
# GitConfig
# ---------------------------------------------------------------------------

class TestGitConfig:
    def test_loads_from_env(self, config):
        assert config.repo_url == "https://example.com/repo.git"
        assert config.user_name == "Test User"
        assert config.user_email == "test@example.com"
        assert config.main_branch == "main"
        assert config.auto_push is True
        assert config.token == "secret-token-123"
        assert config.is_configured is True

    def test_defaults_when_env_empty(self, monkeypatch):
        monkeypatch.delenv("GIT_REPO_URL", raising=False)
        monkeypatch.delenv("GIT_REPO_PATH", raising=False)
        monkeypatch.delenv("GIT_USER_NAME", raising=False)
        monkeypatch.delenv("GIT_USER_EMAIL", raising=False)
        monkeypatch.delenv("GIT_MAIN_BRANCH", raising=False)
        monkeypatch.delenv("GIT_AUTO_PUSH", raising=False)
        monkeypatch.delenv("GIT_TOKEN", raising=False)
        monkeypatch.delenv("GIT_SSH_KEY", raising=False)
        cfg = GitConfig()
        assert cfg.repo_url == ""
        assert cfg.is_configured is False
        assert cfg.main_branch == "main"
        assert cfg.auto_push is True  # default env value is "true"

    def test_auto_push_false(self, monkeypatch, git_env):
        monkeypatch.setenv("GIT_AUTO_PUSH", "false")
        cfg = GitConfig()
        assert cfg.auto_push is False

    def test_auth_repo_url_with_token(self, config):
        assert config.auth_repo_url == "https://oauth2@example.com/repo.git"

    def test_auth_repo_url_without_token(self, monkeypatch, git_env):
        monkeypatch.setenv("GIT_TOKEN", "")
        cfg = GitConfig()
        assert cfg.auth_repo_url == "https://example.com/repo.git"

    def test_auth_repo_url_ssh(self, monkeypatch, git_env):
        monkeypatch.setenv("GIT_REPO_URL", "git@github.com:org/repo.git")
        cfg = GitConfig()
        assert cfg.auth_repo_url == "git@github.com:org/repo.git"

    def test_ssh_key_env(self, monkeypatch, git_env):
        monkeypatch.setenv("GIT_SSH_KEY", "/path/to/key")
        cfg = GitConfig()
        assert cfg.ssh_key == "/path/to/key"


# ---------------------------------------------------------------------------
# _AskPassHelper
# ---------------------------------------------------------------------------

class TestAskPassHelper:
    def test_creates_and_cleans_up_script(self):
        helper = _AskPassHelper("my-token")
        with helper as env:
            assert "GIT_ASKPASS" in env
            assert "GIT_TERMINAL_PROMPT" in env
            script_path = env["GIT_ASKPASS"]
            assert os.path.exists(script_path)
            content = Path(script_path).read_text()
            assert "my-token" in content
        # cleaned up
        assert not os.path.exists(script_path)

    def test_empty_token_returns_empty_env(self):
        helper = _AskPassHelper("")
        with helper as env:
            assert env == {}

    def test_escapes_single_quotes(self):
        helper = _AskPassHelper("tok'en")
        with helper as env:
            content = Path(env["GIT_ASKPASS"]).read_text()
            assert "tok" in content


# ---------------------------------------------------------------------------
# GitClient — enabled / disabled
# ---------------------------------------------------------------------------

class TestGitClientEnabled:
    def test_enabled_when_configured(self, client):
        assert client.enabled is True

    def test_disabled_when_no_url(self, monkeypatch):
        monkeypatch.delenv("GIT_REPO_URL", raising=False)
        monkeypatch.delenv("GIT_REPO_PATH", raising=False)
        monkeypatch.delenv("GIT_MAIN_BRANCH", raising=False)
        monkeypatch.delenv("GIT_AUTO_PUSH", raising=False)
        monkeypatch.delenv("GIT_TOKEN", raising=False)
        monkeypatch.delenv("GIT_SSH_KEY", raising=False)
        c = GitClient(GitConfig())
        assert c.enabled is False

    def test_default_config_created(self, monkeypatch):
        monkeypatch.setenv("GIT_REPO_URL", "https://x.com/r.git")
        monkeypatch.delenv("GIT_REPO_PATH", raising=False)
        monkeypatch.delenv("GIT_MAIN_BRANCH", raising=False)
        monkeypatch.delenv("GIT_AUTO_PUSH", raising=False)
        monkeypatch.delenv("GIT_TOKEN", raising=False)
        monkeypatch.delenv("GIT_SSH_KEY", raising=False)
        c = GitClient()
        assert c.config is not None


# ---------------------------------------------------------------------------
# GitClient._run
# ---------------------------------------------------------------------------

class TestGitClientRun:
    @patch("subprocess.run", return_value=_ok("output"))
    def test_run_basic(self, mock_run, client):
        result = client._run("status")
        assert result.returncode == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "status"]

    @patch("subprocess.run", return_value=_ok())
    def test_run_passes_cwd(self, mock_run, client):
        client._run("status")
        kwargs = mock_run.call_args[1]
        assert kwargs["cwd"] == str(client.config.repo_path)

    @patch("subprocess.run", return_value=_ok())
    def test_run_custom_cwd(self, mock_run, client, tmp_path):
        client._run("status", cwd=tmp_path)
        kwargs = mock_run.call_args[1]
        assert kwargs["cwd"] == str(tmp_path)

    @patch("subprocess.run", return_value=_ok())
    def test_run_sets_author_env(self, mock_run, client):
        client._run("status")
        env = mock_run.call_args[1]["env"]
        assert env["GIT_AUTHOR_NAME"] == "Test User"
        assert env["GIT_AUTHOR_EMAIL"] == "test@example.com"
        assert env["GIT_COMMITTER_NAME"] == "Test User"
        assert env["GIT_COMMITTER_EMAIL"] == "test@example.com"

    @patch("subprocess.run", return_value=_ok())
    def test_run_merges_extra_env(self, mock_run, client):
        client._run("fetch", extra_env={"GIT_ASKPASS": "/tmp/script.sh"})
        env = mock_run.call_args[1]["env"]
        assert env["GIT_ASKPASS"] == "/tmp/script.sh"

    @patch("subprocess.run", return_value=_ok())
    def test_run_uses_timeout(self, mock_run, client):
        from opensepia.config import GIT_CMD_TIMEOUT
        client._run("status")
        kwargs = mock_run.call_args[1]
        assert kwargs["timeout"] == GIT_CMD_TIMEOUT

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 60))
    def test_run_timeout_raises(self, mock_run, client):
        with pytest.raises(subprocess.TimeoutExpired):
            client._run("fetch", "--all")

    @patch("subprocess.run", return_value=_fail("fatal: not a git repo"))
    def test_run_nonzero_logged(self, mock_run, client):
        """Non-zero return with check=True still returns result (no exception)."""
        result = client._run("status", check=True)
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# clone_or_pull
# ---------------------------------------------------------------------------

class TestCloneOrPull:
    def test_disabled_returns_false(self, monkeypatch):
        monkeypatch.delenv("GIT_REPO_URL", raising=False)
        monkeypatch.delenv("GIT_REPO_PATH", raising=False)
        monkeypatch.delenv("GIT_MAIN_BRANCH", raising=False)
        monkeypatch.delenv("GIT_AUTO_PUSH", raising=False)
        monkeypatch.delenv("GIT_TOKEN", raising=False)
        monkeypatch.delenv("GIT_SSH_KEY", raising=False)
        c = GitClient(GitConfig())
        assert c.clone_or_pull() is False

    @patch("subprocess.run", return_value=_ok())
    def test_pull_when_git_exists(self, mock_run, client):
        git_dir = client.config.repo_path / ".git"
        git_dir.mkdir(parents=True)
        assert client.clone_or_pull() is True
        cmds = [c[0][0] for c in mock_run.call_args_list]
        # Should have fetch and reset
        assert ["git", "fetch", "--all"] in cmds
        assert any("reset" in c for c in cmds)

    @patch("subprocess.run", return_value=_ok())
    def test_clone_when_no_repo(self, mock_run, client):
        # repo_path does not exist yet
        assert client.clone_or_pull() is True
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("clone" in c for c in cmds)
        # After clone, should configure user
        assert any("config" in c for c in cmds)

    @patch("subprocess.run", return_value=_fail("clone failed"))
    def test_clone_failure(self, mock_run, client):
        assert client.clone_or_pull() is False


# ---------------------------------------------------------------------------
# Branch operations
# ---------------------------------------------------------------------------

class TestBranchOperations:
    @patch("subprocess.run", return_value=_ok())
    def test_create_branch(self, mock_run, client):
        result = client.create_branch("feature/test")
        assert result is True
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("-b" in c for c in cmds)

    @patch("subprocess.run")
    def test_create_branch_already_exists(self, mock_run, client):
        """If -b fails, switch to existing branch."""
        def side_effect(cmd, **kw):
            if "-b" in cmd:
                return _fail("already exists")
            return _ok()
        mock_run.side_effect = side_effect
        result = client.create_branch("feature/test")
        assert result is True

    @patch("subprocess.run", return_value=_ok("feature/x\n"))
    def test_current_branch(self, mock_run, client):
        assert client.current_branch() == "feature/x"
        cmd = mock_run.call_args[0][0]
        assert "branch" in cmd
        assert "--show-current" in cmd

    @patch("subprocess.run", return_value=_ok())
    def test_switch_branch_success(self, mock_run, client):
        assert client.switch_branch("develop") is True

    @patch("subprocess.run", return_value=_fail())
    def test_switch_branch_failure(self, mock_run, client):
        assert client.switch_branch("nonexistent") is False

    @patch("subprocess.run", return_value=_ok())
    def test_create_branch_custom_from(self, mock_run, client):
        client.create_branch("feature/x", from_branch="develop")
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("develop" in c for c in cmds)


# ---------------------------------------------------------------------------
# Stage / Commit
# ---------------------------------------------------------------------------

class TestStageAndCommit:
    @patch("subprocess.run", return_value=_ok())
    def test_stage_specific_files(self, mock_run, client):
        assert client.stage_files(["a.py", "b.py"]) is True
        assert mock_run.call_count == 2

    @patch("subprocess.run", return_value=_ok())
    def test_stage_all(self, mock_run, client):
        assert client.stage_files() is True
        cmd = mock_run.call_args[0][0]
        assert "-A" in cmd

    @patch("subprocess.run")
    def test_commit_success(self, mock_run, client):
        mock_run.side_effect = [
            _ok("M file.py\n"),   # status --porcelain
            _ok(),                 # commit
        ]
        assert client.commit("add feature", "dev") is True
        commit_cmd = mock_run.call_args_list[1][0][0]
        msg = commit_cmd[commit_cmd.index("-m") + 1]
        assert msg.startswith("feat:")

    @patch("subprocess.run", return_value=_ok(""))
    def test_commit_nothing_to_commit(self, mock_run, client):
        """Empty porcelain output means nothing to commit."""
        assert client.commit("msg") is False

    @patch("subprocess.run")
    def test_commit_failure(self, mock_run, client):
        mock_run.side_effect = [
            _ok("M file.py\n"),   # status --porcelain
            _fail("error"),        # commit fails
        ]
        assert client.commit("msg") is False

    @patch("subprocess.run")
    def test_commit_role_prefixes(self, mock_run, client):
        """Each agent_role maps to a commit prefix."""
        roles = {
            "dev": "feat",
            "devops": "infra",
            "tester": "test",
            "pm": "docs",
            "po": "docs",
            "unknown": "chore",
        }
        for role, expected_prefix in roles.items():
            mock_run.reset_mock()
            mock_run.side_effect = [_ok("M f\n"), _ok()]
            client.commit("msg", role)
            commit_cmd = mock_run.call_args_list[1][0][0]
            msg = commit_cmd[commit_cmd.index("-m") + 1]
            assert msg.startswith(f"{expected_prefix}:"), f"role={role}"


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------

class TestPush:
    @patch("subprocess.run", return_value=_ok())
    def test_push_success(self, mock_run, client):
        # First call returns branch name, second is the push
        mock_run.side_effect = [_ok("feature/x\n"), _ok()]
        assert client.push() is True

    @patch("subprocess.run")
    def test_push_failure(self, mock_run, client):
        mock_run.side_effect = [_ok("main\n"), _fail("rejected")]
        assert client.push() is False

    @patch("subprocess.run", return_value=_ok())
    def test_push_explicit_branch(self, mock_run, client):
        assert client.push(branch="release") is True
        cmd = mock_run.call_args[0][0]
        assert "release" in cmd

    @patch("subprocess.run", return_value=_ok())
    def test_push_force_with_lease(self, mock_run, client):
        assert client.push(branch="b", force=True) is True
        cmd = mock_run.call_args[0][0]
        assert "--force-with-lease" in cmd

    @patch("subprocess.run", return_value=_ok())
    def test_push_sets_upstream(self, mock_run, client):
        assert client.push(branch="b") is True
        cmd = mock_run.call_args[0][0]
        assert "--set-upstream" in cmd

    def test_push_disabled(self, monkeypatch, git_env):
        monkeypatch.setenv("GIT_AUTO_PUSH", "false")
        cfg = GitConfig()
        c = GitClient(cfg)
        assert c.push() is True  # returns True (skipped)


# ---------------------------------------------------------------------------
# commit_and_push
# ---------------------------------------------------------------------------

class TestCommitAndPush:
    @patch("subprocess.run")
    def test_full_flow(self, mock_run, client):
        # commit_and_push with no branch arg:
        # 1. current_branch() for result["branch"]
        # 2. stage_files() -> add -A
        # 3. commit() -> status --porcelain
        # 4. commit() -> commit -m
        # 5. push() -> current_branch()
        # 6. push() -> push
        mock_run.side_effect = [
            _ok("main\n"),   # current_branch (for result)
            _ok(),           # stage_files (add -A)
            _ok("M f\n"),    # commit -> status --porcelain
            _ok(),           # commit -> git commit
            _ok("main\n"),   # push -> current_branch
            _ok(),           # push -> git push
        ]
        result = client.commit_and_push("test commit", "dev")
        assert result["staged"] is True
        assert result["committed"] is True
        assert result["pushed"] is True
        assert result["error"] is None

    @patch("subprocess.run")
    def test_nothing_to_commit(self, mock_run, client):
        results = iter([
            _ok("main\n"),   # current_branch
            _ok("main\n"),   # current_branch
            _ok(),           # stage
            _ok(""),         # status --porcelain (empty)
        ])
        mock_run.side_effect = results
        result = client.commit_and_push("msg", "dev")
        assert result["staged"] is True
        assert result["committed"] is False
        assert result["pushed"] is False

    @patch("subprocess.run")
    def test_subprocess_error_caught(self, mock_run, client):
        mock_run.side_effect = subprocess.SubprocessError("boom")
        result = client.commit_and_push("msg")
        assert result["error"] is not None
        assert "boom" in result["error"]

    @patch("subprocess.run")
    def test_os_error_caught(self, mock_run, client):
        mock_run.side_effect = OSError("disk full")
        result = client.commit_and_push("msg")
        assert result["error"] is not None

    @patch("subprocess.run")
    def test_with_branch_switch(self, mock_run, client):
        """When branch differs from current, create_branch is called."""
        call_count = [0]
        def side_effect(cmd, **kw):
            call_count[0] += 1
            if "--show-current" in cmd:
                # First call: on main; after create_branch: on feature
                if call_count[0] <= 1:
                    return _ok("main\n")
                return _ok("feature/x\n")
            if "--porcelain" in cmd:
                return _ok("M f\n")
            return _ok()
        mock_run.side_effect = side_effect
        result = client.commit_and_push("msg", "dev", branch="feature/x")
        assert result["error"] is None


# ---------------------------------------------------------------------------
# Status / Diff / Log
# ---------------------------------------------------------------------------

class TestStatusDiffLog:
    @patch("subprocess.run", return_value=_ok("M file.py\n?? new.py\n"))
    def test_get_status(self, mock_run, client):
        assert client.get_status() == "M file.py\n?? new.py"

    @patch("subprocess.run", return_value=_ok(" file.py | 5 ++---\n"))
    def test_get_diff(self, mock_run, client):
        result = client.get_diff()
        assert "file.py" in result

    @patch("subprocess.run", return_value=_ok(" file.py | 5 ++---\n"))
    def test_get_diff_custom_branch(self, mock_run, client):
        client.get_diff("develop")
        cmd = mock_run.call_args[0][0]
        assert "origin/develop...HEAD" in cmd

    @patch("subprocess.run", return_value=_ok("abc1234 feat: add X (AI, 1 hour ago)\n"))
    def test_get_log(self, mock_run, client):
        result = client.get_log(5)
        assert "abc1234" in result
        cmd = mock_run.call_args[0][0]
        assert "-5" in cmd

    @patch("subprocess.run", return_value=_ok("abc1234 feat: add X (AI, 1 hour ago)\n"))
    def test_get_log_default_count(self, mock_run, client):
        client.get_log()
        cmd = mock_run.call_args[0][0]
        assert "-10" in cmd


# ---------------------------------------------------------------------------
# get_git_context_md
# ---------------------------------------------------------------------------

class TestGitContextMd:
    def test_disabled(self, monkeypatch):
        monkeypatch.delenv("GIT_REPO_URL", raising=False)
        monkeypatch.delenv("GIT_REPO_PATH", raising=False)
        monkeypatch.delenv("GIT_MAIN_BRANCH", raising=False)
        monkeypatch.delenv("GIT_AUTO_PUSH", raising=False)
        monkeypatch.delenv("GIT_TOKEN", raising=False)
        monkeypatch.delenv("GIT_SSH_KEY", raising=False)
        c = GitClient(GitConfig())
        assert "not active" in c.get_git_context_md()

    @patch("subprocess.run")
    def test_context_includes_branch_and_remote(self, mock_run, client):
        mock_run.return_value = _ok("main\n")
        md = client.get_git_context_md()
        assert "Branch" in md
        assert "Remote" in md

    @patch("subprocess.run")
    def test_context_with_status_and_log(self, mock_run, client):
        def side_effect(cmd, **kw):
            if "--show-current" in cmd:
                return _ok("main\n")
            if "--short" in cmd:
                return _ok("M file.py\n")
            if "log" in cmd:
                return _ok("abc feat: x\n")
            return _ok()
        mock_run.side_effect = side_effect
        md = client.get_git_context_md()
        assert "Uncommitted" in md
        assert "Recent commits" in md


# ---------------------------------------------------------------------------
# sync_workspace_to_repo
# ---------------------------------------------------------------------------

class TestSyncWorkspaceToRepo:
    def test_copies_subdirectories(self, tmp_path):
        ws = tmp_path / "workspace"
        repo = tmp_path / "repo"
        ws.mkdir()
        repo.mkdir()

        # Create workspace structure
        (ws / "src").mkdir()
        (ws / "src" / "app.py").write_text("print('hello')")
        (ws / "tests").mkdir()
        (ws / "tests" / "test_app.py").write_text("assert True")
        (ws / "README.md").write_text("# Project")

        sync_workspace_to_repo(ws, repo)

        assert (repo / "src" / "app.py").exists()
        assert (repo / "tests" / "test_app.py").exists()
        assert (repo / "README.md").exists()

    def test_overwrites_existing(self, tmp_path):
        ws = tmp_path / "workspace"
        repo = tmp_path / "repo"
        ws.mkdir()
        repo.mkdir()
        (ws / "src").mkdir()
        (ws / "src" / "app.py").write_text("v2")
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("v1")

        sync_workspace_to_repo(ws, repo)
        assert (repo / "src" / "app.py").read_text() == "v2"

    def test_missing_workspace(self, tmp_path):
        """No error when workspace doesn't exist."""
        sync_workspace_to_repo(tmp_path / "nope", tmp_path / "repo")

    def test_ignores_pycache(self, tmp_path):
        ws = tmp_path / "workspace"
        repo = tmp_path / "repo"
        ws.mkdir()
        repo.mkdir()
        (ws / "src").mkdir()
        (ws / "src" / "__pycache__").mkdir()
        (ws / "src" / "__pycache__" / "mod.cpython-310.pyc").write_bytes(b"x")
        (ws / "src" / "app.py").write_text("ok")

        sync_workspace_to_repo(ws, repo)
        assert not (repo / "src" / "__pycache__").exists()
        assert (repo / "src" / "app.py").exists()

    def test_skips_dotfiles_in_root(self, tmp_path):
        ws = tmp_path / "workspace"
        repo = tmp_path / "repo"
        ws.mkdir()
        repo.mkdir()
        (ws / ".hidden").write_text("secret")
        (ws / "visible.txt").write_text("ok")

        sync_workspace_to_repo(ws, repo)
        assert not (repo / ".hidden").exists()
        assert (repo / "visible.txt").exists()

    def test_copies_docs_and_config(self, tmp_path):
        ws = tmp_path / "workspace"
        repo = tmp_path / "repo"
        ws.mkdir()
        repo.mkdir()
        (ws / "docs").mkdir()
        (ws / "docs" / "guide.md").write_text("doc")
        (ws / "config").mkdir()
        (ws / "config" / "app.yaml").write_text("key: val")

        sync_workspace_to_repo(ws, repo)
        assert (repo / "docs" / "guide.md").exists()
        assert (repo / "config" / "app.yaml").exists()
