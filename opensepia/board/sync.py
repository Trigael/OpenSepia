"""
AI Dev Team — Board Sync

Synchronizes backlog.md and sprint.md with provider issues and labels.
Called by the orchestrator pipeline's BoardSyncStep.
"""

import re
import json
import logging
from pathlib import Path
from typing import Any

from opensepia.integrations.base import BoardProvider, BOARD_LABELS, PRIORITY_LABELS

logger = logging.getLogger(__name__)


def parse_backlog(backlog_path: Path) -> list[dict[str, Any]]:
    """Parse backlog.md and return a list of stories/bugs."""
    content = backlog_path.read_text(encoding="utf-8")
    items = []

    current_priority = "medium"
    priority_map = {
        "CRITICAL": "critical",
        "HIGH": "high",
        "MEDIUM": "medium",
        "LOW": "low",
    }

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        for key, prio in priority_map.items():
            if key in line and line.startswith("##"):
                current_priority = prio
                break

        match = re.match(r'^###\s+((?:STORY|BUG)-\d+):\s*(.+)', line)
        if match:
            item_id = match.group(1)
            title = match.group(2).strip()

            desc_lines = []
            i += 1
            while i < len(lines):
                if lines[i].startswith("### ") or lines[i].startswith("## ") or lines[i].strip() == "---":
                    break
                desc_lines.append(lines[i])
                i += 1

            description = "\n".join(desc_lines).strip()

            status = "todo"
            status_match = re.search(r'\*\*Status\*\*:\s*(.+)', description)
            if status_match:
                status = normalize_status(status_match.group(1))

            assigned = None
            assign_match = re.search(r'\*\*Assigned\*\*:\s*(.+)', description)
            if assign_match:
                assigned = assign_match.group(1).strip()

            items.append({
                "id": item_id,
                "title": title,
                "description": description,
                "priority": current_priority,
                "status": status,
                "assigned": assigned,
                "is_bug": item_id.startswith("BUG-"),
            })
            continue

        i += 1

    return items


def normalize_status(raw: str) -> str:
    """Normalize free-form English status to a standard value."""
    s = raw.strip().lower()

    direct = {
        "todo": "todo",
        "in_progress": "in_progress",
        "in progress": "in_progress",
        "done": "done",
        "blocked": "blocked",
        "review": "review",
        "testing": "testing",
    }
    if s in direct:
        return direct[s]

    patterns = [
        ("in.progress", "in_progress"),
        ("review", "review"),
    ]
    for pattern, status in patterns:
        if pattern in s:
            return status

    for key in direct:
        if s.startswith(key):
            return direct[key]

    return "todo"


def parse_sprint_statuses(sprint_path: Path) -> dict[str, str]:
    """Parse sprint.md and return a mapping of item_id -> status."""
    content = sprint_path.read_text(encoding="utf-8")
    statuses = {}

    status_map = {
        "todo": "todo",
        "in progress": "in_progress",
        "in_progress": "in_progress",
        "done": "done",
        "blocked": "blocked",
        "review": "review",
        "testing": "testing",
    }

    current_status = None
    for line in content.split("\n"):
        stripped = line.strip().lower()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            matched = False
            for keyword, status in status_map.items():
                if keyword in stripped:
                    current_status = status
                    matched = True
                    break
            if not matched:
                current_status = None

        if current_status:
            if line.strip().startswith("- ["):
                refs = re.findall(r'((?:STORY|BUG)-\d+)', line)
                for ref in refs:
                    statuses[ref] = current_status

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        header_match = re.match(r'^###\s+((?:STORY|BUG)-\d+):', lines[i])
        if header_match:
            item_id = header_match.group(1)
            if item_id not in statuses:
                for j in range(i + 1, min(i + 16, len(lines))):
                    if lines[j].startswith("### ") or lines[j].startswith("## "):
                        break
                    status_match = re.search(r'\*\*Status\*\*:\s*(.+)', lines[j])
                    if status_match:
                        statuses[item_id] = normalize_status(status_match.group(1))
                        break
        i += 1

    return statuses


def sync_to_provider(
    items: list[dict[str, Any]],
    sprint_statuses: dict[str, str],
    provider: BoardProvider,
    board_dir: Path | None = None,
) -> tuple[int, int]:
    """Synchronize items to provider issues (GitLab or GitHub)."""
    all_issues = provider.list_issues(state="opened")
    closed_issues = provider.list_issues(state="closed")
    all_issues.extend(closed_issues)

    issue_map: dict[str, dict] = {}
    for issue in all_issues:
        match = re.search(r'\[((?:STORY|BUG)-\d+)\]', issue.get("title", ""))
        if match:
            issue_map[match.group(1)] = issue

    created = 0
    updated = 0
    all_status_labels = set(BOARD_LABELS.values())

    for item in items:
        item_id = item["id"]
        status = sprint_statuses.get(item_id, item["status"])
        status_label = BOARD_LABELS.get(status, BOARD_LABELS["todo"])
        priority_label = PRIORITY_LABELS.get(item["priority"], PRIORITY_LABELS["medium"])

        labels = [status_label, priority_label]
        if item["is_bug"]:
            labels.append("type::bug")

        title_prefix = "\U0001f41b " if item["is_bug"] else ""
        full_title = f"{title_prefix}[{item_id}] {item['title']}"

        if item_id in issue_map:
            existing = issue_map[item_id]
            existing_labels = set(existing.get("labels", []))
            new_labels = set(labels)
            old_status = existing_labels & all_status_labels
            new_status = new_labels & all_status_labels

            if old_status != new_status or not new_labels.issubset(existing_labels):
                merged_labels = list(new_labels | (existing_labels - all_status_labels))
                result = provider.update_issue_labels(existing['iid'], merged_labels)
                if "error" not in result:
                    updated += 1
                    logger.info(f"  Updated #{existing['iid']} {item_id}: {old_status} -> {new_status}")

            if status != "done" and existing.get("state") == "closed":
                provider.reopen_issue(existing['iid'])
                logger.info(f"  Reopened #{existing['iid']} {item_id}")

            if status == "done" and existing.get("state") != "closed":
                provider.close_issue(existing['iid'])
                logger.info(f"  Closed #{existing['iid']} {item_id}")
        else:
            desc = f"**{item_id}**\n\n{item['description']}"
            if item.get("assigned"):
                desc += f"\n\n**Assigned**: {item['assigned']}"
            result = provider.create_issue(full_title, desc, labels=labels)
            if "error" not in result:
                created += 1
                logger.info(f"  Created #{result.get('iid')} {item_id}: {item['title']}")
            else:
                logger.error(f"  Failed to create {item_id}: {result}")

    backlog_ids = {item["id"] for item in items}
    for item_id, status in sprint_statuses.items():
        if item_id in backlog_ids:
            continue
        if item_id not in issue_map:
            logger.warning(f"  Sprint-only {item_id} ({status}): no provider issue, skipping")
            continue

        existing = issue_map[item_id]
        status_label = BOARD_LABELS.get(status, BOARD_LABELS["todo"])
        existing_labels = set(existing.get("labels", []))
        old_status = existing_labels & all_status_labels
        new_status_set = {status_label}

        if old_status != new_status_set:
            merged_labels = list((existing_labels - all_status_labels) | new_status_set)
            result = provider.update_issue_labels(existing['iid'], merged_labels)
            if "error" not in result:
                updated += 1

        if status == "done" and existing.get("state") != "closed":
            provider.close_issue(existing['iid'])
        if status != "done" and existing.get("state") == "closed":
            provider.reopen_issue(existing['iid'])

    # Export issue map cache
    if board_dir:
        cache_map = {}
        all_fresh = provider.list_issues(state="opened")
        closed_fresh = provider.list_issues(state="closed")
        all_fresh.extend(closed_fresh)
        for issue in all_fresh:
            match = re.search(r'\[((?:STORY|BUG)-\d+)\]', issue.get("title", ""))
            if match:
                cache_map[match.group(1)] = issue["iid"]
        if cache_map:
            cache_path = board_dir / f".{provider.name}_issue_map.json"
            try:
                cache_path.write_text(
                    json.dumps(cache_map, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.warning(f"  Issue map cache: write error: {e}")

    return created, updated
