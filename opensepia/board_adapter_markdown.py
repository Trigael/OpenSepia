"""
AI Dev Team — Markdown Board Adapter.

Implements BoardAdapter by reading/writing local markdown files.
This is an extraction of the current direct file operations from
agents/context.py, agents/writer.py, and steps/agent_runner.py.
"""

import re
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia.board_adapter import BoardAdapter, AgentContext
from opensepia.agents.parser import ParsedFile
from opensepia.agents.workspace import get_workspace_tree
from opensepia.config import MAX_STANDUP_CHARS, MAX_INBOX_CHARS

logger = logging.getLogger(__name__)

MAX_BACKLOG_CHARS = 4000
MAX_PROJECT_CHARS = 2000
MAX_COMMENT_CONTEXT_CHARS = 6000


class MarkdownBoardAdapter(BoardAdapter):
    """Board adapter backed by local markdown files.

    Extracts and preserves the exact behavior of the current direct
    file operations. This is the reference implementation — any new
    adapter must produce the same AgentContext structure.
    """

    def __init__(
        self,
        board_dir: Path,
        workspace_dir: Path,
        project_dir: Path,
    ):
        self.board_dir = board_dir
        self.workspace_dir = workspace_dir
        self.project_dir = project_dir

    SNAPSHOT_FILES = ["sprint.md", "backlog.md", "project.md", "architecture.md", "decisions.md"]

    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except Exception as e:
            return f"[READ ERROR: {e}]"

    # ----- Agent context -----

    def get_agent_context(self, agent_id: str, agents_config: dict, project_config: dict) -> AgentContext:
        sprint_cfg = project_config.get("sprint", {})

        # Project description
        project_md = self._read(self.board_dir / "project.md")
        if len(project_md) > MAX_PROJECT_CHARS:
            project_md = project_md[:MAX_PROJECT_CHARS]

        # Sprint (complete)
        sprint_md = self._read(self.board_dir / "sprint.md")

        # Backlog (truncated)
        backlog_md = self._read(self.board_dir / "backlog.md")
        if len(backlog_md) > MAX_BACKLOG_CHARS:
            backlog_md = backlog_md[:MAX_BACKLOG_CHARS]

        # Standup (current cycle only — strip nested <details>)
        standup = self._read(self.board_dir / "standup.md")
        details_pos = standup.find("<details>")
        if details_pos > 0:
            standup = standup[:details_pos].strip()
        if len(standup) > MAX_STANDUP_CHARS:
            standup = standup[:MAX_STANDUP_CHARS] + "\n_(truncated)_"

        # Inbox
        inbox = self._read(self.board_dir / "inbox" / f"{agent_id}.md")

        # Workspace tree
        workspace_tree = get_workspace_tree(self.workspace_dir)

        # Provider comments (optional)
        provider_comments = self._fetch_provider_comments()

        return AgentContext(
            project_description=project_md,
            sprint_md=sprint_md,
            backlog_md=backlog_md,
            standup=standup,
            inbox=inbox,
            workspace_tree=workspace_tree,
            provider_comments=provider_comments,
            sprint_num=sprint_cfg.get("current_sprint", 1),
            cycle_num=sprint_cfg.get("current_cycle", 0),
        )

    def _fetch_provider_comments(self) -> str:
        """Fetch provider comments for active stories (optional)."""
        try:
            from opensepia.integrations.providers import detect_provider
            from opensepia.board.comments import get_active_story_ids, fetch_comments_for_context

            provider = detect_provider()
            if provider and provider.enabled and provider.name != "markdown":
                active_ids = get_active_story_ids(
                    self.board_dir / "sprint.md",
                    self.board_dir / "backlog.md",
                )
                comments_md = fetch_comments_for_context(
                    active_ids, provider, max_chars=MAX_COMMENT_CONTEXT_CHARS,
                )
                if comments_md:
                    return f"\n## Issue Discussions (from {provider.name})\n{comments_md}"
        except Exception as e:
            logger.debug("Provider comments unavailable: %s", e)
        return ""

    # ----- Agent output -----

    def apply_agent_output(self, agent_id: str, files: list[ParsedFile], agents_config: dict) -> int:
        """Write parsed files to disk with security checks."""
        written = 0
        resolved_base = self.project_dir.resolve()

        for pf in files:
            if not pf.path or not pf.content:
                continue

            # Security: resolve path and check it's under project_dir
            full_path = (self.project_dir / pf.path).resolve()
            if not str(full_path).startswith(str(resolved_base)):
                logger.warning("SECURITY: %s path traversal blocked: %s", agent_id, pf.path)
                continue

            if pf.action == "append":
                existing = self._read(full_path)
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(existing + "\n" + pf.content, encoding="utf-8")
            else:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(pf.content, encoding="utf-8")

            written += 1

        return written

    # ----- Inbox -----

    def get_inbox(self, agent_id: str) -> str:
        return self._read(self.board_dir / "inbox" / f"{agent_id}.md")

    def archive_inbox(self, agent_id: str) -> None:
        inbox_path = self.board_dir / "inbox" / f"{agent_id}.md"
        content = self._read(inbox_path)
        if not content.strip():
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = self.board_dir / "archive" / agent_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / f"{timestamp}.md").write_text(content, encoding="utf-8")
        inbox_path.write_text("", encoding="utf-8")

    # ----- Standup -----

    def init_standup(self, sprint_num: int, cycle_num: int) -> None:
        standup_file = self.board_dir / "standup.md"
        old_content = self._read(standup_file)

        if old_content.strip():
            # Archive old standup
            archive_dir = self.board_dir / "archive" / "standup"
            archive_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            (archive_dir / f"s{sprint_num}_c{cycle_num - 1}_{timestamp}.md").write_text(
                old_content, encoding="utf-8",
            )

            # Keep previous cycle as context (strip nested <details>)
            details_pos = old_content.find("<details>")
            if details_pos > 0:
                clean = old_content[:details_pos].strip()
            else:
                clean = old_content.strip()

            if len(clean) > MAX_INBOX_CHARS:
                clean = clean[:MAX_INBOX_CHARS] + "\n_(truncated)_"

            prev = f"\n\n<details><summary>Previous cycle</summary>\n\n{clean}\n</details>\n"
        else:
            prev = ""

        header = f"# Standup — Sprint {sprint_num}, Cycle {cycle_num}\n"
        standup_file.parent.mkdir(parents=True, exist_ok=True)
        standup_file.write_text(header + prev + "\n", encoding="utf-8")

    # ----- Board readiness -----

    def ensure_board_ready(self) -> None:
        self.board_dir.mkdir(parents=True, exist_ok=True)
        inbox_dir = self.board_dir / "inbox"
        inbox_dir.mkdir(exist_ok=True)
        (self.board_dir / "archive").mkdir(exist_ok=True)

        # Create inbox files for all known agents
        # (use a fixed list since we don't have config here)
        known_agents = [
            "po", "pm", "dev1", "dev2", "devops", "tester",
            "sec_analyst", "sec_engineer", "sec_pentester",
        ]
        for agent in known_agents:
            inbox_file = inbox_dir / f"{agent}.md"
            if not inbox_file.exists():
                inbox_file.touch()

    # ----- New adapter methods -----

    def get_sprint_text(self) -> str:
        return self._read(self.board_dir / "sprint.md")

    def get_backlog_text(self) -> str:
        return self._read(self.board_dir / "backlog.md")

    def get_standup_text(self) -> str:
        return self._read(self.board_dir / "standup.md")

    def get_sprint_number(self) -> int:
        content = self._read(self.board_dir / "sprint.md")
        m = re.search(r"Sprint\s+(\d+)", content)
        return int(m.group(1)) if m else 1

    def get_active_story_ids(self) -> list[str]:
        """Parse sprint.md for stories in TODO/IN_PROGRESS/REVIEW/TESTING sections."""
        content = self._read(self.board_dir / "sprint.md")
        if not content:
            return []

        active_statuses = {"todo", "in progress", "in_progress", "review", "testing"}
        current_status = None
        ids: list[str] = []

        for line in content.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("## "):
                section = stripped[3:].strip()
                current_status = section if section in active_statuses else None
            elif current_status:
                refs = re.findall(r"((?:STORY|BUG)-\d+)", line)
                ids.extend(refs)

        return ids

    def get_board_summary(self) -> dict[str, int]:
        """Count stories by status from sprint.md checkboxes."""
        content = self._read(self.board_dir / "sprint.md")
        if not content:
            return {}

        summary: dict[str, int] = {}
        current_section: str | None = None

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                current_section = stripped[3:].strip().lower().replace(" ", "_")
                if current_section not in summary:
                    summary[current_section] = 0
            elif current_section and stripped.startswith("- ["):
                summary[current_section] = summary.get(current_section, 0) + 1

        return summary

    def check_board_health(self) -> dict[str, bool]:
        """Check sprint.md and backlog.md exist and are non-empty."""
        results: dict[str, bool] = {}
        for fname in ("sprint.md", "backlog.md"):
            fpath = self.board_dir / fname
            results[fname] = fpath.exists() and fpath.stat().st_size > 0
        return results

    def create_snapshot(self) -> int:
        """Copy board files to .snapshot/ directory."""
        snapshot_dir = self.board_dir / ".snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for fname in self.SNAPSHOT_FILES:
            src = self.board_dir / fname
            if src.exists():
                shutil.copy2(src, snapshot_dir / f"{fname}.bak")
                count += 1
        return count

    def send_inbox_message(self, to_agent: str, from_name: str, message: str) -> None:
        """Append a message to an agent's inbox file."""
        inbox_path = self.board_dir / "inbox" / f"{to_agent}.md"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        entry = f"\n## Message from {from_name}\n{message}\n"
        with open(inbox_path, "a", encoding="utf-8") as f:
            f.write(entry)
