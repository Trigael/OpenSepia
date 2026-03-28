"""
AI Dev Team — Quality Gates.

Enforces Definition of Done and other quality checks before
stories can transition to terminal statuses.
"""

import re

# Matches unchecked checkbox lines: - [ ] Some criterion
_UNCHECKED_RE = re.compile(r"^[ \t]*-\s*\[ \]\s*(.+)$", re.MULTILINE)
# Matches any checkbox (checked or unchecked)
_ANY_CHECKBOX_RE = re.compile(r"^[ \t]*-\s*\[[xX ]\]", re.MULTILINE)


def check_definition_of_done(story_text: str) -> tuple[bool, list[str]]:
    """Check if all acceptance criteria checkboxes are checked.

    Returns (passed, list_of_unchecked_criteria).

    If the story has no checkboxes at all, it passes (backward compat).
    """
    if not story_text or not story_text.strip():
        return True, []

    # If there are no checkboxes at all, pass
    if not _ANY_CHECKBOX_RE.search(story_text):
        return True, []

    unchecked = _UNCHECKED_RE.findall(story_text)
    if unchecked:
        return False, [c.strip() for c in unchecked]

    return True, []
