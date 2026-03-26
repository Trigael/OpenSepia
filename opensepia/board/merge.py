"""
AI Dev Team — Auto-merge approved MRs + cleanup of stale branches.

After completing an agent cycle:
1. Merges approved MRs (ai-team/* branches)
2. Closes stale MRs (older than 2 days without approvals)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from opensepia.integrations.base import BoardProvider

logger = logging.getLogger(__name__)

STALE_DAYS = 2


def _parse_provider_date(date_str: str) -> datetime:
    """Parse an ISO 8601 date from a provider."""
    date_str = date_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _is_our_branch(mr: dict) -> bool:
    """Filter only ai-team/ branches (our MRs, not manual ones)."""
    return mr.get("source_branch", "").startswith("ai-team/")


def _parse_cycle_number(branch_name: str) -> int:
    """Extract cycle number from branch name (ai-team/sprint-X-cycle-Y -> Y)."""
    try:
        return int(branch_name.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return 0


def merge_approved_mrs(client: BoardProvider) -> tuple[int, int]:
    """Merge approved MRs and close stale ones.

    Strategy: the newest cycle gets merged, older ones are closed as superseded
    (each cycle contains the complete workspace state, so the newest = the most complete).

    Returns:
        (merged_count, closed_count)
    """
    if not client.enabled:
        logger.warning("Provider is not configured — skipping auto-merge")
        return 0, 0

    mrs = client.list_mrs("opened")
    if not mrs:
        logger.info("No open MRs")
        return 0, 0

    our_mrs = [mr for mr in mrs if _is_our_branch(mr)]
    if not our_mrs:
        logger.info("No ai-team/ MRs to process")
        return 0, 0

    our_mrs.sort(key=lambda m: _parse_cycle_number(m.get("source_branch", "")), reverse=True)

    merged = 0
    closed = 0
    newest_merged = False
    now = datetime.now(timezone.utc)

    for mr in our_mrs:
        iid = mr.get("iid")
        title = mr.get("title", "?")
        branch = mr.get("source_branch", "?")

        detail = client.get_mr(iid)
        if "error" in detail:
            logger.warning("MR !%s: cannot get details — %s", iid, detail)
            continue

        merge_status = detail.get("detailed_merge_status", detail.get("merge_status", ""))
        created_at = _parse_provider_date(detail.get("created_at", ""))
        age = now - created_at

        approvals = client.get_mr_approvals(iid)
        is_approved = approvals.get("approved", False)
        can_merge = merge_status in ("can_be_merged", "mergeable")

        if not newest_merged and can_merge and is_approved:
            logger.info("MR !%s '%s' (%s) — merging (newest, approved)", iid, title, branch)
            result = client.merge_mr(iid, squash=False)
            if "error" not in result:
                merged += 1
                newest_merged = True
            else:
                logger.warning("MR !%s merge failed: %s", iid, result)
            continue

        if newest_merged:
            logger.info("MR !%s '%s' (%s) — closing (superseded)", iid, title, branch)
            client.comment_on_mr(iid,
                "Automatically closed — a newer cycle was merged, this MR is superseded.",
                agent_id="orchestrator")
            result = client.close_mr(iid)
            if "error" not in result:
                closed += 1
            continue

        if not can_merge and is_approved:
            logger.info("MR !%s '%s' (%s) — closing (conflicts)", iid, title, branch)
            client.comment_on_mr(iid,
                f"Automatically closed — MR has conflicts ({merge_status}). "
                "Next cycle will create a new MR from current main.",
                agent_id="orchestrator")
            result = client.close_mr(iid)
            if "error" not in result:
                closed += 1
            continue

        if age > timedelta(days=STALE_DAYS) and not is_approved:
            logger.info("MR !%s '%s' — closing (stale: %dd)", iid, title, age.days)
            client.comment_on_mr(iid,
                f"Automatically closed — MR is older than {STALE_DAYS} days without approvals.",
                agent_id="orchestrator")
            result = client.close_mr(iid)
            if "error" not in result:
                closed += 1
            continue

        logger.info("MR !%s '%s' — skipped (status=%s, approved=%s, age=%dd)",
                     iid, title, merge_status, is_approved, age.days)

    return merged, closed
