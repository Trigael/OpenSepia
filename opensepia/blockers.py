"""
AI Dev Team — Blocker Registry.

Extracts BLOCKED stories from sprint.md, tracks how long they've been
blocked (in cycles), and formats the information for agent context injection.
"""

import re
from pathlib import Path

# Matches lines like: - [ ] STORY-042 Some title
_STORY_LINE_RE = re.compile(
    r"^-\s*\[[ x]?\]\s*((?:STORY|BUG)-\d+)\s+(.*)",
    re.IGNORECASE,
)


def extract_blockers(sprint_text: str) -> list[dict]:
    """Extract BLOCKED stories from sprint.md.

    Looks for a ``## BLOCKED`` section and parses each story/bug line
    within it until the next ``## `` heading (or end of text).

    Returns:
        List of dicts with keys ``story_id``, ``title``, ``blocked_since``.
        ``blocked_since`` is left as empty string when first discovered
        (the caller / registry tracks the actual cycle).
    """
    blockers: list[dict] = []
    in_blocked = False

    for line in sprint_text.split("\n"):
        stripped = line.strip()

        # Detect section headers
        if stripped.lower().startswith("## "):
            section = stripped[3:].strip().lower()
            in_blocked = section == "blocked"
            continue

        if not in_blocked:
            continue

        m = _STORY_LINE_RE.match(stripped)
        if m:
            blockers.append({
                "story_id": m.group(1).upper(),
                "title": m.group(2).strip(),
                "blocked_since": "",
            })

    return blockers


def format_blockers_for_context(blockers: list[dict], cycle_num: int) -> str:
    """Format blockers as markdown for agent context injection.

    Each entry shows the story id, title, and how many cycles it has been
    blocked (``cycle_num - blocked_since``).  If *blockers* is empty an
    ``(none)`` placeholder is returned.
    """
    if not blockers:
        return "## Active Blockers\n(none)\n"

    lines = ["## Active Blockers"]
    for b in blockers:
        since = b.get("blocked_since", "")
        if since and str(since).isdigit():
            age = max(cycle_num - int(since), 1)
        else:
            age = 1
        lines.append(f"- **{b['story_id']}** {b['title']} — blocked {age} cycle(s)")
    lines.append("")
    return "\n".join(lines)


def update_blocker_registry(board_dir: Path, blockers: list[dict], cycle_num: int) -> None:
    """Write/update ``board/blockers.md`` with current blockers and age tracking.

    On each call the existing registry is read so that ``blocked_since``
    values are preserved for stories that were already tracked.  New
    blockers get ``blocked_since`` set to *cycle_num*.  Stories no longer
    in *blockers* are dropped from the registry.
    """
    registry_path = board_dir / "blockers.md"
    existing = _read_registry(registry_path)

    # Merge: preserve blocked_since for known ids, set for new ones
    updated: list[dict] = []
    for b in blockers:
        sid = b["story_id"]
        if sid in existing:
            b = {**b, "blocked_since": existing[sid]}
        else:
            b = {**b, "blocked_since": str(cycle_num)}
        updated.append(b)

    # Write registry
    lines = [f"# Blocker Registry — cycle {cycle_num}", ""]
    if updated:
        for entry in updated:
            age = max(cycle_num - int(entry["blocked_since"]), 1)
            lines.append(
                f"- {entry['story_id']} | {entry['title']} "
                f"| since cycle {entry['blocked_since']} | age {age}"
            )
    else:
        lines.append("(no blockers)")
    lines.append("")

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("\n".join(lines), encoding="utf-8")


def _read_registry(path: Path) -> dict[str, str]:
    """Parse existing blockers.md and return {story_id: blocked_since_cycle}."""
    mapping: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return mapping

    for line in text.split("\n"):
        # Format: - STORY-042 | title | since cycle 5 | age 3
        m = re.match(
            r"^-\s*((?:STORY|BUG)-\d+)\s*\|.*?\|\s*since cycle\s+(\d+)",
            line,
            re.IGNORECASE,
        )
        if m:
            mapping[m.group(1).upper()] = m.group(2)

    return mapping
