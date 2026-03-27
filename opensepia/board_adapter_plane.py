"""
AI Dev Team — Plane.so Board Adapter.

Implements BoardAdapter against the Plane.so REST API.
Translates between the agent's markdown-centric world and
Plane.so's structured work-item/cycle/page model.

Replaces both MarkdownBoardAdapter and BoardServerAdapter when
PLANE_API_KEY + PLANE_WORKSPACE_SLUG are configured.
"""

import re
import logging
from pathlib import Path
from typing import Any

from opensepia.board_adapter import BoardAdapter, AgentContext
from opensepia.agents.parser import ParsedFile
from opensepia.agents.workspace import get_workspace_tree
from opensepia.integrations.providers.plane_client import PlaneClient, PlaneConfig
from opensepia.integrations.providers.plane import PlaneProvider
from opensepia.integrations.providers.plane_mapping import (
    map_plane_state_to_status,
    find_state_id_for_status,
    map_plane_priority,
    map_opensepia_priority,
    extract_story_id_from_title,
    build_title,
    strip_title_prefix,
)

logger = logging.getLogger(__name__)

# Truncation limits (match existing constants)
MAX_PROJECT_CHARS = 2000
MAX_BACKLOG_CHARS = 4000
MAX_STANDUP_CHARS = 2000
MAX_INBOX_CHARS = 1500


class PlaneBoardAdapter(BoardAdapter):
    """Board adapter backed by Plane.so API.

    Builds agent context by fetching work items from Plane and formatting
    them as markdown (same structure agents expect from local files).
    Parses agent output (board file writes) and translates them into
    Plane API calls (create/update work items, pages, comments).
    """

    def __init__(
        self,
        workspace_dir: Path,
        project_dir: Path,
        config: PlaneConfig | None = None,
    ):
        self.workspace_dir = workspace_dir
        self.project_dir = project_dir
        self._config = config or PlaneConfig.from_env()
        self._client = PlaneClient(self._config)
        self._provider = PlaneProvider(self._config)
        self._standup_entries: list[str] = []  # Accumulated per cycle

    @property
    def provider(self) -> PlaneProvider:
        return self._provider

    # =====================================================================
    # Agent context
    # =====================================================================

    def get_agent_context(
        self, agent_id: str, agents_config: dict, project_config: dict,
    ) -> AgentContext:
        sprint_cfg = project_config.get("sprint", {})
        sprint_num = sprint_cfg.get("current_sprint", 1)
        cycle_num = sprint_cfg.get("current_cycle", 0)

        # Sprint markdown from Plane work items
        sprint_md = self._build_sprint_md(sprint_num)

        # Backlog markdown
        backlog_md = self._build_backlog_md()

        # Project description from Plane Page or config fallback
        project_desc = self._get_project_description(project_config)

        # Standup (accumulated entries this cycle or from Page)
        standup = self._get_standup_text(sprint_num, cycle_num)

        # Inbox from Plane Page
        inbox = self._get_inbox_text(agent_id)

        # Workspace tree (always local filesystem)
        workspace_tree = get_workspace_tree(self.workspace_dir)

        # Provider comments from active work items
        provider_comments = self._get_provider_comments()

        return AgentContext(
            project_description=project_desc,
            sprint_md=sprint_md,
            backlog_md=backlog_md,
            standup=standup,
            inbox=inbox,
            workspace_tree=workspace_tree,
            provider_comments=provider_comments,
            sprint_num=sprint_num,
            cycle_num=cycle_num,
        )

    def _build_sprint_md(self, sprint_num: int) -> str:
        """Build sprint.md equivalent from Plane work items."""
        board = self._provider.get_board_state()

        status_order = [
            ("todo", "TODO"),
            ("in_progress", "IN PROGRESS"),
            ("review", "REVIEW"),
            ("testing", "TESTING"),
            ("done", "DONE"),
            ("blocked", "BLOCKED"),
        ]

        lines = [f"# Sprint {sprint_num}\n"]
        for status_key, display in status_order:
            items = board.get(status_key, [])
            lines.append(f"\n## {display}")
            if items:
                for item in items:
                    item_id = item.get("id", "?")
                    title = item.get("title", "?")
                    assigned = item.get("assigned", "")
                    assigned_str = f" ({assigned})" if assigned else ""
                    checkbox = "[x]" if status_key == "done" else "[ ]"
                    lines.append(f"- {checkbox} {item_id}: {title}{assigned_str}")
            lines.append("")

        return "\n".join(lines)

    def _build_backlog_md(self) -> str:
        """Build backlog.md equivalent from Plane work items."""
        board = self._provider.get_board_state()

        # Flatten all items, group by priority
        all_items = []
        for status_items in board.values():
            all_items.extend(status_items)

        by_priority: dict[str, list] = {
            "critical": [], "high": [], "medium": [], "low": [],
        }
        for item in all_items:
            prio = item.get("priority", "medium")
            if prio not in by_priority:
                by_priority[prio] = []
            by_priority[prio].append(item)

        lines = ["# Backlog\n"]
        for prio in ["critical", "high", "medium", "low"]:
            prio_items = by_priority.get(prio, [])
            lines.append(f"\n## {prio.upper()}")
            for item in prio_items:
                item_id = item.get("id", "?")
                title = item.get("title", "?")
                status = item.get("status", "todo")
                assigned = item.get("assigned", "")
                lines.append(f"### {item_id}: {title}")
                lines.append(f"**Priority**: {prio.upper()}")
                lines.append(f"**Status**: {status.upper()}")
                if assigned:
                    lines.append(f"**Assigned**: {assigned}")
                lines.append("")

        text = "\n".join(lines)
        if len(text) > MAX_BACKLOG_CHARS:
            text = text[:MAX_BACKLOG_CHARS] + "\n... (backlog truncated)"
        return text

    def _get_project_description(self, project_config: dict) -> str:
        """Get project description from Plane Page, falling back to config."""
        content = self._provider.get_page_content("project-description")
        if content and content.strip():
            if len(content) > MAX_PROJECT_CHARS:
                content = content[:MAX_PROJECT_CHARS] + "\n... (truncated)"
            return content

        proj = project_config.get("project", {})
        return f"# {proj.get('name', 'Project')}\n\n{proj.get('description', '')}"

    def _get_standup_text(self, sprint_num: int, cycle_num: int) -> str:
        """Get standup from accumulated entries or Plane Page."""
        if self._standup_entries:
            text = "\n".join(self._standup_entries)
        else:
            page_name = f"standup-s{sprint_num}-c{cycle_num}"
            text = self._provider.get_page_content(page_name)

        if len(text) > MAX_STANDUP_CHARS:
            text = text[:MAX_STANDUP_CHARS] + "\n... (standup truncated)"
        return text

    def _get_inbox_text(self, agent_id: str) -> str:
        """Get agent inbox from Plane Page."""
        page_name = f"inbox-{agent_id}"
        text = self._provider.get_page_content(page_name)
        if len(text) > MAX_INBOX_CHARS:
            text = text[:MAX_INBOX_CHARS] + "\n... (inbox truncated)"
        return text

    def _get_provider_comments(self) -> str:
        """Get recent comments from active work items for context."""
        active_ids = self.get_active_story_ids()
        if not active_ids:
            return ""

        lines = ["\n## Recent Comments"]
        total_chars = 0
        max_chars = 3000

        for story_id in active_ids[:8]:  # Limit to 8 stories
            uuid = self._provider.find_issue_by_id(story_id)
            if not uuid:
                continue
            comments = self._provider.get_issue_comments(uuid, limit=5)
            if not comments:
                continue

            header = f"\n### {story_id}\n"
            if total_chars + len(header) > max_chars:
                break
            lines.append(header)
            total_chars += len(header)

            for c in comments[-3:]:
                author = c.get("author", {}).get("name", "?")
                body = c.get("body", "")
                if len(body) > 500:
                    body = body[:497] + "..."
                entry = f"- **{author}**: {body}\n"
                if total_chars + len(entry) > max_chars:
                    break
                lines.append(entry)
                total_chars += len(entry)

        return "\n".join(lines) if len(lines) > 1 else ""

    # =====================================================================
    # Agent output
    # =====================================================================

    def apply_agent_output(
        self, agent_id: str, files: list[ParsedFile], agents_config: dict,
    ) -> int:
        """Parse agent file output and translate to Plane API calls."""
        written = 0
        resolved_base = self.project_dir.resolve()

        for pf in files:
            if not pf.path or not pf.content:
                continue

            if "board/sprint.md" in pf.path:
                self._apply_sprint_update(pf.content, agent_id)
                written += 1
            elif "board/backlog.md" in pf.path:
                self._apply_backlog_update(pf.content, agent_id)
                written += 1
            elif "board/inbox/" in pf.path:
                self._apply_inbox_message(pf.path, pf.content, agent_id)
                written += 1
            elif "board/standup.md" in pf.path:
                self._apply_standup(pf.content)
                written += 1
            elif pf.path in (
                "board/architecture.md", "board/decisions.md",
                "board/project.md",
            ):
                page_name = pf.path.replace("board/", "").replace(".md", "")
                if page_name == "project":
                    page_name = "project-description"
                self._provider.update_page(page_name, pf.content)
                written += 1
            elif pf.path.startswith("workspace/") or pf.path.startswith("src/"):
                # Write to local filesystem
                full_path = (self.project_dir / pf.path).resolve()
                try:
                    full_path.relative_to(resolved_base)
                except ValueError:
                    logger.warning("SECURITY: %s path traversal blocked: %s", agent_id, pf.path)
                    continue
                full_path.parent.mkdir(parents=True, exist_ok=True)
                if pf.action == "append":
                    existing = ""
                    if full_path.exists():
                        existing = full_path.read_text(encoding="utf-8")
                    full_path.write_text(existing + "\n" + pf.content, encoding="utf-8")
                else:
                    full_path.write_text(pf.content, encoding="utf-8")
                written += 1
            elif pf.path.startswith("board/"):
                # Other board files -> Plane Pages
                page_name = pf.path.replace("board/", "").replace(".md", "")
                self._provider.update_page(page_name, pf.content)
                written += 1

        return written

    def _apply_sprint_update(self, content: str, agent_id: str) -> None:
        """Parse sprint markdown and update work item states in Plane."""
        status_map = {
            "todo": "todo", "in progress": "in_progress",
            "in_progress": "in_progress", "review": "review",
            "testing": "testing", "done": "done", "blocked": "blocked",
        }

        current_status = None
        for line in content.split("\n"):
            stripped = line.strip().lower()

            if stripped.startswith("## "):
                current_status = None
                for keyword, status in status_map.items():
                    if keyword in stripped:
                        current_status = status
                        break

            if current_status and ("STORY-" in line or "BUG-" in line):
                refs = re.findall(r'((?:STORY|BUG)-\d+)', line)
                for ref in refs:
                    # Extract title
                    title_match = re.search(
                        rf'{re.escape(ref)}[:\s]+(.+?)(?:\s*\(|$)', line,
                    )
                    title = title_match.group(1).strip() if title_match else ref

                    # Extract assigned agent
                    assign_match = re.search(r'\((\w+)\)\s*$', line)
                    assigned = assign_match.group(1) if assign_match else ""

                    uuid = self._provider.find_issue_by_id(ref)
                    if uuid:
                        # Update state
                        states = self._provider._get_states()
                        state_id = find_state_id_for_status(states, current_status)
                        update_data: dict[str, Any] = {}
                        if state_id:
                            update_data["state_id"] = state_id
                        if assigned:
                            label_id = self._provider._get_label_id(f"agent::{assigned}")
                            if label_id:
                                update_data["label_ids"] = [label_id]
                        if update_data:
                            self._provider.update_work_item(uuid, update_data)
                    else:
                        # Upsert: create missing work item
                        self._provider.create_work_item(
                            ref, title,
                            status=current_status,
                            assigned=assigned,
                        )
                        logger.info("Created missing item %s via upsert: %s", ref, title)

    def _apply_backlog_update(self, content: str, agent_id: str) -> None:
        """Parse backlog markdown and create/update work items in Plane."""
        current_priority = "medium"
        priority_map = {
            "CRITICAL": "critical", "HIGH": "high",
            "MEDIUM": "medium", "LOW": "low",
        }

        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            for key, prio in priority_map.items():
                if key in line and line.strip().startswith("##"):
                    current_priority = prio
                    break

            match = re.match(r'^###\s+((?:STORY|BUG)-\d+):\s*(.+)', line)
            if match:
                item_id = match.group(1)
                title = match.group(2).strip()

                status = "todo"
                assigned = ""
                i += 1
                while i < len(lines) and not lines[i].startswith("### ") and not lines[i].startswith("## "):
                    fl = lines[i]
                    sm = re.search(r'\*\*Status\*\*:\s*(.+)', fl)
                    if sm:
                        status = sm.group(1).strip().lower().replace(" ", "_")
                    am = re.search(r'\*\*Assigned\*\*:\s*(.+)', fl)
                    if am:
                        assigned = am.group(1).strip()
                    i += 1

                uuid = self._provider.find_issue_by_id(item_id)
                if uuid:
                    # Update existing
                    states = self._provider._get_states()
                    state_id = find_state_id_for_status(states, status)
                    update: dict[str, Any] = {
                        "priority": map_opensepia_priority(current_priority),
                    }
                    if state_id:
                        update["state_id"] = state_id
                    if assigned:
                        label_id = self._provider._get_label_id(f"agent::{assigned}")
                        if label_id:
                            update["label_ids"] = [label_id]
                    self._provider.update_work_item(uuid, update)
                else:
                    # Create new
                    self._provider.create_work_item(
                        item_id, title,
                        status=status,
                        priority=current_priority,
                        assigned=assigned,
                    )
                continue
            i += 1

    def _apply_inbox_message(self, path: str, content: str, from_agent: str) -> None:
        """Send an inbox message via Plane Page."""
        match = re.search(r'board/inbox/(\w+)\.md', path)
        if not match:
            return
        to_agent = match.group(1)
        page_name = f"inbox-{to_agent}"

        existing = self._provider.get_page_content(page_name)
        new_content = existing + "\n" + content if existing.strip() else content
        self._provider.update_page(page_name, new_content)

    def _apply_standup(self, content: str) -> None:
        """Accumulate standup entry and write to Plane Page."""
        self._standup_entries.append(content)

    # =====================================================================
    # Inbox
    # =====================================================================

    def get_inbox(self, agent_id: str) -> str:
        return self._get_inbox_text(agent_id)

    def archive_inbox(self, agent_id: str) -> None:
        """Archive and clear agent's inbox Page."""
        page_name = f"inbox-{agent_id}"
        content = self._provider.get_page_content(page_name)
        if content.strip():
            # Append to archive page
            archive_name = f"archive-{agent_id}"
            existing_archive = self._provider.get_page_content(archive_name)
            separator = f"\n\n---\n\n"
            new_archive = existing_archive + separator + content if existing_archive.strip() else content
            self._provider.update_page(archive_name, new_archive)

            # Clear inbox
            self._provider.update_page(page_name, "")
            self._client.cache.invalidate_prefix("pages")

    # =====================================================================
    # Standup
    # =====================================================================

    def init_standup(self, sprint_num: int, cycle_num: int) -> None:
        """Initialize standup for a new cycle."""
        self._standup_entries = [f"# Standup — Sprint {sprint_num}, Cycle {cycle_num}\n"]
        page_name = f"standup-s{sprint_num}-c{cycle_num}"
        self._provider.update_page(page_name, self._standup_entries[0])

    # =====================================================================
    # Board readiness
    # =====================================================================

    def ensure_board_ready(self, agents_config: dict | None = None) -> None:
        """Ensure Plane project is set up with required infrastructure."""
        # Verify connectivity
        result = self._client.api("GET", "/states/")
        if isinstance(result, dict) and "error" in result:
            logger.warning("Plane.so not reachable: %s", result)
            return

        # Set up states and labels
        self._provider.init()

        # Ensure inbox pages exist for all agents
        if agents_config:
            for agent_id in agents_config.get("agents", {}):
                page_name = f"inbox-{agent_id}"
                if not self._provider.get_page(page_name):
                    self._provider.create_page(page_name, "")

        # Ensure documentation pages exist
        for page_name in ["project-description", "architecture", "decisions"]:
            if not self._provider.get_page(page_name):
                self._provider.create_page(page_name, "")

    # =====================================================================
    # Text exports
    # =====================================================================

    def get_sprint_text(self) -> str:
        return self._build_sprint_md(1)  # Sprint num filled from board

    def get_backlog_text(self) -> str:
        return self._build_backlog_md()

    def get_standup_text(self) -> str:
        if self._standup_entries:
            return "\n".join(self._standup_entries)
        return ""

    # =====================================================================
    # Analytics
    # =====================================================================

    def get_sprint_number(self) -> int:
        """Get sprint number from active Plane Cycle or default."""
        cycle = self._provider.get_active_cycle()
        if cycle:
            name = cycle.get("name", "")
            match = re.search(r'Sprint\s+(\d+)', name)
            if match:
                return int(match.group(1))
        return 1

    def get_active_story_ids(self) -> list[str]:
        """Get IDs of stories in active statuses."""
        board = self._provider.get_board_state()
        ids: list[str] = []
        for status in ("todo", "in_progress", "review", "testing", "blocked"):
            for item in board.get(status, []):
                item_id = item.get("id", "")
                if item_id and re.match(r'(?:STORY|BUG)-\d+', item_id):
                    ids.append(item_id)
        return ids

    def get_board_summary(self) -> dict[str, int]:
        """Count work items by status."""
        board = self._provider.get_board_state()
        return {status: len(items) for status, items in board.items()}

    def check_board_health(self) -> dict[str, bool]:
        """Check Plane.so connectivity and project setup."""
        result = self._client.api("GET", "/states/")
        api_ok = not (isinstance(result, dict) and "error" in result)

        states = self._provider._get_states() if api_ok else []
        has_states = len(states) >= 3

        board = self._provider.get_board_state() if api_ok else {}
        has_items = sum(len(v) for v in board.values()) > 0

        return {
            "api_reachable": api_ok,
            "states_configured": has_states,
            "has_work_items": has_items,
        }

    # =====================================================================
    # Snapshot
    # =====================================================================

    def create_snapshot(self) -> int:
        """Create a snapshot of current board state as a Plane Page."""
        import json
        from datetime import datetime

        board = self._provider.get_board_state()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        snapshot_content = f"# Board Snapshot — {timestamp}\n\n"
        snapshot_content += f"```json\n{json.dumps(board, indent=2)}\n```"

        page_name = f"snapshot-{timestamp}"
        self._provider.create_page(page_name, snapshot_content)

        return sum(len(items) for items in board.values())

    # =====================================================================
    # Messaging
    # =====================================================================

    def send_inbox_message(self, to_agent: str, from_name: str, message: str) -> None:
        """Send a message to an agent's Plane inbox Page."""
        page_name = f"inbox-{to_agent}"
        existing = self._provider.get_page_content(page_name)

        formatted = f"\n## Message from {from_name}\n{message}\n"
        new_content = existing + formatted if existing.strip() else formatted
        self._provider.update_page(page_name, new_content)
