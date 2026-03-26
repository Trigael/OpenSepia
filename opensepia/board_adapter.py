"""
AI Dev Team — Board Adapter interface.

Sits between agents and whatever board backend is active (markdown files,
board server, etc.). Speaks in terms agents understand: "give me the
sprint", "here's my inbox", "write these files".

Two implementations:
- MarkdownBoardAdapter: reads/writes local markdown files (current behavior)
- (future) BoardServerAdapter: calls the board server API
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensepia.agents.parser import ParsedFile


@dataclass
class AgentContext:
    """Everything an agent needs to build their prompt context."""
    project_description: str
    sprint_md: str
    backlog_md: str
    standup: str
    inbox: str
    workspace_tree: str
    provider_comments: str
    sprint_num: int
    cycle_num: int


class BoardAdapter(ABC):
    """Interface between agents and the board storage backend."""

    @abstractmethod
    def get_agent_context(self, agent_id: str, agents_config: dict, project_config: dict) -> AgentContext:
        """Get all context an agent needs to build their prompt."""
        ...

    @abstractmethod
    def apply_agent_output(self, agent_id: str, files: list[ParsedFile], agents_config: dict) -> int:
        """Apply parsed agent output files. Returns number of files written."""
        ...

    @abstractmethod
    def get_inbox(self, agent_id: str) -> str:
        """Read an agent's inbox."""
        ...

    @abstractmethod
    def archive_inbox(self, agent_id: str) -> None:
        """Archive and clear an agent's inbox."""
        ...

    @abstractmethod
    def init_standup(self, sprint_num: int, cycle_num: int) -> None:
        """Initialize the standup file for a new cycle."""
        ...

    @abstractmethod
    def ensure_board_ready(self) -> None:
        """Ensure the board is ready (create dirs, inbox files, etc.)."""
        ...

    @abstractmethod
    def get_sprint_text(self) -> str:
        """Return the full sprint markdown text."""
        ...

    @abstractmethod
    def get_backlog_text(self) -> str:
        """Return the full backlog markdown text."""
        ...

    @abstractmethod
    def get_standup_text(self) -> str:
        """Return the current standup text."""
        ...

    @abstractmethod
    def get_sprint_number(self) -> int:
        """Return the current sprint number from the board."""
        ...

    @abstractmethod
    def get_active_story_ids(self) -> list[str]:
        """Return IDs of stories in active statuses (TODO/IN_PROGRESS/REVIEW/TESTING)."""
        ...

    @abstractmethod
    def get_board_summary(self) -> dict[str, int]:
        """Return counts of stories by status."""
        ...

    @abstractmethod
    def check_board_health(self) -> dict[str, bool]:
        """Check board health. Returns dict of check_name -> pass/fail."""
        ...

    @abstractmethod
    def create_snapshot(self) -> int:
        """Create a snapshot of the current board state. Returns number of files saved."""
        ...

    @abstractmethod
    def send_inbox_message(self, to_agent: str, from_name: str, message: str) -> None:
        """Send a message to an agent's inbox."""
        ...


def create_board_adapter(
    board_dir: Path,
    workspace_dir: Path,
    project_dir: Path,
) -> BoardAdapter:
    """Auto-select adapter based on BOARD_SERVER_URL env var.

    Returns BoardServerAdapter if BOARD_SERVER_URL is set and non-empty,
    otherwise returns MarkdownBoardAdapter.
    """
    server_url = os.environ.get("BOARD_SERVER_URL", "").strip()
    if server_url:
        from opensepia.board_adapter_server import BoardServerAdapter
        return BoardServerAdapter(server_url, workspace_dir, project_dir)
    else:
        from opensepia.board_adapter_markdown import MarkdownBoardAdapter
        return MarkdownBoardAdapter(board_dir, workspace_dir, project_dir)
