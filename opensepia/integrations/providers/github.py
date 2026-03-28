#!/usr/bin/env python3
"""
AI Dev Team — GitHub Provider
BoardProvider implementation for GitHub REST API v3.
Issues = stories/bugs, Pull Requests = merge requests.
Labels for board state (same conventions as GitLab).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any

from opensepia.config import PROVIDER_API_TIMEOUT
from ..base import (
    BoardProvider, BOARD_LABELS, PRIORITY_LABELS, ROLE_LABELS,
)
from .http_mixin import HTTPMixin, build_url

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================
class GitHubConfig:
    def __init__(self) -> None:
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.owner = os.getenv("GITHUB_OWNER", "")
        self.repo = os.getenv("GITHUB_REPO", "")
        self.api_url = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

    @property
    def api_base(self) -> str:
        return f"{self.api_url}/repos/{self.owner}/{self.repo}"

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.owner and self.repo)


# =============================================================================
# HTTP helper
# =============================================================================
def _github_headers(config: GitHubConfig) -> dict[str, str]:
    """Build GitHub-specific request headers."""
    return {
        "Authorization": f"Bearer {config.token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _api_call(config: GitHubConfig, method: str, endpoint: str,
              data: dict[str, Any] | None = None, params: dict[str, Any] | None = None,
              _max_retries: int = 4) -> Any:
    """Perform an API call to GitHub with retry on rate limit (403/429)."""
    url = build_url(config.api_base, endpoint, params)
    return HTTPMixin._http_request_with_retry(
        url,
        method=method,
        headers=_github_headers(config),
        data=data,
        timeout=PROVIDER_API_TIMEOUT,
        max_retries=_max_retries,
        retry_on=(403, 429),
    )


# =============================================================================
# Label colors (GitHub-specific — hex without #)
# =============================================================================
GITHUB_LABEL_COLORS = {
    "status::todo":        "428BCA",
    "status::in-progress": "F0AD4E",
    "status::review":      "8E44AD",
    "status::testing":     "E67E22",
    "status::done":        "5CB85C",
    "status::blocked":     "D9534F",
    "role::product-owner":  "9B59B6",
    "role::project-manager": "3498DB",
    "role::developer":      "2ECC71",
    "role::devops":         "E67E22",
    "role::tester":         "E74C3C",
    "priority::critical":   "D9534F",
    "priority::high":       "F0AD4E",
    "priority::medium":     "F7DC6F",
    "priority::low":        "5CB85C",
    "type::bug":            "D93F0B",
}


def ensure_labels(config: GitHubConfig) -> None:
    """Create all required labels if they do not exist."""
    # Load existing labels (paginated)
    existing_names: set[str] = set()
    page = 1
    while True:
        result = _api_call(config, "GET", "/labels",
                           params={"per_page": 100, "page": page})
        if not isinstance(result, list) or not result:
            break
        existing_names.update(l["name"] for l in result)
        if len(result) < 100:
            break
        page += 1

    for label_name, color in GITHUB_LABEL_COLORS.items():
        if label_name not in existing_names:
            result = _api_call(config, "POST", "/labels", data={
                "name": label_name,
                "color": color,
            })
            if "error" not in result:
                logger.info(f"Label created: {label_name}")
            else:
                logger.warning(f"Label {label_name}: {result}")


# =============================================================================
# GitHubProvider
# =============================================================================
class GitHubProvider(BoardProvider):
    """GitHub implementation of BoardProvider."""

    CACHE_TTL_SECONDS = 300  # 5 minutes

    def __init__(self, config: GitHubConfig | None = None) -> None:
        self.config = config or GitHubConfig()
        self._issue_cache: dict[str, int] = {}
        self._cache_timestamps: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "github"

    @property
    def enabled(self) -> bool:
        return self.config.is_configured

    def init(self) -> None:
        if not self.enabled:
            logger.warning("GitHub is not configured — skipping")
            return
        ensure_labels(self.config)
        logger.info("GitHub labels initialized")

    # ----- Cache management -----

    def clear_cache(self) -> None:
        """Clear the in-memory story-id → issue-number cache.

        Call after bulk operations (board sync, restore) or when a cached
        number is suspected stale (e.g. issue was deleted).
        """
        self._issue_cache = {}
        self._cache_timestamps = {}

    # ----- Issues -----

    def create_issue(self, title: str, description: str,
                     labels: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        data = {"title": title, "body": description}
        if labels:
            data["labels"] = labels  # type: ignore[assignment]  # GitHub accepts a list directly

        result = _api_call(self.config, "POST", "/issues", data=data)
        if "error" not in result:
            # Map GitHub "number" to "iid" for compatibility
            result["iid"] = result.get("number")
            logger.info(f"Issue #{result.get('number')} created: {title}")
        return result

    def close_issue(self, issue_id: Any) -> dict[str, Any]:
        return _api_call(self.config, "PATCH", f"/issues/{issue_id}",
                         data={"state": "closed"})

    def reopen_issue(self, issue_id: Any) -> dict[str, Any]:
        return _api_call(self.config, "PATCH", f"/issues/{issue_id}",
                         data={"state": "open"})

    def update_issue_labels(self, issue_id: Any, labels: list[str]) -> dict[str, Any]:
        return _api_call(self.config, "PATCH", f"/issues/{issue_id}",
                         data={"labels": labels})

    def update_issue_status(self, issue_id: Any, from_status: str,
                            to_status: str) -> dict[str, Any]:
        # Load current labels
        issue = _api_call(self.config, "GET", f"/issues/{issue_id}")
        if "error" in issue:
            return issue

        current_labels = [l["name"] for l in issue.get("labels", [])]

        # Remove old status label
        from_label = BOARD_LABELS.get(from_status)
        if from_label and from_label in current_labels:
            current_labels.remove(from_label)

        # Add new status label
        to_label = BOARD_LABELS.get(to_status)
        if to_label and to_label not in current_labels:
            current_labels.append(to_label)

        result = _api_call(self.config, "PATCH", f"/issues/{issue_id}",
                           data={"labels": current_labels})
        if "error" not in result:
            logger.info(f"Issue #{issue_id}: {from_status} → {to_status}")
        return result

    def comment_on_issue(self, issue_id: Any, agent_id: str,
                         message: str) -> dict[str, Any]:
        body = self._format_agent_comment(agent_id, message)
        return _api_call(self.config, "POST",
                         f"/issues/{issue_id}/comments",
                         data={"body": body})

    def find_issue_by_id(self, story_id: str) -> int | None:
        # 1) In-memory cache (with TTL)
        if story_id in self._issue_cache:
            cached_at = self._cache_timestamps.get(story_id, 0)
            if time.time() - cached_at < self.CACHE_TTL_SECONDS:
                return self._issue_cache[story_id]
            # Expired — remove stale entry
            del self._issue_cache[story_id]
            self._cache_timestamps.pop(story_id, None)

        # 2) File cache
        import json as _json
        from opensepia.dirs import get_tool_dir
        cache_path = get_tool_dir() / "project" / "board" / ".github_issue_map.json"
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                file_cache = _json.load(f)
            if story_id in file_cache:
                num = file_cache[story_id]
                self._issue_cache[story_id] = num
                self._cache_timestamps[story_id] = time.time()
                return num
        except (FileNotFoundError, _json.JSONDecodeError, KeyError):
            pass

        # 3) API search
        issues = self.search_issues(f"[{story_id}]")
        for issue in issues:
            title = issue.get("title", "")
            if f"[{story_id}]" in title:
                num = issue["number"]
                self._issue_cache[story_id] = num
                self._cache_timestamps[story_id] = time.time()
                return num

        return None

    def list_issues(self, labels: str | None = None,
                    state: str = "opened") -> list[dict[str, Any]]:
        # GitHub uses "open"/"closed" instead of "opened"/"closed"
        gh_state = "open" if state == "opened" else state
        params = {"state": gh_state, "per_page": 50}
        if labels:
            params["labels"] = labels

        result = _api_call(self.config, "GET", "/issues", params=params)
        if not isinstance(result, list):
            return []

        # Filter out pull requests (GitHub returns issues and PRs together)
        issues = [i for i in result if "pull_request" not in i]
        # Add "iid" alias
        for i in issues:
            i["iid"] = i.get("number")
        return issues

    def search_issues(self, query: str,
                      state: str = "opened") -> list[dict[str, Any]]:
        # GitHub Search API
        gh_state = "open" if state == "opened" else "closed"
        safe_query = urllib.parse.quote(query, safe="")
        q = f"{safe_query} repo:{self.config.owner}/{self.config.repo} is:issue state:{gh_state}"
        url = build_url(
            f"{self.config.api_url}/search/issues", "",
            {"q": q, "per_page": 20},
        )

        result = HTTPMixin._http_request(
            url,
            method="GET",
            headers=_github_headers(self.config),
            timeout=PROVIDER_API_TIMEOUT,
        )

        if isinstance(result, dict) and "error" in result:
            return []

        items = result.get("items", []) if isinstance(result, dict) else []
        for i in items:
            i["iid"] = i.get("number")
        return items

    def get_issue_comments(self, issue_id: Any,
                           limit: int = 10) -> list[dict[str, Any]]:
        params = {"per_page": limit}
        result = _api_call(self.config, "GET",
                           f"/issues/{issue_id}/comments", params=params)
        if not isinstance(result, list):
            return []

        # Map to GitLab-compatible format
        comments = []
        for c in result:
            comments.append({
                "id": c.get("id"),
                "body": c.get("body", ""),
                "author": {
                    "name": c.get("user", {}).get("login", "?"),
                },
                "created_at": c.get("created_at", ""),
                "system": False,
            })
        return comments

    # ----- Board -----

    def get_board_state(self) -> dict[str, list[dict[str, Any]]]:
        state = {}
        for status_key, label_name in BOARD_LABELS.items():
            issues = self.list_issues(labels=label_name)
            state[status_key] = [
                {
                    "iid": i.get("number"),
                    "title": i.get("title", ""),
                    "labels": [l["name"] for l in i.get("labels", [])
                               if isinstance(l, dict)],
                    "updated_at": i.get("updated_at", ""),
                }
                for i in issues
            ]
        return state

    def get_board_summary_md(self) -> str:
        if not self.enabled:
            return "(GitHub integration is not active)"

        state = self.get_board_state()
        lines = ["## 📋 GitHub Board — current state\n"]

        status_names = {
            "todo": "📥 TODO",
            "in_progress": "🔄 IN PROGRESS",
            "review": "👀 REVIEW",
            "testing": "🧪 TESTING",
            "done": "✅ DONE",
            "blocked": "🚫 BLOCKED",
        }

        for status_key, display_name in status_names.items():
            issues = state.get(status_key, [])
            lines.append(f"### {display_name} ({len(issues)})")
            if issues:
                for i in issues:
                    prio = next((l for l in i["labels"] if l.startswith("priority::")), "")
                    prio_short = prio.replace("priority::", "") if prio else ""
                    lines.append(f"- **#{i['iid']}** {i['title']} [{prio_short}]")
            else:
                lines.append("_(empty)_")
            lines.append("")

        return "\n".join(lines)

    # ----- PR (as MR) -----

    def create_mr(self, source_branch: str, target_branch: str = "main",
                  title: str = "", description: str = "") -> dict[str, Any]:
        data = {
            "head": source_branch,
            "base": target_branch,
            "title": title or f"Merge {source_branch} into {target_branch}",
            "body": description,
        }
        result = _api_call(self.config, "POST", "/pulls", data=data)
        if "error" not in result:
            result["iid"] = result.get("number")
        return result

    def list_mrs(self, state: str = "opened") -> list[dict[str, Any]]:
        gh_state = "open" if state == "opened" else state
        params = {"state": gh_state, "per_page": 50}
        result = _api_call(self.config, "GET", "/pulls", params=params)
        if not isinstance(result, list):
            return []
        for pr in result:
            pr["iid"] = pr.get("number")
            pr["source_branch"] = pr.get("head", {}).get("ref", "?")
            pr["target_branch"] = pr.get("base", {}).get("ref", "?")
            if "user" in pr:
                pr["author"] = {"name": pr["user"].get("login", "?")}
        return result

    def get_mr(self, mr_id: Any) -> dict[str, Any]:
        result = _api_call(self.config, "GET", f"/pulls/{mr_id}")
        if "error" not in result:
            result["iid"] = result.get("number")
        return result

    def comment_on_mr(self, mr_id: Any, body: str,
                      agent_id: str = "") -> dict[str, Any]:
        prefix = f"**🤖 {agent_id.upper()}**: " if agent_id else ""
        # GitHub PR comments go through the issues endpoint
        return _api_call(self.config, "POST",
                         f"/issues/{mr_id}/comments",
                         data={"body": prefix + body})

    def approve_mr(self, mr_id: Any) -> dict[str, Any]:
        return _api_call(self.config, "POST",
                         f"/pulls/{mr_id}/reviews",
                         data={"event": "APPROVE"})

    def merge_mr(self, mr_id: Any, squash: bool = False) -> dict[str, Any]:
        data = {"merge_method": "squash" if squash else "merge"}
        return _api_call(self.config, "PUT",
                         f"/pulls/{mr_id}/merge", data=data)

    def close_mr(self, mr_id: Any) -> dict[str, Any]:
        return _api_call(self.config, "PATCH",
                         f"/pulls/{mr_id}",
                         data={"state": "closed"})

    def get_mr_changes(self, mr_id: Any) -> dict[str, Any]:
        return _api_call(self.config, "GET", f"/pulls/{mr_id}/files")

    def get_mr_approvals(self, mr_id: Any) -> dict[str, Any]:
        """Get PR approval status from reviews."""
        result = _api_call(self.config, "GET", f"/pulls/{mr_id}/reviews")
        if isinstance(result, list):
            approved = any(r.get("state") == "APPROVED" for r in result)
            return {"approved": approved, "reviews": result}
        return {"approved": False, "error": result.get("error", "unknown")}

    def get_open_mrs_md(self) -> str:
        mrs = self.list_mrs("opened")
        if not mrs:
            return "### 🔀 Open Pull Requests\n_(none)_"

        lines = [f"### 🔀 Open Pull Requests ({len(mrs)})\n"]
        for pr in mrs[:10]:
            iid = pr.get("number", "?")
            title = pr.get("title", "?")
            author = pr.get("author", {}).get("name", "?")
            source = pr.get("source_branch", "?")
            target = pr.get("target_branch", "?")
            lines.append(f"- **#{iid}** {title}")
            lines.append(f"  - `{source}` → `{target}` (by {author})")

        return "\n".join(lines)

    # ----- Backward-compatible aliases -----

    def create_story(self, story_id: str, title: str, description: str,
                     priority: str = "medium", assigned_to: str | None = None) -> dict[str, Any]:
        result = super().create_story(story_id, title, description,
                                      priority, assigned_to)
        if result.get("number"):
            self._issue_cache[story_id] = result["number"]
            self._cache_timestamps[story_id] = time.time()
        return result


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import sys

    config = GitHubConfig()
    if not config.is_configured:
        print("Set GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO")
        sys.exit(1)

    provider = GitHubProvider(config)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "init":
        provider.init()
        print("✅ GitHub labels initialized")
    elif cmd == "status":
        print(provider.get_board_summary_md())
    elif cmd == "test":
        result = provider.create_story(
            "TEST-001", "Test story", "This is a test", priority="low"
        )
        print(f"Created issue: {result}")
    else:
        print(f"Usage: python github.py [init|status|test]")
