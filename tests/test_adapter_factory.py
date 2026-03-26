"""Tests for adapter factory — auto-selects adapter based on environment."""

import pytest
from pathlib import Path

from opensepia.board_adapter import BoardAdapter, create_board_adapter
from opensepia.board_adapter_markdown import MarkdownBoardAdapter
from opensepia.board_adapter_server import BoardServerAdapter


@pytest.fixture
def board_dirs(tmp_path):
    """Create minimal board and workspace dirs."""
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    ws = tmp_path / "workspace"
    ws.mkdir()
    return board, ws, tmp_path


class TestAdapterFactory:
    def test_returns_markdown_when_no_env(self, board_dirs, monkeypatch):
        monkeypatch.delenv("BOARD_SERVER_URL", raising=False)
        board, ws, project = board_dirs
        adapter = create_board_adapter(board, ws, project)
        assert isinstance(adapter, MarkdownBoardAdapter)

    def test_returns_server_when_env_set(self, board_dirs, monkeypatch):
        monkeypatch.setenv("BOARD_SERVER_URL", "http://localhost:9999")
        board, ws, project = board_dirs
        adapter = create_board_adapter(board, ws, project)
        assert isinstance(adapter, BoardServerAdapter)

    def test_always_returns_board_adapter(self, board_dirs, monkeypatch):
        monkeypatch.delenv("BOARD_SERVER_URL", raising=False)
        board, ws, project = board_dirs
        adapter = create_board_adapter(board, ws, project)
        assert isinstance(adapter, BoardAdapter)

    def test_passes_dirs_to_markdown(self, board_dirs, monkeypatch):
        monkeypatch.delenv("BOARD_SERVER_URL", raising=False)
        board, ws, project = board_dirs
        adapter = create_board_adapter(board, ws, project)
        assert adapter.board_dir == board
        assert adapter.workspace_dir == ws

    def test_passes_url_to_server(self, board_dirs, monkeypatch):
        monkeypatch.setenv("BOARD_SERVER_URL", "http://my-server:8080")
        board, ws, project = board_dirs
        adapter = create_board_adapter(board, ws, project)
        assert adapter.server_url == "http://my-server:8080"

    def test_empty_url_uses_markdown(self, board_dirs, monkeypatch):
        monkeypatch.setenv("BOARD_SERVER_URL", "")
        board, ws, project = board_dirs
        adapter = create_board_adapter(board, ws, project)
        assert isinstance(adapter, MarkdownBoardAdapter)
