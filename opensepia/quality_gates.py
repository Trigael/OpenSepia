"""
AI Dev Team — Quality Gates.

Enforces Definition of Done and other quality checks before
stories can transition to terminal statuses.

Gate is threshold-based: stories pass if >= PASS_THRESHOLD of criteria
are checked. This prevents deadlocks when agents can't fulfill
operational criteria (e.g., "run tests", "create git tag") that
require human or CI intervention.
"""

import re

# Matches unchecked checkbox lines: - [ ] Some criterion
_UNCHECKED_RE = re.compile(r"^[ \t]*-\s*\[ \]\s*(.+)$", re.MULTILINE)
# Matches checked checkbox lines: - [x] Some criterion
_CHECKED_RE = re.compile(r"^[ \t]*-\s*\[[xX]\]\s*(.+)$", re.MULTILINE)
# Matches any checkbox (checked or unchecked)
_ANY_CHECKBOX_RE = re.compile(r"^[ \t]*-\s*\[[xX ]\]", re.MULTILINE)

# Stories pass DoD if this fraction of criteria are checked.
# 0.75 = 75% of criteria must be checked. This allows 1-2 operational
# criteria (CI runs, git tags) to remain unchecked without blocking.
PASS_THRESHOLD = 0.75


def check_definition_of_done(story_text: str) -> tuple[bool, list[str]]:
    """Check if enough acceptance criteria checkboxes are checked.

    Returns (passed, list_of_unchecked_criteria).

    Rules:
    - No checkboxes at all → pass (backward compat)
    - >= PASS_THRESHOLD checked → pass (with unchecked listed as warnings)
    - < PASS_THRESHOLD checked → fail
    """
    if not story_text or not story_text.strip():
        return True, []

    # If there are no checkboxes at all, pass
    if not _ANY_CHECKBOX_RE.search(story_text):
        return True, []

    checked = _CHECKED_RE.findall(story_text)
    unchecked = _UNCHECKED_RE.findall(story_text)
    total = len(checked) + len(unchecked)

    if total == 0:
        return True, []

    ratio = len(checked) / total
    unchecked_list = [c.strip() for c in unchecked]

    if ratio >= PASS_THRESHOLD:
        return True, unchecked_list  # Pass but report remaining items
    else:
        return False, unchecked_list
