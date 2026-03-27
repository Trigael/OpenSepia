"""
AI Dev Team — Board Restore

Board health check and recovery from snapshots or provider issues.
"""

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CRITICAL_FILES = ["sprint.md", "backlog.md"]
IMPORTANT_FILES = ["project.md", "architecture.md", "decisions.md", "standup.md"]


def check_board_health(board_dir: Path) -> dict:
    """Check the health of board files. Returns a report dict."""
    report: dict = {"ok": True, "missing": [], "empty": [], "present": []}

    for f in CRITICAL_FILES + IMPORTANT_FILES:
        path = board_dir / f
        if not path.exists():
            report["missing"].append(f)
            report["ok"] = False
        elif path.stat().st_size == 0:
            report["empty"].append(f)
            report["ok"] = False
        else:
            report["present"].append(f)

    return report


def restore_from_snapshot(board_dir: Path) -> bool:
    """Restore board files from local .snapshot/ directory."""
    snapshot_dir = board_dir / ".snapshot"
    if not snapshot_dir.exists():
        logger.error("No snapshot directory found at board/.snapshot/")
        return False

    backups = list(snapshot_dir.glob("*.bak"))
    if not backups:
        logger.error("No snapshot files found in board/.snapshot/")
        return False

    restored = 0
    for bak_file in backups:
        original_name = bak_file.name.replace(".bak", "")
        target = board_dir / original_name

        if not target.exists() or target.stat().st_size == 0:
            content = bak_file.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8")
            restored += 1
            logger.info("  Restored: %s (%d chars)", original_name, len(content))
        else:
            logger.info("  Skipped: %s (already exists and non-empty)", original_name)

    logger.info("Restore complete: %d files restored from snapshot", restored)
    return restored > 0


def restore_from_provider(board_dir: Path) -> bool:
    """Reconstruct board files from GitLab/GitHub issues."""
    try:
        from opensepia.integrations.providers import detect_provider
        from opensepia.integrations.base import BOARD_LABELS, PRIORITY_LABELS
    except ImportError as e:
        logger.error("Cannot import integrations: %s", e)
        return False

    provider = detect_provider()
    if not provider or not provider.enabled:
        logger.error("No board provider configured (GitLab/GitHub)")
        return False

    logger.info("Fetching issues from %s...", provider.name)

    open_issues = provider.list_issues(state="opened")
    closed_issues = provider.list_issues(state="closed")
    all_issues = open_issues + closed_issues

    if not all_issues:
        logger.warning("No issues found on the provider. Cannot reconstruct board.")
        return False

    status_from_label = {v: k for k, v in BOARD_LABELS.items()}
    priority_from_label = {v: k for k, v in PRIORITY_LABELS.items()}

    stories = []
    for issue in all_issues:
        title = issue.get("title", "")
        labels = set(issue.get("labels", []))

        match = re.search(r'\[((?:STORY|BUG)-\d+)\]', title)
        if not match:
            continue

        story_id = match.group(1)
        story_title = re.sub(r'^\S*\s*\[(?:STORY|BUG)-\d+\]\s*', '', title).strip()

        status = "todo"
        for label in labels:
            if label in status_from_label:
                status = status_from_label[label]
                break
        if issue.get("state") == "closed":
            status = "done"

        priority = "medium"
        for label in labels:
            if label in priority_from_label:
                priority = priority_from_label[label]
                break

        stories.append({
            "id": story_id,
            "title": story_title,
            "description": issue.get("description", ""),
            "status": status,
            "priority": priority,
            "is_bug": story_id.startswith("BUG-"),
        })

    if not stories:
        logger.warning("No STORY/BUG issues found. Cannot reconstruct board.")
        return False

    # Reconstruct backlog.md
    backlog_path = board_dir / "backlog.md"
    if not backlog_path.exists() or backlog_path.stat().st_size == 0:
        sections: dict[str, list] = {"critical": [], "high": [], "medium": [], "low": []}
        for s in stories:
            sections[s["priority"]].append(s)

        lines = ["# Backlog\n"]
        for prio in ["critical", "high", "medium", "low"]:
            if sections[prio]:
                lines.append(f"\n## {prio.upper()}\n")
                for s in sections[prio]:
                    lines.append(f"### {s['id']}: {s['title']}")
                    lines.append(f"**Priority**: {s['priority'].upper()}")
                    lines.append(f"**Status**: {s['status'].upper()}")
                    if s["description"]:
                        lines.append(f"\n{s['description'][:500].strip()}")
                    lines.append("")

        backlog_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("  Reconstructed backlog.md (%d stories)", len(stories))

    # Reconstruct sprint.md
    sprint_path = board_dir / "sprint.md"
    if not sprint_path.exists() or sprint_path.stat().st_size == 0:
        active = [s for s in stories if s["status"] != "done"]
        done = [s for s in stories if s["status"] == "done"]

        status_display = {
            "todo": "TODO", "in_progress": "IN PROGRESS",
            "review": "REVIEW", "testing": "TESTING", "blocked": "BLOCKED",
        }

        lines = ["# Sprint (reconstructed from provider)\n"]
        for status in ["todo", "in_progress", "review", "testing", "blocked"]:
            items = [s for s in active if s["status"] == status]
            if items:
                lines.append(f"\n## {status_display[status]}\n")
                for s in items:
                    lines.append(f"- [ ] **{s['id']}**: {s['title']}")
                lines.append("")

        if done:
            lines.append("\n## DONE\n")
            for s in done[-10:]:
                lines.append(f"- [x] **{s['id']}**: {s['title']}")
            lines.append("")

        sprint_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("  Reconstructed sprint.md (%d active, %d done)", len(active), len(done))

    # Ensure inbox files exist
    inbox_dir = board_dir / "inbox"
    inbox_dir.mkdir(exist_ok=True)

    logger.info("Restore from provider complete.")
    return True
