"""
AI Dev Team — Plane.so Provider

BoardProvider implementation for Plane.so API v1.
Uses work-items (not deprecated issues endpoint), cycles for sprints,
pages for documentation, and states for workflow.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..base import BoardProvider, BOARD_LABELS, PRIORITY_LABELS
from .plane_client import PlaneClient, PlaneConfig
from .plane_mapping import (
    map_plane_state_to_status,
    find_state_id_for_status,
    map_plane_priority,
    map_opensepia_priority,
    extract_story_id_from_title,
    build_title,
    strip_title_prefix,
    STATUS_TO_STATE_NAME,
)

logger = logging.getLogger(__name__)


# Labels to create during init
AGENT_LABELS = [
    "agent::po", "agent::pm", "agent::dev1", "agent::dev2",
    "agent::devops", "agent::tester",
    "agent::sec_analyst", "agent::sec_engineer", "agent::sec_pentester",
]
TYPE_LABELS = ["type::story", "type::bug"]


class PlaneProvider(BoardProvider):
    """Board provider backed by Plane.so REST API."""

    def __init__(self, config: Optional[PlaneConfig] = None):
        self._config = config or PlaneConfig.from_env()
        self._client = PlaneClient(self._config)
        self._issue_cache: dict[str, str] = {}  # story_id -> work_item UUID

    # ----- Properties -----

    @property
    def name(self) -> str:
        return "plane"

    @property
    def enabled(self) -> bool:
        return self._config.is_configured

    @property
    def client(self) -> PlaneClient:
        return self._client

    # ----- Init / Setup -----

    def init(self) -> None:
        """Set up Plane project with required states, labels."""
        self._ensure_states()
        self._ensure_labels()

    def _ensure_states(self) -> None:
        """Create required workflow states if they don't exist."""
        existing = self._get_states()
        existing_names = {s.get("name", "").lower() for s in existing}

        for status, (state_name, state_group) in STATUS_TO_STATE_NAME.items():
            if state_name.lower() not in existing_names:
                result = self._client.api("POST", "/states/", data={
                    "name": state_name,
                    "group": state_group,
                    "color": "#6B7280",
                })
                if isinstance(result, dict) and "error" not in result:
                    logger.info("Plane: created state '%s' (group: %s)", state_name, state_group)
                    self._client.cache.invalidate("states")
                else:
                    logger.debug("Plane: state '%s' may already exist: %s", state_name, result)

    def _ensure_labels(self) -> None:
        """Create required labels if they don't exist."""
        existing = self._get_labels()
        existing_names = {l.get("name", "").lower() for l in existing}

        all_labels = (
            list(BOARD_LABELS.values()) +
            list(PRIORITY_LABELS.values()) +
            AGENT_LABELS + TYPE_LABELS
        )

        for label_name in all_labels:
            if label_name.lower() not in existing_names:
                result = self._client.api("POST", "/labels/", data={
                    "name": label_name,
                    "color": "#6B7280",
                })
                if isinstance(result, dict) and "error" not in result:
                    logger.debug("Plane: created label '%s'", label_name)
                    self._client.cache.invalidate("labels")

    # ----- Data fetching (cached) -----

    def _get_states(self) -> list[dict]:
        result = self._client.get_cached("states", "/states/")
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []

    def _get_labels(self) -> list[dict]:
        result = self._client.get_cached("labels", "/labels/")
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []

    def _get_label_id(self, label_name: str) -> Optional[str]:
        labels = self._get_labels()
        for label in labels:
            if label.get("name", "").lower() == label_name.lower():
                return label.get("id")
        return None

    def _get_members(self) -> list[dict]:
        result = self._client.get_cached("members", "/members/")
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []

    # ----- Cycles (Sprints) -----

    def get_or_create_cycle(self, sprint_num: int) -> Optional[str]:
        """Find or create a Plane Cycle for the given sprint number.
        Returns the cycle UUID or None.
        """
        cycle_name = f"Sprint {sprint_num}"
        cycles = self._get_cycles()

        for cycle in cycles:
            if cycle.get("name", "").strip() == cycle_name:
                return cycle["id"]

        result = self._client.api("POST", "/cycles/", data={
            "name": cycle_name,
        })
        if isinstance(result, dict) and "error" not in result:
            self._client.cache.invalidate("cycles")
            logger.info("Plane: created cycle '%s'", cycle_name)
            return result.get("id")

        logger.warning("Plane: failed to create cycle '%s': %s", cycle_name, result)
        return None

    def _get_cycles(self) -> list[dict]:
        result = self._client.get_cached("cycles", "/cycles/")
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []

    def get_active_cycle(self) -> Optional[dict]:
        """Get the most recent (active) cycle."""
        cycles = self._get_cycles()
        if not cycles:
            return None
        # Return the last one (most recent)
        return cycles[-1] if cycles else None

    def assign_to_cycle(self, work_item_id: str, cycle_id: str) -> dict:
        """Add a work item to a cycle."""
        return self._client.api("POST", f"/cycles/{cycle_id}/cycle-issues/", data={
            "issues": [work_item_id],
        })

    # ----- Pages (Documentation) -----

    def get_page(self, name: str) -> Optional[dict]:
        """Get a page by name. Returns the page dict or None."""
        pages = self._list_pages()
        for page in pages:
            if page.get("name", "").strip().lower() == name.lower():
                return page
        return None

    def get_page_content(self, name: str) -> str:
        """Get a page's description/content by name."""
        page = self.get_page(name)
        if not page:
            return ""
        return page.get("description_html", page.get("description", ""))

    def create_page(self, name: str, content: str) -> dict:
        """Create a new page."""
        result = self._client.api("POST", "/pages/", data={
            "name": name,
            "description": content,
            "access": 0,  # public within project
        })
        self._client.cache.invalidate("pages")
        return result if isinstance(result, dict) else {}

    def update_page(self, name: str, content: str) -> dict:
        """Update a page's content. Creates if it doesn't exist."""
        page = self.get_page(name)
        if page:
            result = self._client.api("PATCH", f"/pages/{page['id']}/", data={
                "description": content,
            })
            self._client.cache.invalidate("pages")
            return result if isinstance(result, dict) else {}
        return self.create_page(name, content)

    def _list_pages(self) -> list[dict]:
        result = self._client.get_cached("pages", "/pages/")
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []

    # ----- Issues (Work Items) -----

    def create_issue(
        self, title: str, description: str,
        labels: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a work item in Plane."""
        data: dict[str, Any] = {
            "name": title,
            "description_html": f"<p>{description}</p>",
        }

        # Set state
        state_label = None
        label_ids = []
        if labels:
            for lbl in labels:
                if lbl.startswith("status::"):
                    status = lbl.replace("status::", "").replace("-", "_")
                    state_label = status
                lid = self._get_label_id(lbl)
                if lid:
                    label_ids.append(lid)

        if state_label:
            states = self._get_states()
            state_id = find_state_id_for_status(states, state_label)
            if state_id:
                data["state_id"] = state_id

        if label_ids:
            data["label_ids"] = label_ids

        # Priority
        priority = kwargs.get("priority")
        if priority and isinstance(priority, str):
            data["priority"] = map_opensepia_priority(priority)

        result = self._client.api("POST", "/work-items/", data=data)
        self._client.cache.invalidate_prefix("work_items")

        if isinstance(result, dict) and "error" not in result:
            # Cache the mapping
            story_id = extract_story_id_from_title(title)
            if story_id and "id" in result:
                self._issue_cache[story_id] = result["id"]
            return {"iid": result.get("id", ""), **result}

        return result if isinstance(result, dict) else {"error": "unexpected"}

    def close_issue(self, issue_id: Any) -> dict[str, Any]:
        """Move work item to completed state."""
        states = self._get_states()
        state_id = find_state_id_for_status(states, "done")
        if not state_id:
            return {"error": "no 'done' state found"}
        result = self._client.api("PATCH", f"/work-items/{issue_id}/", data={
            "state_id": state_id,
        })
        self._client.cache.invalidate_prefix("work_items")
        return result if isinstance(result, dict) else {}

    def reopen_issue(self, issue_id: Any) -> dict[str, Any]:
        """Move work item back to todo state."""
        states = self._get_states()
        state_id = find_state_id_for_status(states, "todo")
        if not state_id:
            return {"error": "no 'todo' state found"}
        result = self._client.api("PATCH", f"/work-items/{issue_id}/", data={
            "state_id": state_id,
        })
        self._client.cache.invalidate_prefix("work_items")
        return result if isinstance(result, dict) else {}

    def update_issue_labels(self, issue_id: Any, labels: list[str]) -> dict[str, Any]:
        """Update labels on a work item."""
        label_ids = []
        for lbl in labels:
            lid = self._get_label_id(lbl)
            if lid:
                label_ids.append(lid)
        result = self._client.api("PATCH", f"/work-items/{issue_id}/", data={
            "label_ids": label_ids,
        })
        self._client.cache.invalidate_prefix("work_items")
        return result if isinstance(result, dict) else {}

    def update_issue_status(
        self, issue_id: Any, from_status: str, to_status: str,
    ) -> dict[str, Any]:
        """Change work item state."""
        states = self._get_states()
        state_id = find_state_id_for_status(states, to_status)
        if not state_id:
            return {"error": f"no state found for '{to_status}'"}
        result = self._client.api("PATCH", f"/work-items/{issue_id}/", data={
            "state_id": state_id,
        })
        self._client.cache.invalidate_prefix("work_items")
        return result if isinstance(result, dict) else {}

    def comment_on_issue(
        self, issue_id: Any, agent_id: str, message: str,
    ) -> dict[str, Any]:
        """Post a comment on a work item."""
        formatted = self._format_agent_comment(agent_id, message)
        result = self._client.api(
            "POST", f"/work-items/{issue_id}/comments/",
            data={"comment_html": f"<p>{formatted}</p>"},
        )
        return result if isinstance(result, dict) else {}

    def find_issue_by_id(self, story_id: str) -> str | int | None:
        """Find Plane work item UUID by OpenSepia story ID (e.g., STORY-001)."""
        # Check cache first
        if story_id in self._issue_cache:
            return self._issue_cache[story_id]

        # Search work items
        items = self._list_work_items()
        for item in items:
            item_story_id = extract_story_id_from_title(item.get("name", ""))
            if item_story_id:
                self._issue_cache[item_story_id] = item["id"]
                if item_story_id == story_id:
                    return item["id"]
        return None

    def list_issues(
        self, labels: str | None = None, state: str = "opened",
    ) -> list[dict[str, Any]]:
        """List work items, optionally filtered."""
        items = self._list_work_items()

        # Map Plane state to open/closed for filtering
        states = self._get_states()
        state_map = {}
        for s in states:
            status = map_plane_state_to_status(s.get("name", ""), s.get("group", ""))
            state_map[s["id"]] = status

        result = []
        for item in items:
            item_status = state_map.get(item.get("state_id", item.get("state", "")), "todo")

            if state == "opened" and item_status == "done":
                continue
            if state == "closed" and item_status != "done":
                continue

            story_id = extract_story_id_from_title(item.get("name", ""))
            result.append({
                "iid": item.get("id", ""),
                "title": item.get("name", ""),
                "state": "closed" if item_status == "done" else "opened",
                "labels": [l.get("name", "") for l in item.get("labels", [])],
                "story_id": story_id,
                "status": item_status,
            })
        return result

    def search_issues(
        self, query: str, state: str = "opened",
    ) -> list[dict[str, Any]]:
        """Search work items by query string."""
        all_items = self.list_issues(state=state)
        query_lower = query.lower()
        return [
            item for item in all_items
            if query_lower in item.get("title", "").lower()
        ]

    def get_issue_comments(
        self, issue_id: Any, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch comments on a work item."""
        result = self._client.api("GET", f"/work-items/{issue_id}/comments/")
        comments = []
        if isinstance(result, list):
            comments = result
        elif isinstance(result, dict) and "results" in result:
            comments = result["results"]
        elif isinstance(result, dict) and "error" in result:
            return []

        formatted = []
        for c in comments[-limit:]:
            formatted.append({
                "body": c.get("comment_stripped", c.get("comment_html", "")),
                "author": {"name": c.get("actor_detail", {}).get("display_name", "User")},
                "created_at": c.get("created_at", ""),
                "system": False,
            })
        return formatted

    # ----- Board -----

    def get_board_state(self) -> dict[str, list[dict[str, Any]]]:
        """Get work items grouped by OpenSepia status."""
        items = self._list_work_items()
        states = self._get_states()
        state_map = {}
        for s in states:
            status = map_plane_state_to_status(s.get("name", ""), s.get("group", ""))
            state_map[s["id"]] = status

        board: dict[str, list[dict]] = {
            "todo": [], "in_progress": [], "review": [],
            "testing": [], "done": [], "blocked": [],
        }

        for item in items:
            status = state_map.get(item.get("state_id", item.get("state", "")), "todo")
            story_id = extract_story_id_from_title(item.get("name", ""))
            title = strip_title_prefix(item.get("name", ""))
            priority = map_plane_priority(item.get("priority"))

            # Determine assigned agent from labels
            assigned = ""
            item_labels = item.get("label_detail", item.get("labels", []))
            if isinstance(item_labels, list):
                for lbl in item_labels:
                    lbl_name = lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
                    if lbl_name.startswith("agent::"):
                        assigned = lbl_name.replace("agent::", "")
                        break

            entry = {
                "id": story_id or item.get("id", ""),
                "uuid": item.get("id", ""),
                "title": title,
                "status": status,
                "priority": priority,
                "assigned": assigned,
            }
            if status in board:
                board[status].append(entry)
            else:
                board["todo"].append(entry)

        return board

    def get_board_summary_md(self) -> str:
        """Format board state as markdown summary."""
        board = self.get_board_state()
        lines = ["## Board Summary"]
        for status, items in board.items():
            if items:
                lines.append(f"- **{status.upper()}**: {len(items)} items")
        return "\n".join(lines)

    # ----- MR / PR (not supported by Plane) -----

    def create_mr(self, source_branch: str, target_branch: str,
                  title: str, description: str = "") -> dict[str, Any]:
        return {"error": "not_supported", "message": "Plane.so does not manage MRs"}

    def list_mrs(self, state: str = "opened") -> list[dict[str, Any]]:
        return []

    def get_mr(self, mr_id: Any) -> dict[str, Any]:
        return {"error": "not_supported"}

    def comment_on_mr(self, mr_id: Any, body: str,
                      agent_id: str = "") -> dict[str, Any]:
        return {"error": "not_supported"}

    def approve_mr(self, mr_id: Any) -> dict[str, Any]:
        return {"error": "not_supported"}

    def merge_mr(self, mr_id: Any, squash: bool = False) -> dict[str, Any]:
        return {"error": "not_supported"}

    def close_mr(self, mr_id: Any) -> dict[str, Any]:
        return {"error": "not_supported"}

    def get_open_mrs_md(self) -> str:
        return ""

    def get_mr_changes(self, mr_id: Any) -> dict[str, Any]:
        return {"error": "not_supported"}

    def get_mr_approvals(self, mr_id: Any) -> dict[str, Any]:
        return {"approved": False, "error": "not_supported"}

    # ----- Cache -----

    def clear_cache(self) -> None:
        self._client.cache.clear()
        self._issue_cache.clear()

    # ----- Internal helpers -----

    def _list_work_items(self) -> list[dict]:
        """Get all work items (cached)."""
        result = self._client.get_cached(
            "work_items:all", "/work-items/", paginate=True,
        )
        return result if isinstance(result, list) else []

    def list_work_items_for_cycle(self, cycle_id: str) -> list[dict]:
        """Get work items assigned to a specific cycle."""
        cache_key = f"work_items:cycle:{cycle_id}"
        result = self._client.get_cached(
            cache_key, f"/cycles/{cycle_id}/cycle-issues/", paginate=True,
        )
        if isinstance(result, list):
            # Cycle issues endpoint returns issue details nested
            items = []
            for entry in result:
                if isinstance(entry, dict):
                    issue = entry.get("issue_detail", entry)
                    items.append(issue)
            return items
        return []

    def update_work_item(self, work_item_id: str, data: dict) -> dict:
        """Update a work item's fields."""
        result = self._client.api("PATCH", f"/work-items/{work_item_id}/", data=data)
        self._client.cache.invalidate_prefix("work_items")
        return result if isinstance(result, dict) else {}

    def create_work_item(
        self,
        story_id: str,
        title: str,
        status: str = "todo",
        priority: str = "medium",
        assigned: str = "",
    ) -> dict:
        """Create a work item with OpenSepia conventions."""
        full_title = build_title(story_id, title)
        states = self._get_states()
        state_id = find_state_id_for_status(states, status)

        data: dict[str, Any] = {
            "name": full_title,
            "priority": map_opensepia_priority(priority),
        }
        if state_id:
            data["state_id"] = state_id

        # Set agent label
        label_ids = []
        if assigned:
            lid = self._get_label_id(f"agent::{assigned}")
            if lid:
                label_ids.append(lid)

        # Set type label
        type_label = "type::bug" if story_id.startswith("BUG-") else "type::story"
        lid = self._get_label_id(type_label)
        if lid:
            label_ids.append(lid)

        if label_ids:
            data["label_ids"] = label_ids

        result = self._client.api("POST", "/work-items/", data=data)
        self._client.cache.invalidate_prefix("work_items")

        if isinstance(result, dict) and "error" not in result and "id" in result:
            self._issue_cache[story_id] = result["id"]

        return result if isinstance(result, dict) else {}
