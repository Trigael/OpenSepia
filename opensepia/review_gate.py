"""
AI Dev Team — Code Review Quality Gate.

Ensures stories cannot transition from REVIEW to DONE without
peer review evidence. Scans archive and standup files for review
keywords referencing the story ID.
"""

import logging
from pathlib import Path


logger = logging.getLogger(__name__)

APPROVAL_KEYWORDS = ["approved", "lgtm", "looks good", "code review: approved"]
REJECTION_KEYWORDS = ["needs changes", "rejected", "request changes"]

# Maps dev agents to their reviewer counterpart
_REVIEWER_MAP = {
    "dev1": "dev2",
    "dev2": "dev1",
}


def _classify_text(content_lower: str) -> str | None:
    """Return 'approved', 'rejected', or None based on keywords found."""
    for kw in REJECTION_KEYWORDS:
        if kw in content_lower:
            return "rejected"
    for kw in APPROVAL_KEYWORDS:
        if kw in content_lower:
            return "approved"
    return None


def check_review_evidence(story_id: str, board_dir: Path) -> tuple[bool, str]:
    """Check if a story has peer review evidence in archive or standup.

    Scans board/archive/*/ and board/standup.md for review keywords
    referencing the story_id. When multiple files mention the story,
    the most recent evidence (by filename sort order) wins.

    Returns (has_approval, reviewer_name_or_reason).
    """
    story_lower = story_id.lower()

    # Collect all text sources to scan, sorted so newest files come last
    texts: list[tuple[str, str]] = []  # (source_label, content)

    # Scan archive directories
    archive_dir = board_dir / "archive"
    if archive_dir.is_dir():
        for agent_dir in sorted(archive_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            for f in sorted(agent_dir.iterdir()):
                if f.suffix == ".md" and f.is_file():
                    try:
                        content = f.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    texts.append((f"{agent_dir.name}/{f.name}", content))

    # Scan standup (always most recent context)
    standup_path = board_dir / "standup.md"
    if standup_path.is_file():
        try:
            texts.append(("standup.md", standup_path.read_text(encoding="utf-8")))
        except OSError:
            pass

    # Find the most recent review verdict for this story.
    # Since files are sorted chronologically, iterate in reverse
    # so the newest evidence takes priority.
    last_verdict: str | None = None
    last_source: str = ""
    last_reviewer: str = ""

    for source, content in texts:
        content_lower = content.lower()
        if story_lower not in content_lower:
            continue

        verdict = _classify_text(content_lower)
        if verdict is not None:
            last_verdict = verdict
            last_source = source
            last_reviewer = source.split("/")[0] if "/" in source else "unknown"

    if last_verdict == "approved":
        return True, last_reviewer
    if last_verdict == "rejected":
        return False, f"rejection found in {last_source}"

    return False, "no review evidence found"


def get_reviewer_for_story(story_id: str, assigned_to: str) -> str:
    """Determine who should review: dev1's work -> dev2, and vice versa."""
    return _REVIEWER_MAP.get(assigned_to, "dev1")
