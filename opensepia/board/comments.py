"""
AI Dev Team — Board Comment Sync

Synchronizes agent comments to provider issues/MRs and reads comments back.

WRITE: Agent writes to inbox -> extract STORY-XXX -> post comment to provider issue
READ:  Provider issues -> fetch comments -> inject into agent context
"""

import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# WRITE functions — agent output -> provider comments
# =============================================================================

def extract_story_refs(text: str) -> set[str]:
    """Extract STORY-XXX and BUG-XXX references from text."""
    return set(re.findall(r'((?:STORY|BUG)-\d+)', text))


def extract_mr_refs(text: str) -> set[int]:
    """Extract MR IID references (!123) from text. Returns a set of ints."""
    return {int(m) for m in re.findall(r'!(\d+)', text)}


def truncate_for_comment(text: str, max_chars: int = 2000) -> str:
    """Truncate a message for a provider comment."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 20] + "\n\n_(truncated)_"


def post_agent_messages_to_provider(
    agent_id: str,
    written_files: list[dict[str, str]],
    client: Any,
) -> int:
    """Post agent review messages as comments to provider issues/MRs.

    Only posts messages that are code reviews, QA reviews, or explicit
    approvals. Regular inbox messages (task assignments, coordination,
    status updates) stay inbox-only to avoid noise on stories.
    """
    if not client or not client.enabled:
        return 0

    posted = 0

    for file_info in written_files:
        path = file_info.get("path", "")
        content = file_info.get("content", "")

        if "board/inbox/" not in path or not content.strip():
            continue

        # Only post reviews and approvals as story comments — not every
        # inbox message that happens to mention a story ID
        if not _is_review_message(content):
            continue

        story_refs = extract_story_refs(content)
        if not story_refs:
            continue

        comment_body = truncate_for_comment(content)

        for story_id in story_refs:
            try:
                iid = client.find_issue_by_id(story_id)
                if not iid:
                    continue
                result = client.comment_on_issue(iid, agent_id, comment_body)
                if "error" not in result:
                    posted += 1
            except Exception as e:
                logger.warning("Provider: error sending comment on %s: %s", story_id, e)

        # Post reviews on MRs too
        mr_refs = extract_mr_refs(content)
        for mr_iid in mr_refs:
            try:
                result = client.comment_on_mr(mr_iid, comment_body, agent_id=agent_id)
                if "error" not in result:
                    posted += 1
                if _is_approval(content):
                    _try_approve_mr(client, mr_iid, agent_id)
            except Exception as e:
                logger.warning("Provider: error commenting on MR !%d: %s", mr_iid, e)

        # Find MRs for reviewed stories
        mr_iids_from_stories = _find_mrs_for_stories(client, story_refs)
        for mr_iid in mr_iids_from_stories - mr_refs:
            try:
                result = client.comment_on_mr(mr_iid, comment_body, agent_id=agent_id)
                if "error" not in result:
                    posted += 1
                if _is_approval(content):
                    _try_approve_mr(client, mr_iid, agent_id)
            except Exception as e:
                logger.warning("Provider: error posting review on MR !%d: %s", mr_iid, e)

    return posted


# Cache open MRs per sync cycle
_open_mrs_cache: list | None = None


def _get_open_mrs(client: Any) -> list:
    global _open_mrs_cache
    if _open_mrs_cache is None:
        _open_mrs_cache = client.list_mrs("opened")
    return _open_mrs_cache


def reset_mr_cache() -> None:
    """Reset the open MRs cache. Call at the start of each sync cycle."""
    global _open_mrs_cache
    _open_mrs_cache = None


def _find_mrs_for_stories(client: Any, story_ids: set[str]) -> set[int]:
    """Find open MRs whose branch or title contains any of the story IDs."""
    mrs = _get_open_mrs(client)
    matched = set()
    for mr in mrs:
        branch = mr.get("source_branch", "")
        title = mr.get("title", "")
        search_text = f"{branch} {title}".lower()
        for story_id in story_ids:
            slug = story_id.lower().replace("-", "")
            if slug in search_text or story_id.lower() in search_text:
                matched.add(mr["iid"])
                break
    return matched


_REVIEW_KEYWORDS = [
    "code review", "review", "qa review", "functional review",
    "pentest", "security review", "lgtm", "approve", "approved",
    "looks good", "needs changes", "request changes",
]
_APPROVE_KEYWORDS = ["approve", "lgtm", "approved", "looks good", "\u2705"]


def _is_review_message(content: str) -> bool:
    content_lower = content.lower()
    return any(kw in content_lower for kw in _REVIEW_KEYWORDS)


def _is_approval(content: str) -> bool:
    content_lower = content.lower()
    has_approval = any(kw in content_lower for kw in _APPROVE_KEYWORDS)
    has_rejection = any(kw in content_lower for kw in [
        "needs changes", "reject", "request changes", "not approved",
    ])
    return has_approval and not has_rejection


def _try_approve_mr(client: Any, mr_iid: int, agent_id: str) -> None:
    try:
        result = client.approve_mr(mr_iid)
        if "error" not in result:
            logger.info("Provider: %s approved MR !%d", agent_id, mr_iid)
    except Exception as e:
        logger.debug("Provider: approve MR !%d error: %s", mr_iid, e)


# =============================================================================
# STANDUP functions — board/standup.md -> provider issues
# =============================================================================

def post_standup_to_provider(standup_path: Path, client: Any) -> int:
    """Post standup summary to provider.

    Disabled: standup dumps on individual stories create noise.
    The standup is available via the board files and cycle logs instead.
    """
    return 0

    # Original implementation kept for reference:
    if not client or not client.enabled:
        return 0
    if not standup_path.exists():
        return 0

    content = standup_path.read_text(encoding="utf-8")
    if not content.strip():
        return 0

    story_refs = extract_story_refs(content)
    if not story_refs:
        return 0

    comment_body = f"\U0001f4cb **Standup Summary**\n\n{truncate_for_comment(content, 3000)}"

    posted = 0
    for story_id in story_refs:
        try:
            iid = client.find_issue_by_id(story_id)
            if not iid:
                continue
            result = client.comment_on_issue(iid, "standup", comment_body)
            if "error" not in result:
                posted += 1
        except Exception as e:
            logger.warning("Standup: error sending to %s: %s", story_id, e)

    return posted


# =============================================================================
# READ functions — provider comments -> agent context
# =============================================================================

def get_active_story_ids(
    sprint_path: Path | None = None,
    backlog_path: Path | None = None,
) -> list[str]:
    """Extract active story IDs (not DONE) from sprint.md and backlog.md."""
    story_ids = []
    ACTIVE_KEYWORDS = {"todo", "in progress", "in_progress", "review", "testing", "blocked"}

    for fpath in [sprint_path, backlog_path]:
        if fpath is None or not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8")
        in_active_section = False
        for line in content.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("##"):
                in_active_section = any(kw in stripped for kw in ACTIVE_KEYWORDS)
                continue
            if not in_active_section:
                continue
            refs = re.findall(r'((?:STORY|BUG)-\d+)', line)
            story_ids.extend(refs)

    seen = set()
    unique = []
    for sid in story_ids:
        if sid not in seen:
            seen.add(sid)
            unique.append(sid)
    return unique


def fetch_comments_for_context(
    story_ids: list[str],
    client: Any,
    max_chars: int = 2000,
) -> str:
    """Fetch recent provider comments for agent context."""
    if not client or not client.enabled or not story_ids:
        return ""
    try:
        return client.get_recent_comments_md(story_ids, max_chars=max_chars)
    except Exception as e:
        logger.warning("Provider: error fetching comments: %s", e)
        return ""
