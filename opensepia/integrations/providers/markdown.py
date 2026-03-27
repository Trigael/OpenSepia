"""
AI Dev Team — Markdown Provider

BoardProvider implementation backed by local markdown files.
This is the default provider when no external service is configured.

Wraps the current board/ directory operations (sprint.md, backlog.md,
inbox/*.md) behind the standard BoardProvider ABC, making it
interchangeable with GitLab, GitHub, or Board Server providers.
"""

import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from ..base import BoardProvider, BOARD_LABELS, PRIORITY_LABELS

logger = logging.getLogger(__name__)


class MarkdownProvider(BoardProvider):
    """Markdown file-backed implementation of BoardProvider.

    Reads and writes to the board/ directory structure:
      board/sprint.md     — current sprint with stories and statuses
      board/backlog.md    — product backlog with priorities
      board/standup.md    — standup reports
      board/inbox/*.md    — agent communication
      board/archive/      — archived inbox messages
    """

    def __init__(self, board_dir: Path | None = None):
        self._board_dir = board_dir
        self._issue_cache: dict[str, str] = {}

    @property
    def board_dir(self) -> Path:
        if self._board_dir:
            return self._board_dir
        # Default: look relative to the project
        return Path("project/board")

    @property
    def name(self) -> str:
        return "markdown"

    @property
    def enabled(self) -> bool:
        return self.board_dir.exists()

    def init(self) -> None:
        """Ensure board directory structure exists."""
        self.board_dir.mkdir(parents=True, exist_ok=True)
        (self.board_dir / "inbox").mkdir(exist_ok=True)
        (self.board_dir / "archive").mkdir(exist_ok=True)

    def clear_cache(self) -> None:
        self._issue_cache = {}

    def _load_status_overrides(self) -> dict[str, str]:
        """Load programmatic status overrides (from provider API calls)."""
        path = self.board_dir / ".status_overrides.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_status_override(self, story_id: str, status: str) -> None:
        """Save a status override for a story."""
        overrides = self._load_status_overrides()
        overrides[story_id] = status
        path = self.board_dir / ".status_overrides.json"
        path.write_text(json.dumps(overrides), encoding="utf-8")

    # ----- File helpers -----

    def _read(self, filename: str) -> str:
        path = self.board_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _write(self, filename: str, content: str) -> None:
        path = self.board_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _append(self, filename: str, content: str) -> None:
        path = self.board_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)

    # ----- Issues -----

    def create_issue(self, title: str, description: str,
                     labels: list[str] | None = None, **kwargs) -> dict:
        """Append a story/bug to backlog.md."""
        # Extract story ID from title if present: [STORY-001] Title
        match = re.search(r'\[((?:STORY|BUG)-\d+)\]', title)
        if match:
            story_id = match.group(1)
            clean_title = re.sub(r'\[(?:STORY|BUG)-\d+\]\s*', '', title).strip()
        else:
            # Generate next ID
            story_id = self._next_story_id(title)
            clean_title = title

        is_bug = "type::bug" in (labels or [])

        # If no explicit ID and it's a bug, generate BUG- prefix
        if not match and is_bug:
            story_id = self._next_id_with_prefix("BUG")

        priority = "medium"
        status = "todo"
        if labels:
            for key, val in PRIORITY_LABELS.items():
                if val in labels:
                    priority = key
            for key, val in BOARD_LABELS.items():
                if val in labels:
                    status = key

        # Append to backlog
        entry = f"\n### {story_id}: {clean_title}\n"
        entry += f"**Priority**: {priority.upper()}\n"
        entry += f"**Status**: {status.upper()}\n"
        if description:
            entry += f"\n{description}\n"

        self._append("backlog.md", entry)

        result = {
            "id": story_id,
            "iid": story_id,
            "title": f"[{story_id}] {clean_title}",
            "status": status,
            "priority": priority,
            "labels": labels or [],
            "state": "closed" if status == "done" else "opened",
        }

        self._issue_cache[story_id] = story_id
        logger.info("Created %s: %s", story_id, clean_title)
        return result

    def _next_story_id(self, title: str) -> str:
        """Generate next sequential story ID."""
        return self._next_id_with_prefix("STORY")

    def _next_id_with_prefix(self, prefix: str) -> str:
        """Generate next sequential ID for a given prefix."""
        backlog = self._read("backlog.md")
        sprint = self._read("sprint.md")
        all_text = backlog + sprint

        existing = re.findall(rf'{prefix}-(\d+)', all_text)
        if existing:
            next_num = max(int(n) for n in existing) + 1
        else:
            next_num = 1
        return f"{prefix}-{next_num:03d}"

    def close_issue(self, issue_id: Any) -> dict:
        return self.update_issue_status(str(issue_id), "", "done")

    def reopen_issue(self, issue_id: Any) -> dict:
        return self.update_issue_status(str(issue_id), "done", "todo")

    def update_issue_labels(self, issue_id: Any, labels: list[str]) -> dict:
        # Extract status and priority from labels
        for key, val in BOARD_LABELS.items():
            if val in labels:
                return self.update_issue_status(str(issue_id), "", key)
        return {"status": "ok"}

    def update_issue_status(self, issue_id: Any, from_status: str,
                            to_status: str) -> dict:
        """Update a story's status in sprint.md and backlog.md."""
        story_id = str(issue_id)
        updated = False

        # Update sprint.md
        sprint = self._read("sprint.md")
        if sprint:
            # Try block format: ### STORY-XXX: with **Status**: VALUE
            pattern = rf'(\*\*Status\*\*:\s*)(\S+)(.*?)(?=\n###|\n##|\Z)'
            for m in re.finditer(rf'### {re.escape(story_id)}:', sprint):
                # Find the Status line after this header
                rest = sprint[m.start():]
                status_match = re.search(r'(\*\*Status\*\*:\s*)(\S+)', rest)
                if status_match:
                    pos = m.start() + status_match.start(2)
                    end = m.start() + status_match.end(2)
                    sprint = sprint[:pos] + to_status.upper() + sprint[end:]
                    updated = True
                    break

            # Try checkbox format
            if to_status == "done":
                new_sprint, n = re.subn(
                    rf'- \[ \] (.*?{re.escape(story_id)})',
                    rf'- [x] \1',
                    sprint,
                )
                if n > 0:
                    sprint = new_sprint
                    updated = True
            elif from_status == "done" or not updated:
                new_sprint, n = re.subn(
                    rf'- \[x\] (.*?{re.escape(story_id)})',
                    rf'- [ ] \1',
                    sprint,
                )
                if n > 0:
                    sprint = new_sprint
                    updated = True

            if updated:
                self._write("sprint.md", sprint)

        # Also update backlog.md if it has a Status field
        backlog = self._read("backlog.md")
        if backlog:
            pattern = rf'(### {re.escape(story_id)}:.*?\n(?:.*?\n)*?\*\*Status\*\*:\s*)(\S+)'
            match = re.search(pattern, backlog)
            if match:
                backlog = backlog[:match.start(2)] + to_status.upper() + backlog[match.end(2):]
                self._write("backlog.md", backlog)

        # Save override so list_issues returns the correct status
        self._save_status_override(story_id, to_status)

        logger.info("Issue %s: %s -> %s", story_id, from_status, to_status)
        return {"status": "ok"}

    def comment_on_issue(self, issue_id: Any, agent_id: str,
                         message: str) -> dict:
        """Write a comment — stored as an entry in the agent's archive."""
        body = self._format_agent_comment(agent_id, message)
        # No per-issue comment file in markdown — comments go to agent inboxes
        # This is a no-op for markdown provider; agent-to-agent communication
        # is handled via inbox files directly
        return {"status": "ok", "body": body}

    def find_issue_by_id(self, story_id: str) -> str | None:
        if story_id in self._issue_cache:
            return self._issue_cache[story_id]

        backlog = self._read("backlog.md")
        sprint = self._read("sprint.md")

        if story_id in backlog or story_id in sprint:
            self._issue_cache[story_id] = story_id
            return story_id

        return None

    def list_issues(self, labels: str | None = None,
                    state: str = "opened") -> list:
        """Parse backlog.md and sprint.md into issue list."""
        from opensepia.board.sync import parse_backlog, parse_sprint_statuses

        backlog_path = self.board_dir / "backlog.md"
        sprint_path = self.board_dir / "sprint.md"

        items = []
        if backlog_path.exists():
            items = parse_backlog(backlog_path)

        sprint_statuses = {}
        if sprint_path.exists():
            sprint_statuses = parse_sprint_statuses(sprint_path)

        # Apply status overrides (from programmatic updates via provider API)
        overrides = self._load_status_overrides()

        result = []
        for item in items:
            status = sprint_statuses.get(item["id"], item.get("status", "todo"))
            # Provider overrides take priority over parsed markdown
            if item["id"] in overrides:
                status = overrides[item["id"]]
            priority = item.get("priority", "medium")

            # Filter by state
            if state == "closed" and status != "done":
                continue
            if state == "opened" and status == "done":
                continue

            # Filter by label
            if labels:
                item_labels = []
                if status in BOARD_LABELS:
                    item_labels.append(BOARD_LABELS[status])
                if priority in PRIORITY_LABELS:
                    item_labels.append(PRIORITY_LABELS[priority])
                if item.get("is_bug"):
                    item_labels.append("type::bug")
                if labels not in item_labels:
                    continue

            result.append({
                "id": item["id"],
                "iid": item["id"],
                "title": f"[{item['id']}] {item['title']}",
                "status": status,
                "priority": priority,
                "assigned": item.get("assigned"),
                "labels": [
                    BOARD_LABELS.get(status, ""),
                    PRIORITY_LABELS.get(priority, ""),
                ],
                "state": "closed" if status == "done" else "opened",
            })

        return result

    def search_issues(self, query: str,
                      state: str = "opened") -> list:
        items = self.list_issues(state=state)
        q = query.lower()
        return [i for i in items if q in i.get("title", "").lower()]

    def get_issue_comments(self, issue_id: Any,
                           limit: int = 10) -> list:
        # Markdown doesn't have per-issue comments — return empty
        return []

    # ----- Board -----

    def get_board_state(self) -> dict:
        items = self.list_issues(state="opened") + self.list_issues(state="closed")
        board: dict[str, list] = {}
        for item in items:
            status = item.get("status", "todo")
            if status not in board:
                board[status] = []
            board[status].append(item)
        return board

    def get_board_summary_md(self) -> str:
        # Just return sprint.md content — it IS the board
        return self._read("sprint.md") or "(no sprint.md)"

    # ----- MR / PR (not applicable for markdown) -----

    def create_mr(self, source_branch: str, target_branch: str,
                  title: str, description: str = "") -> dict:
        return {"error": "not_supported"}

    def list_mrs(self, state: str = "opened") -> list:
        return []

    def get_mr(self, mr_id: Any) -> dict:
        return {"error": "not_supported"}

    def comment_on_mr(self, mr_id: Any, body: str,
                      agent_id: str = "") -> dict:
        return {"error": "not_supported"}

    def approve_mr(self, mr_id: Any) -> dict:
        return {"error": "not_supported"}

    def merge_mr(self, mr_id: Any, squash: bool = False) -> dict:
        return {"error": "not_supported"}

    def close_mr(self, mr_id: Any) -> dict:
        return {"error": "not_supported"}

    def get_open_mrs_md(self) -> str:
        return ""

    def get_mr_changes(self, mr_id: Any) -> dict:
        return {"error": "not_supported"}

    def get_mr_approvals(self, mr_id: Any) -> dict:
        return {"approved": False}

    # ----- Inbox (markdown-specific, extends the ABC) -----

    def get_inbox(self, agent_id: str) -> str:
        """Read an agent's inbox file."""
        return self._read(f"inbox/{agent_id}.md")

    def send_inbox(self, to_agent: str, from_agent: str, message: str) -> None:
        """Append a message to an agent's inbox."""
        self._append(f"inbox/{to_agent}.md", f"\n{message}\n")

    def archive_inbox(self, agent_id: str) -> None:
        """Archive and clear an agent's inbox."""
        content = self.get_inbox(agent_id)
        if not content.strip():
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = self.board_dir / "archive" / agent_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / f"{timestamp}.md").write_text(content, encoding="utf-8")
        self._write(f"inbox/{agent_id}.md", "")

    def get_standup(self) -> str:
        """Read the standup file."""
        return self._read("standup.md")

    def get_project_description(self) -> str:
        """Read project.md."""
        return self._read("project.md")
