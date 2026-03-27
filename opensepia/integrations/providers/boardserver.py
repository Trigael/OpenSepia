"""
AI Dev Team — Board Server Provider

BoardProvider implementation for the self-hosted Board Server.
Connects to the board server REST API for issue management,
comments, and inbox messaging.

The board server doesn't manage git/MRs — those methods are no-ops.
"""

import logging
import os
from typing import Any, Optional

from opensepia.config import HTTP_REQUEST_TIMEOUT
from ..base import BoardProvider, BOARD_LABELS, PRIORITY_LABELS
from .http_mixin import HTTPMixin, build_url

logger = logging.getLogger(__name__)


class BoardServerConfig:
    def __init__(self):
        self.url = os.getenv("BOARD_SERVER_URL", "").rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.url)

    @property
    def api_base(self) -> str:
        return f"{self.url}/api"


def _boardserver_headers(agent_id: str = "opensepia") -> dict:
    """Build board-server-specific request headers."""
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Id": agent_id,
    }
    token = os.environ.get("BOARD_SERVER_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_call(
    config: BoardServerConfig,
    method: str,
    endpoint: str,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
    agent_id: str = "opensepia",
):
    """Perform an API call to the board server."""
    url = build_url(config.api_base, endpoint, params)
    return HTTPMixin._http_request(
        url,
        method=method,
        headers=_boardserver_headers(agent_id),
        data=data,
        timeout=HTTP_REQUEST_TIMEOUT,
    )


class BoardServerProvider(BoardProvider):
    """Board Server implementation of BoardProvider."""

    def __init__(self, config: Optional[BoardServerConfig] = None) -> None:
        self.config = config or BoardServerConfig()
        self._issue_cache: dict[str, str] = {}  # story_id -> prefix_id

    @property
    def name(self) -> str:
        return "boardserver"

    @property
    def enabled(self) -> bool:
        return self.config.is_configured

    def init(self) -> None:
        """No initialization needed — board server manages its own schema."""
        if not self.enabled:
            logger.warning("Board Server is not configured — skipping")
            return
        logger.info("Board Server provider ready: %s", self.config.url)

    def clear_cache(self) -> None:
        self._issue_cache = {}

    # ----- Issues -----

    def create_issue(self, title: str, description: str,
                     labels: list = None, **kwargs) -> dict:
        # Determine type from labels
        is_bug = labels and "type::bug" in labels
        item_type = "bug" if is_bug else "story"

        # Extract status and priority from labels
        status = "todo"
        priority = "medium"
        if labels:
            for label in labels:
                for key, val in BOARD_LABELS.items():
                    if label == val:
                        status = key
                for key, val in PRIORITY_LABELS.items():
                    if label == val:
                        priority = key

        data = {
            "type": item_type,
            "title": title,
            "description": description,
            "status": status,
            "priority": priority if item_type == "story" else None,
        }
        if item_type == "bug":
            data["severity"] = priority

        # Clean None values
        data = {k: v for k, v in data.items() if v is not None}

        result = _api_call(self.config, "POST", "/items", data=data)
        if "error" not in result:
            # Map to GitLab-compatible format
            result["iid"] = result.get("id")
            # Cache the mapping
            prefix_id = result.get("id", "")
            if prefix_id:
                self._issue_cache[prefix_id] = prefix_id
            logger.info("Issue %s created: %s", result.get("id"), title)
        return result

    def close_issue(self, issue_id: Any) -> dict:
        return _api_call(self.config, "PATCH", f"/items/{issue_id}",
                         data={"status": "done"})

    def reopen_issue(self, issue_id: Any) -> dict:
        return _api_call(self.config, "PATCH", f"/items/{issue_id}",
                         data={"status": "todo"})

    def update_issue_labels(self, issue_id: Any, labels: list[str]) -> dict:
        # Translate labels to field updates
        updates = {}
        for label in labels:
            for key, val in BOARD_LABELS.items():
                if label == val:
                    updates["status"] = key
            for key, val in PRIORITY_LABELS.items():
                if label == val:
                    updates["priority"] = key
        if updates:
            return _api_call(self.config, "PATCH", f"/items/{issue_id}", data=updates)
        return {"status": "ok"}

    def update_issue_status(self, issue_id: Any, from_status: str,
                            to_status: str) -> dict:
        result = _api_call(self.config, "PATCH", f"/items/{issue_id}",
                           data={"status": to_status})
        if "error" not in result:
            logger.info("Issue %s: %s -> %s", issue_id, from_status, to_status)
        return result

    def comment_on_issue(self, issue_id: Any, agent_id: str,
                         message: str) -> dict:
        body = self._format_agent_comment(agent_id, message)
        return _api_call(self.config, "POST", f"/items/{issue_id}/comments",
                         data={"body": body}, agent_id=agent_id)

    def find_issue_by_id(self, story_id: str) -> Optional[str]:
        # Check cache
        if story_id in self._issue_cache:
            return self._issue_cache[story_id]

        # The story_id IS the prefix_id on board server (STORY-001)
        item = _api_call(self.config, "GET", f"/items/{story_id}")
        if "error" not in item:
            self._issue_cache[story_id] = story_id
            return story_id

        # Search by title pattern [STORY-001]
        items = _api_call(self.config, "GET", "/items")
        if isinstance(items, list):
            for item in items:
                title = item.get("title", "")
                if f"[{story_id}]" in title:
                    prefix_id = item.get("id", "")
                    self._issue_cache[story_id] = prefix_id
                    return prefix_id

        return None

    def list_issues(self, labels: str = None,
                    state: str = "opened") -> list:
        params = {}
        if labels:
            # Translate label to status filter
            for key, val in BOARD_LABELS.items():
                if labels == val:
                    params["status"] = key
                    break

        result = _api_call(self.config, "GET", "/items", params=params)
        if not isinstance(result, list):
            return []

        # Filter by state
        if state == "closed":
            result = [i for i in result if i.get("status") == "done"]
        elif state == "opened":
            result = [i for i in result if i.get("status") != "done"]

        # Map to GitLab-compatible format
        for item in result:
            item["iid"] = item.get("id")
            # Translate status to labels
            status = item.get("status", "")
            priority = item.get("priority", item.get("severity", ""))
            item["labels"] = []
            if status and status in BOARD_LABELS:
                item["labels"].append(BOARD_LABELS[status])
            if priority and priority in PRIORITY_LABELS:
                item["labels"].append(PRIORITY_LABELS[priority])
            if item.get("type") == "bug":
                item["labels"].append("type::bug")
            # Map state
            item["state"] = "closed" if status == "done" else "opened"

        return result

    def search_issues(self, query: str,
                      state: str = "opened") -> list:
        items = self.list_issues(state=state)
        q = query.lower()
        return [i for i in items if q in i.get("title", "").lower() or q in i.get("id", "").lower()]

    def get_issue_comments(self, issue_id: Any,
                           limit: int = 10) -> list:
        result = _api_call(self.config, "GET", f"/items/{issue_id}/comments")
        if not isinstance(result, list):
            return []
        # Map to GitLab-compatible format
        comments = []
        for c in result[-limit:]:
            comments.append({
                "id": c.get("id"),
                "body": c.get("body", ""),
                "author": {"name": c.get("author", "?")},
                "created_at": c.get("created_at", ""),
                "system": False,
            })
        return comments

    # ----- Board -----

    def get_board_state(self) -> dict:
        result = _api_call(self.config, "GET", "/board")
        if isinstance(result, dict) and "error" not in result:
            return result
        return {}

    def get_board_summary_md(self) -> str:
        board = self.get_board_state()
        if not board:
            return "(Board Server not available)"

        status_names = {
            "todo": "TODO", "in_progress": "IN PROGRESS",
            "review": "REVIEW", "testing": "TESTING",
            "done": "DONE", "blocked": "BLOCKED",
        }

        lines = ["## Board\n"]
        for status_key, display_name in status_names.items():
            items = board.get(status_key, [])
            lines.append(f"### {display_name} ({len(items)})")
            if items:
                for i in items:
                    priority = i.get("priority", i.get("severity", ""))
                    lines.append(f"- **{i.get('id')}** {i.get('title', '?')} [{priority}]")
            else:
                lines.append("_(empty)_")
            lines.append("")

        return "\n".join(lines)

    # ----- MR / PR (not supported — board server doesn't manage git) -----

    def create_mr(self, source_branch: str, target_branch: str,
                  title: str, description: str = "") -> dict:
        return {"error": "not_supported", "message": "Board Server does not manage merge requests"}

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
        return "_(Board Server does not manage merge requests)_"

    def get_mr_changes(self, mr_id: Any) -> dict:
        return {"error": "not_supported"}

    def get_mr_approvals(self, mr_id: Any) -> dict:
        return {"approved": False, "error": "not_supported"}
