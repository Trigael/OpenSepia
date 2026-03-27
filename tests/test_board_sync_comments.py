"""Tests targeting uncovered lines in board/comments.py and board/sync.py.

Complements the existing test_sync_comments.py and test_sync_board.py suites.
All provider calls are mocked via MagicMock.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opensepia.board.comments import (
    post_agent_messages_to_provider,
    fetch_comments_for_context,
    _try_approve_mr,
    _get_open_mrs,
    reset_mr_cache,
)
from opensepia.board.sync import sync_to_provider


# ============================================================================
# Helpers
# ============================================================================

def _make_client(**overrides):
    """Return a MagicMock provider client with sane defaults."""
    client = MagicMock()
    client.enabled = True
    client.find_issue_by_id = MagicMock(return_value=42)
    client.comment_on_issue = MagicMock(return_value={"id": 1})
    client.comment_on_mr = MagicMock(return_value={"id": 2})
    client.approve_mr = MagicMock(return_value={"id": 3})
    client.list_mrs = MagicMock(return_value=[])
    client.get_recent_comments_md = MagicMock(return_value="")
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


def _review_file(story="STORY-001", mr_ref="", extra=""):
    """Build a written_files entry that looks like a review inbox message."""
    body = f"## Code Review\n{story} looks good.{extra}"
    if mr_ref:
        body += f"\nSee {mr_ref} for details."
    return {"path": "project/board/inbox/reviewer.md", "content": body}


# ============================================================================
# post_agent_messages_to_provider
# ============================================================================

class TestPostAgentMessages:
    """Covers lines 51, 59/69, 77, 81-82, 87-94, 99-106."""

    def test_returns_0_when_client_is_none(self):
        assert post_agent_messages_to_provider("agent", [], None) == 0

    def test_returns_0_when_client_disabled(self):
        client = _make_client()
        client.enabled = False
        assert post_agent_messages_to_provider("agent", [_review_file()], client) == 0

    def test_skips_non_inbox_files(self):
        client = _make_client()
        files = [{"path": "project/board/sprint.md", "content": "## Code Review\nSTORY-001"}]
        assert post_agent_messages_to_provider("agent", files, client) == 0
        client.find_issue_by_id.assert_not_called()

    def test_skips_empty_content(self):
        client = _make_client()
        files = [{"path": "project/board/inbox/dev.md", "content": "   "}]
        assert post_agent_messages_to_provider("agent", files, client) == 0

    def test_skips_non_review_messages(self):
        client = _make_client()
        files = [{"path": "project/board/inbox/dev.md",
                  "content": "Implemented STORY-001: added endpoint"}]
        assert post_agent_messages_to_provider("agent", files, client) == 0
        client.find_issue_by_id.assert_not_called()

    def test_skips_review_with_no_story_refs(self):
        reset_mr_cache()
        client = _make_client()
        files = [{"path": "project/board/inbox/dev.md",
                  "content": "## Code Review\nEverything looks fine."}]
        assert post_agent_messages_to_provider("agent", files, client) == 0

    def test_posts_comment_for_story_ref(self):
        reset_mr_cache()
        client = _make_client()
        files = [_review_file("STORY-010")]
        count = post_agent_messages_to_provider("reviewer", files, client)
        assert count == 1
        client.find_issue_by_id.assert_called_once_with("STORY-010")
        client.comment_on_issue.assert_called_once()

    def test_find_issue_returns_none_skips(self):
        """Line 77: find_issue_by_id returns None -> skip."""
        reset_mr_cache()
        client = _make_client()
        client.find_issue_by_id.return_value = None
        files = [_review_file("STORY-099")]
        count = post_agent_messages_to_provider("agent", files, client)
        assert count == 0
        client.comment_on_issue.assert_not_called()

    def test_posts_on_mr_refs(self):
        """Lines 87-94: post comments on MRs referenced by !123."""
        reset_mr_cache()
        client = _make_client()
        files = [_review_file("STORY-001", mr_ref="!55")]
        count = post_agent_messages_to_provider("agent", files, client)
        # 1 from story + 1 from MR ref
        assert count >= 2
        # Verify comment_on_mr was called with mr_iid=55
        mr_calls = [c for c in client.comment_on_mr.call_args_list if c[0][0] == 55]
        assert len(mr_calls) >= 1

    def test_mr_ref_error_handled(self):
        """Lines 87-94: OSError on comment_on_mr is caught."""
        reset_mr_cache()
        client = _make_client()
        client.comment_on_mr.side_effect = OSError("connection failed")
        files = [_review_file("STORY-001", mr_ref="!10")]
        # Should not raise
        count = post_agent_messages_to_provider("agent", files, client)
        # story comment still counts
        assert count == 1

    def test_issue_comment_error_handled(self):
        """Lines 81-82: error from comment_on_issue is caught."""
        reset_mr_cache()
        client = _make_client()
        client.comment_on_issue.side_effect = ValueError("bad request")
        files = [_review_file("STORY-001")]
        count = post_agent_messages_to_provider("agent", files, client)
        assert count == 0

    def test_approval_triggers_approve_mr(self):
        """Lines 91-92: approval content triggers _try_approve_mr on MR refs."""
        reset_mr_cache()
        client = _make_client()
        files = [{
            "path": "project/board/inbox/reviewer.md",
            "content": "## Code Review\nSTORY-001 LGTM, approved! See !77.",
        }]
        post_agent_messages_to_provider("reviewer", files, client)
        client.approve_mr.assert_called_with(77)

    def test_finds_mrs_for_stories(self):
        """Lines 99-106: _find_mrs_for_stories posts on discovered MRs."""
        reset_mr_cache()
        client = _make_client()
        client.list_mrs.return_value = [
            {"iid": 88, "source_branch": "ai-team/story001-s1c1", "title": "story001"},
        ]
        # No explicit !ref, so MR 88 is found via branch name
        files = [_review_file("STORY-001")]
        count = post_agent_messages_to_provider("agent", files, client)
        # 1 from issue comment + 1 from discovered MR
        assert count == 2
        # comment_on_mr called for MR 88
        client.comment_on_mr.assert_called_once()
        assert client.comment_on_mr.call_args[0][0] == 88

    def test_mrs_from_stories_error_handled(self):
        """Lines 99-106: error posting on discovered MR is caught."""
        reset_mr_cache()
        client = _make_client()
        client.list_mrs.return_value = [
            {"iid": 88, "source_branch": "ai-team/story001-s1c1", "title": "story001"},
        ]
        client.comment_on_mr.side_effect = KeyError("missing field")
        files = [_review_file("STORY-001")]
        count = post_agent_messages_to_provider("agent", files, client)
        # issue comment succeeded (1), MR comment failed (0)
        assert count == 1

    def test_approval_on_discovered_mr(self):
        """Lines 103-104: approval on MR found via _find_mrs_for_stories."""
        reset_mr_cache()
        client = _make_client()
        client.list_mrs.return_value = [
            {"iid": 99, "source_branch": "ai-team/story001-s1c1", "title": "story001"},
        ]
        files = [{
            "path": "project/board/inbox/reviewer.md",
            "content": "## Code Review\nSTORY-001 LGTM, approved!",
        }]
        post_agent_messages_to_provider("reviewer", files, client)
        client.approve_mr.assert_called_with(99)

    def test_comment_on_issue_returns_error_dict(self):
        """Line 79-80: result dict with 'error' key does not increment posted."""
        reset_mr_cache()
        client = _make_client()
        client.comment_on_issue.return_value = {"error": "rate limited"}
        files = [_review_file("STORY-001")]
        count = post_agent_messages_to_provider("agent", files, client)
        assert count == 0


# ============================================================================
# _try_approve_mr — lines 168-174
# ============================================================================

class TestTryApproveMr:

    def test_calls_approve_mr(self):
        client = _make_client()
        _try_approve_mr(client, 42, "reviewer")
        client.approve_mr.assert_called_once_with(42)

    def test_handles_error_gracefully(self):
        client = _make_client()
        client.approve_mr.side_effect = OSError("forbidden")
        # Should not raise
        _try_approve_mr(client, 42, "reviewer")

    def test_handles_value_error(self):
        client = _make_client()
        client.approve_mr.side_effect = ValueError("bad")
        _try_approve_mr(client, 10, "agent")

    def test_approve_returns_error_dict(self):
        """Line 171: result with 'error' key — no exception but logged differently."""
        client = _make_client()
        client.approve_mr.return_value = {"error": "already approved"}
        _try_approve_mr(client, 5, "agent")
        client.approve_mr.assert_called_once_with(5)


# ============================================================================
# fetch_comments_for_context — lines 226-238
# ============================================================================

class TestFetchCommentsForContext:

    def test_returns_empty_when_client_none(self):
        assert fetch_comments_for_context(["STORY-001"], None) == ""

    def test_returns_empty_when_disabled(self):
        client = _make_client()
        client.enabled = False
        assert fetch_comments_for_context(["STORY-001"], client) == ""

    def test_returns_empty_when_no_story_ids(self):
        client = _make_client()
        assert fetch_comments_for_context([], client) == ""

    def test_calls_get_recent_comments_md(self):
        client = _make_client()
        client.get_recent_comments_md.return_value = "## Comments\nSome comment"
        result = fetch_comments_for_context(["STORY-001", "STORY-002"], client, max_chars=500)
        assert result == "## Comments\nSome comment"
        client.get_recent_comments_md.assert_called_once_with(
            ["STORY-001", "STORY-002"], max_chars=500,
        )

    def test_handles_oserror(self):
        client = _make_client()
        client.get_recent_comments_md.side_effect = OSError("timeout")
        assert fetch_comments_for_context(["STORY-001"], client) == ""

    def test_handles_value_error(self):
        client = _make_client()
        client.get_recent_comments_md.side_effect = ValueError("bad json")
        assert fetch_comments_for_context(["STORY-001"], client) == ""

    def test_handles_key_error(self):
        client = _make_client()
        client.get_recent_comments_md.side_effect = KeyError("missing")
        assert fetch_comments_for_context(["STORY-001"], client) == ""


# ============================================================================
# _get_open_mrs / reset_mr_cache — cache behavior
# ============================================================================

class TestMrCache:

    def test_cache_avoids_repeated_calls(self):
        reset_mr_cache()
        client = _make_client()
        client.list_mrs.return_value = [{"iid": 1, "source_branch": "b", "title": "t"}]
        first = _get_open_mrs(client)
        second = _get_open_mrs(client)
        assert first is second
        client.list_mrs.assert_called_once()

    def test_reset_clears_cache(self):
        reset_mr_cache()
        client = _make_client()
        client.list_mrs.return_value = [{"iid": 1, "source_branch": "b", "title": "t"}]
        _get_open_mrs(client)
        reset_mr_cache()
        _get_open_mrs(client)
        assert client.list_mrs.call_count == 2


# ============================================================================
# sync_to_provider — lines 189-276
# ============================================================================

def _make_provider(**overrides):
    """Return a MagicMock BoardProvider with sane defaults."""
    prov = MagicMock()
    prov.name = "gitlab"
    prov.list_issues = MagicMock(return_value=[])
    prov.create_issue = MagicMock(return_value={"iid": 100})
    prov.update_issue_labels = MagicMock(return_value={"iid": 100})
    prov.close_issue = MagicMock(return_value={"iid": 100})
    prov.reopen_issue = MagicMock(return_value={"iid": 100})
    for k, v in overrides.items():
        setattr(prov, k, v)
    return prov


def _item(item_id="STORY-001", title="Auth", status="todo", priority="medium",
          is_bug=False, assigned=None):
    return {
        "id": item_id,
        "title": title,
        "description": "Some description",
        "priority": priority,
        "status": status,
        "assigned": assigned,
        "is_bug": is_bug,
    }


class TestSyncToProvider:

    def test_creates_new_issue(self):
        """Line 222-231: item not in provider -> create_issue."""
        prov = _make_provider()
        items = [_item("STORY-010", "New feature")]
        created, updated = sync_to_provider(items, {}, prov)
        assert created == 1
        assert updated == 0
        prov.create_issue.assert_called_once()
        call_args = prov.create_issue.call_args
        assert "[STORY-010]" in call_args[0][0]

    def test_creates_bug_with_prefix(self):
        prov = _make_provider()
        items = [_item("BUG-005", "Crash", is_bug=True)]
        sync_to_provider(items, {}, prov)
        title_arg = prov.create_issue.call_args[0][0]
        assert "type::bug" in prov.create_issue.call_args[1]["labels"]

    def test_create_with_assigned(self):
        prov = _make_provider()
        items = [_item("STORY-011", assigned="dev1")]
        sync_to_provider(items, {}, prov)
        desc_arg = prov.create_issue.call_args[0][1]
        assert "dev1" in desc_arg

    def test_create_error_does_not_count(self):
        """Line 230-231: create returns error."""
        prov = _make_provider()
        prov.create_issue.return_value = {"error": "forbidden"}
        items = [_item("STORY-010")]
        created, _ = sync_to_provider(items, {}, prov)
        assert created == 0

    def test_updates_labels_when_status_changes(self):
        """Lines 201-213: existing issue with different status -> update labels."""
        existing = {
            "iid": 42,
            "title": "[STORY-001] Auth",
            "labels": ["status::todo", "priority::medium"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [existing],  # opened
            [],           # closed
            [existing],   # refresh opened
            [],           # refresh closed
        ])
        items = [_item("STORY-001", status="todo")]
        sprint_statuses = {"STORY-001": "in_progress"}
        created, updated = sync_to_provider(items, sprint_statuses, prov)
        assert updated == 1
        prov.update_issue_labels.assert_called_once()

    def test_closes_done_issue(self):
        """Lines 219-221: status=done and state=opened -> close."""
        existing = {
            "iid": 42,
            "title": "[STORY-001] Auth",
            "labels": ["status::todo", "priority::medium"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [existing], [],  # initial
            [existing], [],  # refresh
        ])
        items = [_item("STORY-001")]
        sprint_statuses = {"STORY-001": "done"}
        sync_to_provider(items, sprint_statuses, prov)
        prov.close_issue.assert_called_with(42)

    def test_reopens_undone_closed_issue(self):
        """Lines 215-217: status != done but state=closed -> reopen."""
        existing = {
            "iid": 42,
            "title": "[STORY-001] Auth",
            "labels": ["status::done", "priority::medium"],
            "state": "closed",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [],
            [existing],  # closed
            [], [existing],  # refresh
        ])
        items = [_item("STORY-001")]
        sprint_statuses = {"STORY-001": "in_progress"}
        sync_to_provider(items, sprint_statuses, prov)
        prov.reopen_issue.assert_called_with(42)

    def test_sprint_only_item_updates_labels(self):
        """Lines 233-256: item in sprint_statuses but not in backlog items."""
        existing = {
            "iid": 50,
            "title": "[STORY-099] Sprint only",
            "labels": ["status::todo", "priority::medium"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [existing], [],  # initial
            [existing], [],  # refresh
        ])
        items = []  # no backlog items
        sprint_statuses = {"STORY-099": "in_progress"}
        created, updated = sync_to_provider(items, sprint_statuses, prov)
        assert created == 0
        assert updated == 1
        prov.update_issue_labels.assert_called_once()

    def test_sprint_only_item_no_provider_issue_skips(self):
        """Line 237-238: sprint-only item with no matching provider issue."""
        prov = _make_provider()
        items = []
        sprint_statuses = {"STORY-999": "in_progress"}
        created, updated = sync_to_provider(items, sprint_statuses, prov)
        assert created == 0
        assert updated == 0

    def test_sprint_only_closes_done(self):
        """Lines 253-254: sprint-only done item gets closed."""
        existing = {
            "iid": 60,
            "title": "[STORY-050] Done thing",
            "labels": ["status::review", "priority::medium"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [existing], [],  # initial
            [existing], [],  # refresh
        ])
        items = []
        sprint_statuses = {"STORY-050": "done"}
        sync_to_provider(items, sprint_statuses, prov)
        prov.close_issue.assert_called_with(60)

    def test_sprint_only_reopens_undone(self):
        """Lines 255-256: sprint-only non-done item in closed state gets reopened."""
        existing = {
            "iid": 61,
            "title": "[STORY-051] Reopened",
            "labels": ["status::done", "priority::medium"],
            "state": "closed",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [],
            [existing],  # closed
            [], [existing],  # refresh
        ])
        items = []
        sprint_statuses = {"STORY-051": "todo"}
        sync_to_provider(items, sprint_statuses, prov)
        prov.reopen_issue.assert_called_with(61)

    def test_exports_issue_map_cache(self, tmp_path):
        """Lines 258-276: writes .gitlab_issue_map.json when board_dir provided."""
        cached_issue = {
            "iid": 42,
            "title": "[STORY-001] Auth",
            "labels": ["status::todo"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [], [],           # initial (no existing)
            [cached_issue], [],  # refresh for cache export
        ])
        items = [_item("STORY-001")]
        sync_to_provider(items, {}, prov, board_dir=tmp_path)
        cache_path = tmp_path / ".gitlab_issue_map.json"
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert data["STORY-001"] == 42

    def test_cache_write_error_handled(self, tmp_path):
        """Line 275-276: OSError writing cache is caught."""
        prov = _make_provider()
        cached_issue = {
            "iid": 42,
            "title": "[STORY-001] Auth",
            "labels": ["status::todo"],
            "state": "opened",
        }
        prov.list_issues = MagicMock(side_effect=[
            [], [],
            [cached_issue], [],
        ])
        items = [_item("STORY-001")]
        # Use a non-writable path
        bad_dir = tmp_path / "readonly"
        bad_dir.mkdir()
        cache_file = bad_dir / f".{prov.name}_issue_map.json"
        cache_file.write_text("{}")
        cache_file.chmod(0o000)
        # Should not raise
        sync_to_provider(items, {}, prov, board_dir=bad_dir)
        cache_file.chmod(0o644)  # cleanup

    def test_no_board_dir_skips_cache(self):
        """Line 259: board_dir is None -> skip cache export."""
        prov = _make_provider()
        items = [_item("STORY-001")]
        sync_to_provider(items, {}, prov, board_dir=None)
        # list_issues called only for initial open + closed (2 calls)
        assert prov.list_issues.call_count == 2

    def test_sprint_only_same_status_no_update(self):
        """Sprint-only item with matching status -> no update."""
        existing = {
            "iid": 70,
            "title": "[STORY-070] Same",
            "labels": ["status::in-progress", "priority::medium"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [existing], [],  # initial
            [existing], [],  # refresh
        ])
        items = []
        sprint_statuses = {"STORY-070": "in_progress"}
        created, updated = sync_to_provider(items, sprint_statuses, prov)
        assert updated == 0
        prov.update_issue_labels.assert_not_called()

    def test_update_returns_error_not_counted(self):
        """Line 211-212: update_issue_labels returns error dict."""
        existing = {
            "iid": 42,
            "title": "[STORY-001] Auth",
            "labels": ["status::todo", "priority::medium"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [existing], [],
            [existing], [],
        ])
        prov.update_issue_labels.return_value = {"error": "forbidden"}
        items = [_item("STORY-001")]
        sprint_statuses = {"STORY-001": "review"}
        _, updated = sync_to_provider(items, sprint_statuses, prov)
        assert updated == 0

    def test_backlog_item_skipped_in_sprint_only_loop(self):
        """Line 235-236: item present in both backlog and sprint is not double-processed."""
        existing = {
            "iid": 42,
            "title": "[STORY-001] Auth",
            "labels": ["status::todo", "priority::medium"],
            "state": "opened",
        }
        prov = _make_provider()
        prov.list_issues = MagicMock(side_effect=[
            [existing], [],
            [existing], [],
        ])
        items = [_item("STORY-001")]
        sprint_statuses = {"STORY-001": "in_progress"}
        sync_to_provider(items, sprint_statuses, prov)
        # update_issue_labels called only once (from backlog loop), not twice
        assert prov.update_issue_labels.call_count == 1

    def test_unmatched_sprint_section_resets_current_status(self):
        """Line 139-140 of parse_sprint_statuses: unmatched ## header sets current_status to None."""
        from opensepia.board.sync import parse_sprint_statuses
        sprint_content = """\
# Sprint

## Miscellaneous Notes
- [ ] STORY-500: Should not be picked up

## IN PROGRESS
- [ ] STORY-501: Actual in progress
"""
        p = Path("/tmp/test_sprint_unmatched.md")
        p.write_text(sprint_content, encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        assert "STORY-500" not in statuses
        assert statuses.get("STORY-501") == "in_progress"
        p.unlink()
