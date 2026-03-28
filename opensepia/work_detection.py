"""
AI Dev Team — Work Detection & Stuck Story Detection.

Determines if an agent has work to do before invoking Claude.
Detects stories stuck in the same status for too many cycles.
"""

import re
import logging
from pathlib import Path

from opensepia.board_adapter import STORY_BUG_ID_RE

logger = logging.getLogger(__name__)

# Stories stuck in the same status for this many cycles get escalated
STUCK_THRESHOLD_CYCLES = 3

# Agent role → which sprint sections they care about
AGENT_WORK_SECTIONS = {
    "po": {"todo", "in progress", "review", "testing", "blocked"},  # PO always has work (backlog mgmt)
    "pm": {"todo", "in progress", "review", "testing", "blocked"},  # PM always has work (coordination)
    "dev1": {"todo", "in progress", "review"},
    "dev2": {"todo", "in progress", "review"},
    "devops": {"todo", "in progress", "review"},
    "tester": {"testing", "review"},
    "sec_analyst": {"in progress", "review", "testing"},
    "sec_engineer": {"in progress", "review"},
    "sec_pentester": {"in progress", "review", "testing"},
}


def agent_has_work(agent_id: str, sprint_text: str, inbox_text: str) -> bool:
    """Check if an agent has meaningful work to do this cycle.

    Returns True if:
    - Agent has inbox messages (someone sent them work/review requests)
    - Agent has stories assigned in relevant sprint sections
    - Agent is PO or PM (always have coordination work)
    - Agent is a spawned/unknown type (assume they have work)
    """
    # Inbox messages = always has work
    if inbox_text.strip():
        return True

    # PO and PM always run (coordination roles)
    if agent_id in ("po", "pm"):
        return True

    # Check if agent has assigned stories in relevant sections
    relevant_sections = AGENT_WORK_SECTIONS.get(agent_id)
    if relevant_sections is None:
        # Unknown agent (spawned) — assume they have work
        return True

    current_section = None
    for line in sprint_text.split("\n"):
        stripped = line.strip().lower()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()

        if current_section and current_section in relevant_sections:
            # Check if this line references the agent
            if f"({agent_id})" in line.lower() or f"assigned**: {agent_id}" in line.lower():
                return True

    # Tester: check if anything is in TESTING section at all
    if agent_id == "tester":
        in_testing = False
        for line in sprint_text.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("## testing"):
                in_testing = True
            elif stripped.startswith("## ") and in_testing:
                break
            elif in_testing and STORY_BUG_ID_RE.search(line):
                return True

        # Also check REVIEW — tester does functional review
        in_review = False
        for line in sprint_text.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("## review"):
                in_review = True
            elif stripped.startswith("## ") and in_review:
                break
            elif in_review and STORY_BUG_ID_RE.search(line):
                return True

    # Security agents: check if there are any active stories
    if agent_id.startswith("sec_"):
        for section in ("in progress", "review", "testing"):
            in_section = False
            for line in sprint_text.split("\n"):
                stripped = line.strip().lower()
                if stripped.startswith("## ") and section in stripped:
                    in_section = True
                elif stripped.startswith("## ") and in_section:
                    break
                elif in_section and STORY_BUG_ID_RE.search(line):
                    return True

    return False


def detect_stuck_stories(
    sprint_text: str,
    board_dir: Path,
    current_cycle: int,
) -> list[dict]:
    """Detect stories stuck in the same status for too many cycles.

    Reads/writes a tracking file at board/.stuck_tracker.
    Returns list of {story_id, status, stuck_since_cycle, cycles_stuck}.
    """
    tracker_path = board_dir / ".stuck_tracker"

    # Load previous tracker state
    prev_state: dict[str, dict] = {}
    if tracker_path.exists():
        try:
            for line in tracker_path.read_text(encoding="utf-8").strip().split("\n"):
                if ":" in line:
                    parts = line.split(":", 2)
                    if len(parts) == 3:
                        prev_state[parts[0]] = {
                            "status": parts[1],
                            "since": int(parts[2]),
                        }
        except (OSError, ValueError):
            pass

    # Parse current sprint statuses
    current_state: dict[str, str] = {}
    current_section = None
    for line in sprint_text.split("\n"):
        stripped = line.strip().lower()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
        elif current_section and current_section not in ("done", "blocked"):
            refs = STORY_BUG_ID_RE.findall(line)
            for ref in refs:
                current_state[ref.upper()] = current_section

    # Update tracker
    new_state: dict[str, dict] = {}
    stuck: list[dict] = []

    for story_id, status in current_state.items():
        prev = prev_state.get(story_id)
        if prev and prev["status"] == status:
            # Same status as before
            since = prev["since"]
            cycles_stuck = current_cycle - since
            new_state[story_id] = {"status": status, "since": since}
            if cycles_stuck >= STUCK_THRESHOLD_CYCLES:
                stuck.append({
                    "story_id": story_id,
                    "status": status,
                    "stuck_since_cycle": since,
                    "cycles_stuck": cycles_stuck,
                })
        else:
            # New or changed status
            new_state[story_id] = {"status": status, "since": current_cycle}

    # Write updated tracker
    try:
        lines = [f"{sid}:{d['status']}:{d['since']}" for sid, d in new_state.items()]
        tracker_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass

    return stuck


def escalate_stuck_stories(
    stuck: list[dict],
    board_dir: Path,
) -> int:
    """Send inbox messages to PO about stuck stories. Returns count escalated."""
    if not stuck:
        return 0

    inbox_path = board_dir / "inbox" / "po.md"
    messages = []
    for s in stuck:
        messages.append(
            f"- **{s['story_id']}** stuck in {s['status'].upper()} "
            f"for {s['cycles_stuck']} cycles (since cycle {s['stuck_since_cycle']})"
        )

    message = (
        f"## System Alert — Stuck Stories\n\n"
        f"The following stories have not progressed for {STUCK_THRESHOLD_CYCLES}+ cycles. "
        f"Consider: reassigning, breaking into smaller stories, marking BLOCKED, "
        f"or flagging as needing human intervention.\n\n"
        + "\n".join(messages) + "\n"
    )

    try:
        existing = inbox_path.read_text(encoding="utf-8") if inbox_path.exists() else ""
        # Don't send duplicate alerts
        if "Stuck Stories" not in existing:
            inbox_path.write_text(existing + "\n" + message, encoding="utf-8")
            logger.info("Escalated %d stuck stories to PO", len(stuck))
            return len(stuck)
    except OSError:
        pass
    return 0
