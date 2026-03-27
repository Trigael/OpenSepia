"""
AI Dev Team — Plane.so Entity Mappings

Bidirectional mappings between Plane.so concepts and OpenSepia concepts:
states, priorities, work item IDs.
"""

import re
from typing import Any, Optional


# ---------------------------------------------------------------------------
# State group mapping (Plane state groups -> OpenSepia statuses)
# ---------------------------------------------------------------------------
STATE_GROUP_TO_STATUS: dict[str, str] = {
    "backlog": "todo",
    "unstarted": "todo",
    "started": "in_progress",
    "completed": "done",
    "cancelled": "done",
}

# Custom state name overrides (matched case-insensitively within a group)
# These take precedence over the group-level mapping above.
STATE_NAME_OVERRIDES: dict[str, str] = {
    "review": "review",
    "in review": "review",
    "code review": "review",
    "testing": "testing",
    "qa": "testing",
    "in testing": "testing",
    "blocked": "blocked",
}

# Reverse: OpenSepia status -> preferred Plane state name (used for creating states)
STATUS_TO_STATE_NAME: dict[str, tuple[str, str]] = {
    # status -> (state_name, state_group)
    "todo": ("Todo", "unstarted"),
    "in_progress": ("In Progress", "started"),
    "review": ("Review", "started"),
    "testing": ("Testing", "started"),
    "done": ("Done", "completed"),
    "blocked": ("Blocked", "started"),
}


def map_plane_state_to_status(state_name: str, state_group: str) -> str:
    """Map a Plane state to an OpenSepia status.

    First checks the state name for known overrides (e.g., "Review" -> "review"),
    then falls back to the group mapping.
    """
    name_lower = state_name.strip().lower()
    if name_lower in STATE_NAME_OVERRIDES:
        return STATE_NAME_OVERRIDES[name_lower]
    return STATE_GROUP_TO_STATUS.get(state_group, "todo")


def find_state_id_for_status(
    states: list[dict[str, Any]],
    target_status: str,
) -> Optional[str]:
    """Find the Plane state ID that best matches an OpenSepia status.

    Searches states by name first (exact match), then by group.
    """
    preferred_name, preferred_group = STATUS_TO_STATE_NAME.get(
        target_status, ("Todo", "unstarted")
    )

    # First pass: exact name match
    for state in states:
        if state.get("name", "").strip().lower() == preferred_name.lower():
            return state["id"]

    # Second pass: name override match
    for state in states:
        name_lower = state.get("name", "").strip().lower()
        if name_lower in STATE_NAME_OVERRIDES:
            if STATE_NAME_OVERRIDES[name_lower] == target_status:
                return state["id"]

    # Third pass: group match
    for state in states:
        if state.get("group") == preferred_group:
            return state["id"]

    return None


# ---------------------------------------------------------------------------
# Priority mapping (Plane <-> OpenSepia named priorities)
# ---------------------------------------------------------------------------
# Plane v1.2.x uses strings: "none", "low", "medium", "high", "urgent"
# Newer Plane versions may use integers: 0=None, 1=Urgent, 2=High, 3=Medium, 4=Low
# We support both formats.

PLANE_PRIORITY_STR_TO_OPENSEPIA: dict[str, str] = {
    "none": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "urgent": "critical",
}

PLANE_PRIORITY_INT_TO_OPENSEPIA: dict[int, str] = {
    0: "low",       # None -> low
    1: "critical",  # Urgent -> critical
    2: "high",
    3: "medium",
    4: "low",
}

OPENSEPIA_PRIORITY_TO_PLANE_STR: dict[str, str] = {
    "critical": "urgent",
    "high": "high",
    "medium": "medium",
    "low": "low",
}

OPENSEPIA_PRIORITY_TO_PLANE_INT: dict[str, int] = {
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
}


def map_plane_priority(priority: int | str | None) -> str:
    if priority is None:
        return "medium"
    if isinstance(priority, str):
        return PLANE_PRIORITY_STR_TO_OPENSEPIA.get(priority.lower(), "medium")
    return PLANE_PRIORITY_INT_TO_OPENSEPIA.get(priority, "medium")


def map_opensepia_priority(priority: str) -> str:
    """Map OpenSepia priority to Plane priority string."""
    return OPENSEPIA_PRIORITY_TO_PLANE_STR.get(priority.lower(), "medium")


# ---------------------------------------------------------------------------
# Work item ID helpers (STORY-001 / BUG-001 <-> Plane titles)
# ---------------------------------------------------------------------------
_STORY_BUG_RE = re.compile(r'\[((?:STORY|BUG)-\d+)\]')


def extract_story_id_from_title(title: str) -> Optional[str]:
    """Extract [STORY-001] or [BUG-001] from a Plane work item title."""
    match = _STORY_BUG_RE.search(title)
    return match.group(1) if match else None


def build_title(story_id: str, title: str) -> str:
    """Format a work item title: [STORY-001] Login feature"""
    # Strip existing prefix if present
    clean_title = _STORY_BUG_RE.sub("", title).strip()
    prefix = "\U0001f41b " if story_id.startswith("BUG-") else ""
    return f"{prefix}[{story_id}] {clean_title}"


def strip_title_prefix(title: str) -> str:
    """Remove [STORY-001] prefix and bug emoji from a title."""
    cleaned = _STORY_BUG_RE.sub("", title)
    cleaned = cleaned.replace("\U0001f41b", "").strip()
    return cleaned
