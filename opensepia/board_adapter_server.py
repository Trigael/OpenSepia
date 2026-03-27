"""
AI Dev Team — Board Server Adapter.

Implements BoardAdapter against the board server REST API.
Translates between the agent's markdown-centric world and
the board server's structured item/inbox model.
"""

import os
import re
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any

from opensepia.board_adapter import BoardAdapter, AgentContext
from opensepia.agents.parser import ParsedFile
from opensepia.agents.workspace import get_workspace_tree
from opensepia.config import HTTP_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class BoardServerAdapter(BoardAdapter):
    """Board adapter backed by the board server REST API.

    Builds agent context by fetching items from the API and formatting
    them as markdown (same structure agents expect from local files).
    Parses agent output (board file writes) and translates them into
    API calls (create/update items, send inbox messages).
    """

    def __init__(
        self,
        server_url: str,
        workspace_dir: Path,
        project_dir: Path,
    ):
        self.server_url = server_url.rstrip("/")
        self.workspace_dir = workspace_dir
        self.project_dir = project_dir
        self._standup_entries: list[str] = []  # Accumulated per cycle

    def _api(self, method: str, path: str, data: dict | None = None,
             params: dict | None = None, agent: str = "opensepia") -> Any:
        """Call the board server API."""
        url = f"{self.server_url}/api{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        body = json.dumps(data).encode("utf-8") if data else None
        headers = {"Content-Type": "application/json", "X-Agent-Id": agent}
        token = os.environ.get("BOARD_SERVER_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            url, data=body, method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            error_code = e.code
            logger.debug("Board server API %s %s: HTTP %d", method, path, error_code)
            return {"error": error_code, "message": str(e)}
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Board server API %s %s: %s", method, path, e)
            return {"error": str(e)}

    # ----- Agent context -----

    def get_agent_context(self, agent_id: str, agents_config: dict, project_config: dict) -> AgentContext:
        sprint_cfg = project_config.get("sprint", {})
        sprint_num = sprint_cfg.get("current_sprint", 1)
        cycle_num = sprint_cfg.get("current_cycle", 0)

        # Build sprint markdown from board items
        sprint_md = self._build_sprint_md(sprint_num)

        # Build backlog markdown
        backlog_md = self._build_backlog_md()

        # Project description from config
        proj = project_config.get("project", {})
        project_desc = f"# {proj.get('name', 'Project')}\n\n{proj.get('description', '')}"

        # Standup (accumulated entries this cycle)
        standup = "\n".join(self._standup_entries) if self._standup_entries else ""

        # Inbox
        inbox = self._get_inbox_text(agent_id)

        # Workspace tree (filesystem — always local)
        workspace_tree = get_workspace_tree(self.workspace_dir)

        return AgentContext(
            project_description=project_desc,
            sprint_md=sprint_md,
            backlog_md=backlog_md,
            standup=standup,
            inbox=inbox,
            workspace_tree=workspace_tree,
            provider_comments="",  # Board server IS the provider
            sprint_num=sprint_num,
            cycle_num=cycle_num,
        )

    def _build_sprint_md(self, sprint_num: int) -> str:
        """Build sprint.md equivalent from board server items."""
        board = self._api("GET", "/board")
        if isinstance(board, dict) and "error" in board:
            return "# Sprint (unavailable)\n"

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
                    # Clean provider prefix from title
                    title = re.sub(r'^\[(?:STORY|BUG)-\d+\]\s*', '', title)
                    assigned = item.get("assigned", "")
                    assigned_str = f" ({assigned})" if assigned else ""
                    checkbox = "[x]" if status_key == "done" else "[ ]"
                    lines.append(f"- {checkbox} {item_id}: {title}{assigned_str}")
            lines.append("")

        return "\n".join(lines)

    def _build_backlog_md(self) -> str:
        """Build backlog.md equivalent from board server items."""
        items = self._api("GET", "/items")
        if not isinstance(items, list):
            return "# Backlog\n"

        # Group by priority
        by_priority: dict[str, list] = {"critical": [], "high": [], "medium": [], "low": []}
        for item in items:
            prio = item.get("priority", item.get("severity", "medium"))
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
                title = re.sub(r'^\[(?:STORY|BUG)-\d+\]\s*', '', title)
                status = item.get("status", "todo")
                assigned = item.get("assigned", "")
                lines.append(f"### {item_id}: {title}")
                lines.append(f"**Priority**: {prio.upper()}")
                lines.append(f"**Status**: {status.upper()}")
                if assigned:
                    lines.append(f"**Assigned**: {assigned}")
                lines.append("")

        return "\n".join(lines)

    def _get_inbox_text(self, agent_id: str) -> str:
        """Get inbox messages as markdown text."""
        messages = self._api("GET", f"/inbox/{agent_id}")
        if not isinstance(messages, list) or not messages:
            return ""

        lines = []
        for msg in messages:
            from_agent = msg.get("from_agent", "system")
            body = msg.get("message", "")
            lines.append(f"## Message from {from_agent}")
            lines.append(body)
            lines.append("")

        return "\n".join(lines)

    # ----- Agent output -----

    def apply_agent_output(self, agent_id: str, files: list[ParsedFile], agents_config: dict) -> int:
        """Parse agent file output and translate to board server API calls."""
        written = 0
        resolved_base = self.project_dir.resolve()

        for pf in files:
            if not pf.path or not pf.content:
                continue

            # Route based on file path
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
                self._standup_entries.append(pf.content)
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
                # Other board files (architecture.md, decisions.md, project.md)
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

        return written

    def _apply_sprint_update(self, content: str, agent_id: str) -> None:
        """Parse sprint markdown and update item statuses on board server."""
        # Parse status sections
        status_map = {
            "todo": "todo", "in progress": "in_progress", "in_progress": "in_progress",
            "review": "review", "testing": "testing",
            "done": "done", "blocked": "blocked",
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
                    # Extract title from line: "- [ ] STORY-001: Title here (dev1)"
                    title_match = re.search(rf'{re.escape(ref)}[:\s]+(.+?)(?:\s*\(|$)', line)
                    title = title_match.group(1).strip() if title_match else ref

                    result = self._api("PATCH", f"/items/{ref}",
                                       data={"status": current_status}, agent=agent_id)

                    # Upsert: if item doesn't exist (404), create it
                    if isinstance(result, dict) and result.get("error") == 404:
                        item_type = "bug" if ref.startswith("BUG-") else "story"
                        self._api("POST", "/items", data={
                            "type": item_type,
                            "title": title,
                            "status": current_status,
                        }, agent=agent_id)
                        logger.info("Created missing item %s via upsert: %s", ref, title)

    def _apply_backlog_update(self, content: str, agent_id: str) -> None:
        """Parse backlog markdown and create/update items on board server."""
        existing = self._api("GET", "/items")
        existing_ids = set()
        if isinstance(existing, list):
            existing_ids = {i.get("id", "") for i in existing}

        current_priority = "medium"
        priority_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}

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

                # Collect fields
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

                if item_id not in existing_ids:
                    # Create new item
                    item_type = "bug" if item_id.startswith("BUG-") else "story"
                    data: dict[str, Any] = {
                        "type": item_type,
                        "title": title,
                        "status": status,
                        "priority": current_priority,
                        "sprint": 1,
                    }
                    if assigned:
                        data["assigned"] = assigned
                    self._api("POST", "/items", data=data, agent=agent_id)
                else:
                    # Update existing
                    update: dict[str, Any] = {"status": status, "priority": current_priority}
                    if assigned:
                        update["assigned"] = assigned
                    self._api("PATCH", f"/items/{item_id}", data=update, agent=agent_id)
                continue
            i += 1

    def _apply_inbox_message(self, path: str, content: str, from_agent: str) -> None:
        """Send an inbox message to the board server."""
        # Extract target agent from path: board/inbox/dev1.md -> dev1
        match = re.search(r'board/inbox/(\w+)\.md', path)
        if not match:
            return
        to_agent = match.group(1)
        self._api("POST", f"/inbox/{to_agent}",
                  data={"message": content}, agent=from_agent)

    # ----- Inbox -----

    def get_inbox(self, agent_id: str) -> str:
        return self._get_inbox_text(agent_id)

    def archive_inbox(self, agent_id: str) -> None:
        self._api("DELETE", f"/inbox/{agent_id}", agent=agent_id)

    # ----- Standup -----

    def init_standup(self, sprint_num: int, cycle_num: int) -> None:
        self._standup_entries = [f"# Standup — Sprint {sprint_num}, Cycle {cycle_num}\n"]

    # ----- Board readiness -----

    def ensure_board_ready(self, agents_config: dict | None = None) -> None:
        # Board server is always ready — just verify it's reachable
        result = self._api("GET", "/schema")
        if isinstance(result, dict) and "error" in result:
            logger.warning("Board server not reachable: %s", result)

    # ----- New adapter methods -----

    def get_sprint_text(self) -> str:
        sprint_num = 1  # Will be overridden by project config when available
        return self._build_sprint_md(sprint_num)

    def get_backlog_text(self) -> str:
        return self._build_backlog_md()

    def get_standup_text(self) -> str:
        return "\n".join(self._standup_entries) if self._standup_entries else ""

    def get_sprint_number(self) -> int:
        # Board server doesn't store sprint number — rely on items or default
        return 1

    def get_active_story_ids(self) -> list[str]:
        """GET items with active status filter."""
        ids: list[str] = []
        for status in ("todo", "in_progress", "review", "testing"):
            items = self._api("GET", "/items", params={"status": status})
            if isinstance(items, list):
                for item in items:
                    item_id = item.get("id", "")
                    if item_id:
                        ids.append(item_id)
        return ids

    def get_board_summary(self) -> dict[str, int]:
        """GET /board and count items per status."""
        board = self._api("GET", "/board")
        if isinstance(board, dict) and "error" in board:
            return {}
        summary: dict[str, int] = {}
        if isinstance(board, dict):
            for status_key, items in board.items():
                if isinstance(items, list):
                    summary[status_key] = len(items)
        return summary

    def check_board_health(self) -> dict[str, bool]:
        """Ping /api/schema to check if the server is reachable."""
        result = self._api("GET", "/schema")
        ok = isinstance(result, dict) and "error" not in result
        return {"server_reachable": ok}

    def create_snapshot(self) -> int:
        """No-op for board server — server manages its own state."""
        return 0

    def send_inbox_message(self, to_agent: str, from_name: str, message: str) -> None:
        """POST a message to the board server inbox."""
        self._api("POST", f"/inbox/{to_agent}",
                  data={"message": message}, agent=from_name)
