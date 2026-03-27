"""Tests for integrations/__init__.py — IntegrationDispatcher."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from opensepia.integrations import IntegrationDispatcher


def _make_dispatcher(tmp_path, board=None, git=None, docker=None):
    """Create a dispatcher with mocked clients."""
    with patch("opensepia.integrations.detect_provider", return_value=board), \
         patch("opensepia.integrations.GitClient") as MockGit, \
         patch("opensepia.integrations.DockerClient") as MockDocker:
        MockGit.return_value = git or MagicMock()
        MockDocker.return_value = docker or MagicMock()
        dispatcher = IntegrationDispatcher(tmp_path)
    # Override clients with our mocks if provided
    if board is not None:
        dispatcher.board = board
    if git is not None:
        dispatcher.git = git
    if docker is not None:
        dispatcher.docker = docker
    return dispatcher


class TestActiveIntegrations:
    def test_all_active(self, tmp_path):
        board = MagicMock()
        board.name = "GitHub"
        git = MagicMock()
        git.enabled = True
        d = _make_dispatcher(tmp_path, board=board, git=git)

        active = d.active_integrations
        assert "GitHub" in active
        assert "git" in active
        assert "docker" in active

    def test_no_board(self, tmp_path):
        git = MagicMock()
        git.enabled = True
        d = _make_dispatcher(tmp_path, board=None, git=git)
        d.board = None

        active = d.active_integrations
        assert "git" in active
        assert "docker" in active
        assert len([a for a in active if a not in ("git", "docker")]) == 0

    def test_no_git(self, tmp_path):
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, board=None, git=git)
        d.board = None

        active = d.active_integrations
        assert "git" not in active
        assert "docker" in active


class TestGetContextForAgent:
    def test_no_integrations(self, tmp_path):
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, board=None, git=git)
        d.board = None

        result = d.get_context_for_agent("po")
        assert result == "(No active integrations)"

    def test_board_context_for_all_agents(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.return_value = "## Board Summary"
        board.get_open_mrs_md.return_value = "## Open MRs"
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, board=board, git=git)

        result = d.get_context_for_agent("po")
        assert "Board Summary" in result

    def test_mr_context_for_dev_agents(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.return_value = "Board"
        board.get_open_mrs_md.return_value = "## Open MRs"
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, board=board, git=git)

        result = d.get_context_for_agent("dev1")
        assert "Open MRs" in result

    def test_no_mr_context_for_po(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.return_value = "Board"
        board.get_open_mrs_md.return_value = "## Open MRs"
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, board=board, git=git)

        result = d.get_context_for_agent("po")
        assert "Open MRs" not in result

    def test_git_context_for_dev(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.return_value = "Board"
        board.get_open_mrs_md.return_value = "## MRs"
        git = MagicMock()
        git.enabled = True
        git.get_git_context_md.return_value = "## Git Status"
        d = _make_dispatcher(tmp_path, board=board, git=git)

        result = d.get_context_for_agent("dev1")
        assert "Git Status" in result

    def test_docker_context_for_devops(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.return_value = "Board"
        git = MagicMock()
        git.enabled = False
        docker = MagicMock()
        docker.get_docker_context_md.return_value = "## Docker Status"
        d = _make_dispatcher(tmp_path, board=board, git=git, docker=docker)

        result = d.get_context_for_agent("devops")
        assert "Docker Status" in result

    def test_no_docker_context_for_non_devops(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.return_value = "Board"
        board.get_open_mrs_md.return_value = "## MRs"
        git = MagicMock()
        git.enabled = False
        docker = MagicMock()
        docker.get_docker_context_md.return_value = "## Docker"
        d = _make_dispatcher(tmp_path, board=board, git=git, docker=docker)

        result = d.get_context_for_agent("dev1")
        assert "Docker" not in result

    def test_board_error_handled(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.side_effect = OSError("fail")
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, board=board, git=git)

        result = d.get_context_for_agent("po")
        assert "unavailable" in result.lower()

    def test_git_error_handled(self, tmp_path):
        board = MagicMock()
        board.get_board_summary_md.return_value = "Board"
        board.get_open_mrs_md.return_value = "## MRs"
        git = MagicMock()
        git.enabled = True
        git.get_git_context_md.side_effect = subprocess.SubprocessError("fail")
        d = _make_dispatcher(tmp_path, board=board, git=git)

        result = d.get_context_for_agent("dev1")
        assert "unavailable" in result.lower()


class TestProcessActions:
    def test_empty_actions(self, tmp_path):
        d = _make_dispatcher(tmp_path)
        results = d.process_actions("dev1", [])
        assert results == []

    def test_unknown_action(self, tmp_path):
        d = _make_dispatcher(tmp_path)
        results = d.process_actions("dev1", [{"type": "unknown_action", "params": {}}])
        assert len(results) == 1
        assert results[0]["action"] == "unknown_action"
        assert results[0]["success"] is False  # "error" in result

    def test_action_exception_caught(self, tmp_path):
        board = MagicMock()
        board.create_story.side_effect = RuntimeError("boom")
        d = _make_dispatcher(tmp_path, board=board)

        results = d.process_actions("po", [{"type": "board_create_story", "params": {"title": "Test"}}])
        assert len(results) == 1
        assert results[0]["success"] is False
        assert "boom" in results[0]["error"]


class TestDispatchBoardActions:
    def test_board_create_story(self, tmp_path):
        board = MagicMock()
        board.create_story.return_value = {"iid": 1}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("po", "board_create_story", {"title": "New story"})
        board.create_story.assert_called_once_with(title="New story")
        assert result == {"iid": 1}

    def test_board_create_story_no_board(self, tmp_path):
        d = _make_dispatcher(tmp_path, board=None)
        d.board = None
        result = d._dispatch("po", "board_create_story", {})
        assert "error" in result

    def test_board_create_bug(self, tmp_path):
        board = MagicMock()
        board.create_bug.return_value = {"iid": 2}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("tester", "board_create_bug", {"title": "Bug"})
        board.create_bug.assert_called_once_with(title="Bug")

    def test_board_move_issue(self, tmp_path):
        board = MagicMock()
        board.update_issue_status.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("pm", "board_move_issue", {"issue_iid": 1, "status": "done"})
        board.update_issue_status.assert_called_once_with(issue_iid=1, status="done")

    def test_board_comment(self, tmp_path):
        board = MagicMock()
        board.comment_on_issue.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("dev1", "board_comment", {"issue_iid": 5, "message": "Done"})
        board.comment_on_issue.assert_called_once_with(5, "dev1", "Done")

    def test_board_close_issue(self, tmp_path):
        board = MagicMock()
        board.close_issue.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("pm", "board_close_issue", {"issue_iid": 3})
        board.close_issue.assert_called_once_with(3)


class TestDispatchGitActions:
    def test_git_commit_and_push(self, tmp_path):
        git = MagicMock()
        git.enabled = True
        git.config.repo_path.exists.return_value = False
        git.commit_and_push.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, git=git)

        result = d._dispatch("dev1", "git_commit_and_push", {"message": "fix bug"})
        git.commit_and_push.assert_called_once()

    def test_git_commit_disabled(self, tmp_path):
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, git=git)

        result = d._dispatch("dev1", "git_commit_and_push", {})
        assert "error" in result

    def test_git_create_branch(self, tmp_path):
        git = MagicMock()
        git.enabled = True
        d = _make_dispatcher(tmp_path, git=git)

        result = d._dispatch("dev1", "git_create_branch", {"branch_name": "feature/x"})
        git.create_branch.assert_called_once_with("feature/x")
        assert result["success"] is True

    def test_git_create_branch_disabled(self, tmp_path):
        git = MagicMock()
        git.enabled = False
        d = _make_dispatcher(tmp_path, git=git)

        result = d._dispatch("dev1", "git_create_branch", {"branch_name": "x"})
        assert "error" in result

    def test_git_create_mr(self, tmp_path):
        board = MagicMock()
        board.create_mr.return_value = {"iid": 10}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("dev1", "git_create_mr", {
            "source_branch": "feature/x",
            "title": "New feature",
            "description": "Adds X",
        })
        board.create_mr.assert_called_once()

    def test_git_create_mr_no_board(self, tmp_path):
        d = _make_dispatcher(tmp_path, board=None)
        d.board = None
        result = d._dispatch("dev1", "git_create_mr", {})
        assert "error" in result


class TestDispatchMrActions:
    def test_mr_comment(self, tmp_path):
        board = MagicMock()
        board.comment_on_mr.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("dev1", "mr_comment", {"mr_iid": 5, "body": "LGTM"})
        board.comment_on_mr.assert_called_once_with(mr_id=5, body="LGTM", agent_id="dev1")

    def test_mr_approve(self, tmp_path):
        board = MagicMock()
        board.approve_mr.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("tester", "mr_approve", {"mr_iid": 5})
        board.approve_mr.assert_called_once_with(5)

    def test_mr_merge(self, tmp_path):
        board = MagicMock()
        board.merge_mr.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, board=board)

        result = d._dispatch("pm", "mr_merge", {"mr_iid": 5, "squash": True})
        board.merge_mr.assert_called_once_with(mr_id=5, squash=True)

    def test_mr_actions_no_board(self, tmp_path):
        d = _make_dispatcher(tmp_path, board=None)
        d.board = None

        for action in ("mr_comment", "mr_approve", "mr_merge"):
            result = d._dispatch("dev1", action, {"mr_iid": 1})
            assert "error" in result


class TestDispatchDockerActions:
    def test_docker_build(self, tmp_path):
        docker = MagicMock()
        docker.build.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_build", {"path": ".", "tag": "v1"})
        docker.build.assert_called_once()

    def test_docker_run(self, tmp_path):
        docker = MagicMock()
        docker.run.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_run", {"image": "nginx", "name": "web"})
        docker.run.assert_called_once()

    def test_docker_stop(self, tmp_path):
        docker = MagicMock()
        docker.stop.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_stop", {"container": "web"})
        docker.stop.assert_called_once_with("web")

    def test_docker_restart(self, tmp_path):
        docker = MagicMock()
        docker.restart.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_restart", {"container": "web"})
        docker.restart.assert_called_once_with("web")

    def test_docker_rm(self, tmp_path):
        docker = MagicMock()
        docker.rm.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_rm", {"container": "web", "force": True})
        docker.rm.assert_called_once_with("web", force=True)

    def test_docker_deploy(self, tmp_path):
        docker = MagicMock()
        docker.deploy.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_deploy", {
            "image": "myapp", "name": "app", "tag": "v2",
        })
        docker.deploy.assert_called_once()

    def test_docker_pull(self, tmp_path):
        docker = MagicMock()
        docker.pull.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_pull", {"image": "nginx:latest"})
        docker.pull.assert_called_once_with("nginx:latest")

    def test_docker_push(self, tmp_path):
        docker = MagicMock()
        docker.push.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "docker_push", {"image": "myapp:v1"})
        docker.push.assert_called_once_with("myapp:v1")


class TestDispatchComposeActions:
    def test_compose_up(self, tmp_path):
        docker = MagicMock()
        docker.compose_up.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "compose_up", {"services": ["web", "db"]})
        docker.compose_up.assert_called_once()

    def test_compose_down(self, tmp_path):
        docker = MagicMock()
        docker.compose_down.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "compose_down", {"volumes": True})
        docker.compose_down.assert_called_once()

    def test_compose_restart(self, tmp_path):
        docker = MagicMock()
        docker.compose_restart.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        result = d._dispatch("devops", "compose_restart", {"services": ["web"]})
        docker.compose_restart.assert_called_once()

    def test_compose_uses_workspace_as_default_cwd(self, tmp_path):
        docker = MagicMock()
        docker.compose_up.return_value = {"ok": True}
        d = _make_dispatcher(tmp_path, docker=docker)

        d._dispatch("devops", "compose_up", {})
        _, kwargs = docker.compose_up.call_args
        # cwd should default to workspace_dir
        assert kwargs["cwd"] == d.workspace_dir


class TestUnknownAction:
    def test_returns_error(self, tmp_path):
        d = _make_dispatcher(tmp_path)
        result = d._dispatch("dev1", "totally_unknown", {})
        assert "error" in result
        assert "Unknown action" in result["error"]
