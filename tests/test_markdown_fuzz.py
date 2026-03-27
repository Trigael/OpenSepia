"""Fuzz and edge-case tests for the Markdown board adapter parser.

Covers: empty/whitespace files, malformed markdown, unicode/emoji,
extremely long lines, markdown injection, duplicate IDs, invalid statuses,
missing fields, mixed line endings, special characters, deeply nested
structures, credential-like strings, and more.
"""

import pytest
from pathlib import Path

from opensepia.board_adapter_markdown import (
    MarkdownBoardAdapter,
    MAX_BACKLOG_CHARS,
    MAX_PROJECT_CHARS,
)
from opensepia.board_adapter import STORY_BUG_ID_RE
from opensepia.config import MAX_STANDUP_CHARS, MAX_INBOX_CHARS
from opensepia.agents.parser import ParsedFile
from opensepia.board.sync import parse_backlog, normalize_status, parse_sprint_statuses


# =============================================================================
# Helpers
# =============================================================================

def _adapter(tmp_path, sprint="", backlog="", project="", standup=""):
    """Create a MarkdownBoardAdapter with given board file contents."""
    board = tmp_path / "board"
    board.mkdir(exist_ok=True)
    (board / "inbox").mkdir(exist_ok=True)
    (board / "archive").mkdir(exist_ok=True)
    for a in ["po", "dev1"]:
        (board / "inbox" / f"{a}.md").write_text("", encoding="utf-8")

    if sprint is not None:
        (board / "sprint.md").write_text(sprint, encoding="utf-8")
    if backlog is not None:
        (board / "backlog.md").write_text(backlog, encoding="utf-8")
    if project is not None:
        (board / "project.md").write_text(project, encoding="utf-8")
    if standup is not None:
        (board / "standup.md").write_text(standup, encoding="utf-8")

    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return MarkdownBoardAdapter(board_dir=board, workspace_dir=ws, project_dir=tmp_path), board


def _agents_config():
    return {
        "agents": {"dev1": {"name": "Dev1", "system_prompt": "You are Dev1."}},
        "global": {"standup_instruction": "", "communication_rules": ""},
    }


def _project_config():
    return {"sprint": {"current_sprint": 1, "current_cycle": 1}}


# =============================================================================
# Empty / whitespace-only files
# =============================================================================

class TestEmptyFiles:
    def test_empty_sprint(self, tmp_path):
        adapter, _ = _adapter(tmp_path, sprint="")
        assert adapter.get_active_story_ids() == []
        assert adapter.get_board_summary() == {}
        assert adapter.get_sprint_number() == 1

    def test_whitespace_only_sprint(self, tmp_path):
        adapter, _ = _adapter(tmp_path, sprint="   \n\n\t\n  ")
        assert adapter.get_active_story_ids() == []
        assert adapter.get_board_summary() == {}

    def test_empty_backlog(self, tmp_path):
        adapter, _ = _adapter(tmp_path, backlog="")
        assert adapter.get_backlog_text() == ""

    def test_whitespace_only_backlog(self, tmp_path):
        adapter, _ = _adapter(tmp_path, backlog="\n\n  \t  \n")
        text = adapter.get_backlog_text()
        assert text.strip() == ""

    def test_empty_project(self, tmp_path):
        adapter, _ = _adapter(tmp_path, project="")
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert ctx.project_description == ""

    def test_empty_standup(self, tmp_path):
        adapter, _ = _adapter(tmp_path, standup="")
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert ctx.standup == ""

    def test_missing_sprint_file(self, tmp_path):
        """Sprint file does not exist at all."""
        board = tmp_path / "board"
        board.mkdir()
        (board / "inbox").mkdir()
        for a in ["dev1"]:
            (board / "inbox" / f"{a}.md").write_text("", encoding="utf-8")
        ws = tmp_path / "workspace"
        ws.mkdir()
        adapter = MarkdownBoardAdapter(board_dir=board, workspace_dir=ws, project_dir=tmp_path)
        assert adapter.get_active_story_ids() == []
        assert adapter.get_sprint_number() == 1
        assert adapter.get_board_summary() == {}


# =============================================================================
# Malformed markdown
# =============================================================================

class TestMalformedMarkdown:
    def test_missing_h1_header(self, tmp_path):
        adapter, _ = _adapter(tmp_path, sprint="## TODO\n- [ ] STORY-001: No header\n")
        ids = adapter.get_active_story_ids()
        assert "STORY-001" in ids

    def test_broken_table_in_sprint(self, tmp_path):
        content = "# Sprint 1\n\n| Col1 | Col2\n| broken | row |\n\n## TODO\n- [ ] STORY-010: After table\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-010" in ids

    def test_unclosed_code_block(self, tmp_path):
        content = "# Sprint 1\n\n```python\ndef foo():\n    pass\n\n## TODO\n- [ ] STORY-020: After code\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        # The parser treats lines literally, so it should still find the story
        ids = adapter.get_active_story_ids()
        assert "STORY-020" in ids

    def test_no_section_headers_at_all(self, tmp_path):
        content = "# Sprint 1\n\nJust some text, no ## sections.\n- [ ] STORY-030: Orphan\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        # No active section, so story should NOT be included
        assert "STORY-030" not in ids

    def test_h2_with_no_items(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n\n## IN PROGRESS\n\n## DONE\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        assert adapter.get_active_story_ids() == []
        summary = adapter.get_board_summary()
        # Sections exist but have zero items
        assert summary.get("todo", 0) == 0

    def test_only_h1_no_content(self, tmp_path):
        adapter, _ = _adapter(tmp_path, sprint="# Sprint 1\n")
        assert adapter.get_active_story_ids() == []

    def test_malformed_checkbox(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [x STORY-040: Bad checkbox\n- [] STORY-041: No space\n- [?] STORY-042: Unknown mark\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        summary = adapter.get_board_summary()
        # Only '- [' prefix triggers counting; '- [x' starts with '- [' so should count
        # '- []' also starts with '- ['
        # '- [?]' also starts with '- ['
        assert summary.get("todo", 0) >= 0  # Should not crash


# =============================================================================
# Unicode / emoji in IDs, statuses, agent names
# =============================================================================

class TestUnicode:
    def test_emoji_in_story_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-050: \U0001F680 Rocket feature\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-050" in ids

    def test_unicode_section_header(self, tmp_path):
        content = "# Sprint 1\n\n## \u2705 TODO\n- [ ] STORY-051: Under unicode header\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        # Section header has a checkmark prefix, won't match "todo" exactly
        ids = adapter.get_active_story_ids()
        # The parser checks stripped.lower() against active_statuses set
        # "\u2705 todo" won't match "todo" so it won't be found
        assert "STORY-051" not in ids

    def test_cjk_in_project_description(self, tmp_path):
        adapter, _ = _adapter(tmp_path, project="# \u30D7\u30ED\u30B8\u30A7\u30AF\u30C8\n\u3053\u308C\u306F\u30C6\u30B9\u30C8\u3067\u3059\u3002\n")
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert "\u30D7\u30ED\u30B8\u30A7\u30AF\u30C8" in ctx.project_description

    def test_rtl_text_in_backlog(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n### STORY-052: \u0645\u0634\u0631\u0648\u0639 \u062C\u062F\u064A\u062F\n**Status**: TODO\n"
        adapter, _ = _adapter(tmp_path, backlog=content)
        text = adapter.get_backlog_text()
        assert "STORY-052" in text

    def test_emoji_agent_name_inbox(self, tmp_path):
        adapter, board = _adapter(tmp_path)
        adapter.send_inbox_message("dev1", "\U0001F916 Bot", "Hello from bot")
        content = (board / "inbox" / "dev1.md").read_text(encoding="utf-8")
        assert "\U0001F916 Bot" in content

    def test_zero_width_chars_in_story_id(self, tmp_path):
        """Zero-width joiner inserted inside a story ID should not match."""
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY\u200B-060: Zero width\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        # The zero-width char breaks the regex match
        assert "STORY-060" not in ids


# =============================================================================
# Extremely long lines
# =============================================================================

class TestLongLines:
    def test_10k_char_story_title(self, tmp_path):
        title = "A" * 10000
        content = f"# Sprint 1\n\n## TODO\n- [ ] STORY-070: {title}\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-070" in ids

    def test_huge_project_truncated(self, tmp_path):
        big = "x" * (MAX_PROJECT_CHARS + 5000)
        adapter, _ = _adapter(tmp_path, project=big)
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert len(ctx.project_description) == MAX_PROJECT_CHARS

    def test_huge_backlog_truncated(self, tmp_path):
        big = "y" * (MAX_BACKLOG_CHARS + 5000)
        adapter, _ = _adapter(tmp_path, backlog=big)
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert len(ctx.backlog_md) == MAX_BACKLOG_CHARS

    def test_huge_standup_truncated(self, tmp_path):
        big = "z" * (MAX_STANDUP_CHARS + 5000)
        adapter, _ = _adapter(tmp_path, standup=big)
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert len(ctx.standup) <= MAX_STANDUP_CHARS + 50  # allow for truncation marker

    def test_many_stories_in_single_section(self, tmp_path):
        lines = ["# Sprint 1\n", "## TODO\n"]
        for i in range(500):
            lines.append(f"- [ ] STORY-{1000 + i}: Story number {i}\n")
        content = "".join(lines)
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert len(ids) == 500
        summary = adapter.get_board_summary()
        assert summary.get("todo") == 500


# =============================================================================
# Markdown injection (nested headers, HTML tags)
# =============================================================================

class TestMarkdownInjection:
    def test_nested_headers_in_story_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-080: ## Fake header in title\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-080" in ids

    def test_html_tags_in_sprint(self, tmp_path):
        content = "# Sprint 1\n\n<script>alert('xss')</script>\n\n## TODO\n- [ ] STORY-081: Normal\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-081" in ids

    def test_html_comment_hiding_section(self, tmp_path):
        content = "# Sprint 1\n\n<!-- ## TODO\n- [ ] STORY-082: Hidden -->\n\n## IN PROGRESS\n- [ ] STORY-083: Visible\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        # Parser treats lines literally, the comment line starts with <!--
        # "## TODO" inside comment is prefixed with "<!-- " so won't match "## "
        assert "STORY-083" in ids

    def test_details_tag_in_standup_strips_correctly(self, tmp_path):
        standup = "Current work\n<details><summary>Old</summary>\nold content\n</details>\n<details>more old</details>\n"
        adapter, _ = _adapter(tmp_path, standup=standup)
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        assert "old content" not in ctx.standup
        assert "Current work" in ctx.standup

    def test_nested_details_tags(self, tmp_path):
        standup = "Work done\n<details>\n<details>nested</details>\nstill inside\n</details>\n"
        adapter, _ = _adapter(tmp_path, standup=standup)
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        # First <details> is found and everything after is stripped
        assert "nested" not in ctx.standup
        assert "Work done" in ctx.standup

    def test_h2_inside_code_block_not_treated_as_section(self, tmp_path):
        """In a real markdown parser, ## inside ``` is not a header.
        But our line-by-line parser will still treat it as one."""
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-090: Real\n\n```\n## DONE\n- [x] STORY-091: In code block\n```\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-090" in ids
        # The parser will see ## DONE and switch context, so STORY-091 won't be active
        assert "STORY-091" not in ids


# =============================================================================
# Duplicate story IDs
# =============================================================================

class TestDuplicateIDs:
    def test_same_id_in_two_sections(self, tmp_path):
        content = (
            "# Sprint 1\n\n"
            "## TODO\n- [ ] STORY-100: First occurrence\n\n"
            "## IN PROGRESS\n- [ ] STORY-100: Duplicate\n"
        )
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert ids.count("STORY-100") == 2

    def test_duplicate_in_board_summary(self, tmp_path):
        content = (
            "# Sprint 1\n\n"
            "## TODO\n- [ ] STORY-101: A\n- [ ] STORY-101: B\n"
        )
        adapter, _ = _adapter(tmp_path, sprint=content)
        summary = adapter.get_board_summary()
        assert summary.get("todo") == 2  # Counts items, not unique IDs

    def test_duplicate_id_in_backlog_parse(self, tmp_path):
        content = (
            "# Backlog\n\n## HIGH\n"
            "### STORY-102: First\n**Status**: TODO\n\n"
            "### STORY-102: Second\n**Status**: IN_PROGRESS\n"
        )
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        ids = [i["id"] for i in items]
        assert ids.count("STORY-102") == 2


# =============================================================================
# Invalid status values
# =============================================================================

class TestInvalidStatus:
    def test_garbage_status_normalizes_to_todo(self):
        assert normalize_status("asdfghjkl") == "todo"

    def test_empty_status_normalizes_to_todo(self):
        assert normalize_status("") == "todo"

    def test_whitespace_status_normalizes_to_todo(self):
        assert normalize_status("   ") == "todo"

    def test_numeric_status(self):
        assert normalize_status("12345") == "todo"

    def test_status_with_special_chars(self):
        assert normalize_status("!@#$%^&*()") == "todo"

    def test_status_with_sql_injection(self):
        assert normalize_status("'; DROP TABLE stories; --") == "todo"

    def test_extremely_long_status(self):
        assert normalize_status("x" * 10000) == "todo"

    def test_status_with_newlines(self):
        assert normalize_status("TODO\nIN_PROGRESS") == "todo"

    def test_unknown_section_header_in_sprint(self, tmp_path):
        content = "# Sprint 1\n\n## ABANDONED\n- [ ] STORY-110: Lost\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        # "abandoned" is not in active_statuses, so this should not appear
        assert "STORY-110" not in ids

    def test_partial_status_match(self):
        # "in progress" is a valid status, but what about partial matches?
        assert normalize_status("in") == "todo"
        assert normalize_status("don") == "todo"


# =============================================================================
# Missing required fields
# =============================================================================

class TestMissingFields:
    def test_story_with_no_status_in_backlog(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n### STORY-120: No status field\nJust a description.\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        assert len(items) == 1
        assert items[0]["status"] == "todo"  # Default

    def test_story_with_no_title(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n### STORY-121:\n**Status**: TODO\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        # The regex requires ': .+' so empty title after colon might not match
        # Depends on regex: r'^###\s+((?:STORY|BUG)-\d+):\s*(.+)'
        # '.+' requires at least one char, so empty title won't match
        assert len(items) == 0

    def test_story_with_no_assigned(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n### STORY-122: Unassigned\n**Status**: TODO\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        assert len(items) == 1
        assert items[0]["assigned"] is None

    def test_no_sprint_number_in_header(self, tmp_path):
        adapter, _ = _adapter(tmp_path, sprint="# Current Work\n\n## TODO\n- [ ] STORY-123: Item\n")
        # get_sprint_number uses regex Sprint\s+(\d+) — no match returns 1
        assert adapter.get_sprint_number() == 1

    def test_apply_output_empty_path(self, tmp_path):
        adapter, _ = _adapter(tmp_path)
        files = [ParsedFile(path="", content="data", action="write")]
        count = adapter.apply_agent_output("dev1", files, _agents_config())
        assert count == 0

    def test_apply_output_none_content(self, tmp_path):
        adapter, _ = _adapter(tmp_path)
        files = [ParsedFile(path="board/test.md", content="", action="write")]
        count = adapter.apply_agent_output("dev1", files, _agents_config())
        assert count == 0


# =============================================================================
# Files with only comments (HTML comments)
# =============================================================================

class TestOnlyComments:
    def test_sprint_only_html_comments(self, tmp_path):
        content = "<!-- This is a comment -->\n<!-- Another comment -->\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert ids == []

    def test_backlog_only_comments(self, tmp_path):
        content = "<!-- TODO: fill in backlog -->\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        assert items == []


# =============================================================================
# Mixed line endings
# =============================================================================

class TestMixedLineEndings:
    def test_crlf_line_endings(self, tmp_path):
        content = "# Sprint 1\r\n\r\n## TODO\r\n- [ ] STORY-130: CRLF\r\n\r\n## DONE\r\n- [x] STORY-131: Done CRLF\r\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-130" in ids
        assert "STORY-131" not in ids

    def test_cr_only_line_endings(self, tmp_path):
        content = "# Sprint 1\r\r## TODO\r- [ ] STORY-132: CR only\r"
        # Write as binary to preserve \r
        board = tmp_path / "board"
        board.mkdir(exist_ok=True)
        (board / "inbox").mkdir(exist_ok=True)
        (board / "inbox" / "dev1.md").write_text("", encoding="utf-8")
        (board / "sprint.md").write_bytes(content.encode("utf-8"))
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        adapter = MarkdownBoardAdapter(board_dir=board, workspace_dir=ws, project_dir=tmp_path)
        # \r only doesn't split on \n, so all content is one big line
        ids = adapter.get_active_story_ids()
        # Likely won't find it since split("\n") won't break lines
        # Just verify it doesn't crash
        assert isinstance(ids, list)

    def test_mixed_lf_crlf(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\r\n- [ ] STORY-133: Mixed\n\n## DONE\r\n- [x] STORY-134: Done\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        # \r\n split on \n leaves \r at end, but strip() in parser removes it
        assert "STORY-133" in ids

    def test_crlf_backlog(self, tmp_path):
        content = "# Backlog\r\n\r\n## HIGH\r\n### STORY-135: CRLF backlog\r\n**Status**: TODO\r\n"
        p = tmp_path / "backlog.md"
        p.write_bytes(content.encode("utf-8"))
        items = parse_backlog(p)
        assert len(items) == 1
        assert items[0]["id"] == "STORY-135"


# =============================================================================
# Special characters in story titles
# =============================================================================

class TestSpecialChars:
    def test_pipe_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-140: Use | operator in query\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-140" in ids

    def test_brackets_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-141: Fix [urgent] issue\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-141" in ids

    def test_backticks_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-142: Fix `main()` function\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-142" in ids

    def test_parentheses_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-143: Refactor (phase 1)\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-143" in ids

    def test_asterisks_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-144: **Bold** and *italic*\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-144" in ids

    def test_hash_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-145: Issue #42 fix\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-145" in ids

    def test_backslash_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-146: Fix C:\\path\\file\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-146" in ids

    def test_url_in_title(self, tmp_path):
        content = "# Sprint 1\n\n## TODO\n- [ ] STORY-147: See https://example.com/issue?id=1&foo=bar\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-147" in ids

    def test_backlog_title_with_colon(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n### STORY-148: Config: update settings\n**Status**: TODO\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        assert len(items) == 1
        assert "Config" in items[0]["title"]


# =============================================================================
# Deeply nested markdown structures
# =============================================================================

class TestDeeplyNested:
    def test_many_header_levels(self, tmp_path):
        content = (
            "# Sprint 1\n\n## TODO\n### Sub-section\n#### Sub-sub\n##### Deep\n"
            "- [ ] STORY-150: Deep item\n"
        )
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-150" in ids

    def test_nested_lists(self, tmp_path):
        content = (
            "# Sprint 1\n\n## TODO\n"
            "- [ ] STORY-151: Parent\n"
            "  - [ ] STORY-152: Child\n"
            "    - [ ] STORY-153: Grandchild\n"
        )
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-151" in ids
        # Indented items: strip() + startswith("- [") should still match
        assert "STORY-152" in ids
        assert "STORY-153" in ids

    def test_100_nested_blockquotes(self, tmp_path):
        prefix = "> " * 100
        content = f"# Sprint 1\n\n## TODO\n{prefix}- [ ] STORY-154: Very quoted\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        # The line won't start with "- [" after strip since it starts with "> > > ..."
        ids = adapter.get_active_story_ids()
        # Should not crash
        assert isinstance(ids, list)


# =============================================================================
# Stories with no status field
# =============================================================================

class TestNoStatusField:
    def test_sprint_item_without_explicit_status(self, tmp_path):
        """Sprint items derive status from section header, not from an explicit field."""
        content = "# Sprint 1\n\n## IN PROGRESS\n- [ ] STORY-160: No status field\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-160" in ids

    def test_sprint_statuses_from_section_headers(self, tmp_path):
        content = "# Sprint 1\n\n## REVIEW\n- [ ] STORY-161: Needs review\n"
        p = tmp_path / "sprint.md"
        p.write_text(content, encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        assert statuses.get("STORY-161") == "review"


# =============================================================================
# Conflicting status sections in sprint
# =============================================================================

class TestConflictingSections:
    def test_duplicate_todo_sections(self, tmp_path):
        content = (
            "# Sprint 1\n\n"
            "## TODO\n- [ ] STORY-170: First TODO\n\n"
            "## IN PROGRESS\n- [ ] STORY-171: Working\n\n"
            "## TODO\n- [ ] STORY-172: Second TODO\n"
        )
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-170" in ids
        assert "STORY-171" in ids
        assert "STORY-172" in ids

    def test_duplicate_section_board_summary(self, tmp_path):
        content = (
            "# Sprint 1\n\n"
            "## TODO\n- [ ] STORY-173: A\n\n"
            "## TODO\n- [ ] STORY-174: B\n"
        )
        adapter, _ = _adapter(tmp_path, sprint=content)
        summary = adapter.get_board_summary()
        # Second ## TODO overwrites current_section but summary accumulates
        assert summary.get("todo", 0) == 2

    def test_same_story_in_todo_and_done(self, tmp_path):
        """Story appears in both TODO and DONE sections."""
        content = (
            "# Sprint 1\n\n"
            "## TODO\n- [ ] STORY-175: Confused\n\n"
            "## DONE\n- [x] STORY-175: Confused\n"
        )
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        # TODO is active, DONE is not, so we get one occurrence from TODO
        assert "STORY-175" in ids

    def test_conflicting_section_sprint_statuses(self, tmp_path):
        content = (
            "# Sprint 1\n\n"
            "## TODO\n- [ ] STORY-176: Was TODO\n\n"
            "## DONE\n- [x] STORY-176: Now DONE\n"
        )
        p = tmp_path / "sprint.md"
        p.write_text(content, encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        # Second occurrence overwrites the first in the dict
        assert statuses["STORY-176"] == "done"


# =============================================================================
# Backlog with items in wrong format
# =============================================================================

class TestWrongFormatBacklog:
    def test_h2_stories_not_h3(self, tmp_path):
        content = "# Backlog\n\n## STORY-180: Wrong level\n**Status**: TODO\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        # Parser expects ### not ##, so this should not be parsed as a story
        assert len(items) == 0

    def test_no_colon_after_id(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n### STORY-181 Missing colon\n**Status**: TODO\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        # Regex requires ': ' after ID
        assert len(items) == 0

    def test_bullet_list_instead_of_headers(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n- STORY-182: As bullet\n- STORY-183: Another bullet\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        # Parser expects ### prefix
        assert len(items) == 0

    def test_numbered_list_stories(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n1. STORY-184: Numbered\n2. STORY-185: Also numbered\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        assert len(items) == 0

    def test_story_id_without_number(self, tmp_path):
        content = "# Backlog\n\n## HIGH\n### STORY-: No number\n**Status**: TODO\n"
        p = tmp_path / "backlog.md"
        p.write_text(content, encoding="utf-8")
        items = parse_backlog(p)
        # Regex requires \d+ after dash
        assert len(items) == 0


# =============================================================================
# Inbox files with malformed content
# =============================================================================

class TestMalformedInbox:
    def test_inbox_with_binary_like_content(self, tmp_path):
        adapter, board = _adapter(tmp_path)
        garbage = "".join(chr(i) for i in range(1, 128))
        (board / "inbox" / "dev1.md").write_text(garbage, encoding="utf-8")
        content = adapter.get_inbox("dev1")
        assert isinstance(content, str)

    def test_inbox_huge_content_in_context(self, tmp_path):
        adapter, board = _adapter(tmp_path)
        huge = "Important message\n" * 10000
        (board / "inbox" / "dev1.md").write_text(huge, encoding="utf-8")
        # get_inbox reads full content (no truncation at this level)
        content = adapter.get_inbox("dev1")
        assert "Important message" in content

    def test_inbox_with_null_bytes(self, tmp_path):
        adapter, board = _adapter(tmp_path)
        # Write content with null bytes (common in binary file confusion)
        content = "Hello\x00World\x00End"
        (board / "inbox" / "dev1.md").write_text(content, encoding="utf-8")
        result = adapter.get_inbox("dev1")
        assert isinstance(result, str)

    def test_archive_inbox_with_only_whitespace(self, tmp_path):
        adapter, board = _adapter(tmp_path)
        (board / "inbox" / "dev1.md").write_text("   \n\t\n  ", encoding="utf-8")
        adapter.archive_inbox("dev1")
        # Whitespace-only content should not be archived (strip() returns empty)
        archive_dir = board / "archive" / "dev1"
        assert not archive_dir.exists() or len(list(archive_dir.glob("*.md"))) == 0

    def test_send_message_to_nonexistent_agent(self, tmp_path):
        adapter, board = _adapter(tmp_path)
        # Should create the inbox file on demand
        adapter.send_inbox_message("nonexistent_agent", "PM", "Hello")
        assert (board / "inbox" / "nonexistent_agent.md").exists()


# =============================================================================
# Credential-like strings in board content (should not leak)
# =============================================================================

class TestCredentialStrings:
    def test_api_key_in_project_description(self, tmp_path):
        content = "# Project\nAPI_KEY=sk-1234567890abcdef\nSECRET_TOKEN=ghp_abc123\n"
        adapter, _ = _adapter(tmp_path, project=content)
        ctx = adapter.get_agent_context("dev1", _agents_config(), _project_config())
        # The adapter does not filter credentials (it's a pass-through)
        # This test documents the current behavior
        assert "sk-1234567890abcdef" in ctx.project_description

    def test_password_in_sprint(self, tmp_path):
        content = "# Sprint 1\n\npassword: hunter2\naws_secret_access_key=AKIA1234\n\n## TODO\n- [ ] STORY-190: Fix auth\n"
        adapter, _ = _adapter(tmp_path, sprint=content)
        ids = adapter.get_active_story_ids()
        assert "STORY-190" in ids
        # Credential-like strings pass through
        text = adapter.get_sprint_text()
        assert "hunter2" in text

    def test_path_traversal_in_apply_output(self, tmp_path):
        adapter, _ = _adapter(tmp_path)
        # Various path traversal attempts
        traversals = [
            "../../../etc/passwd",
            "board/../../etc/shadow",
            "board/../../../secret",
            "/etc/hosts",
            "board/./../../etc/passwd",
        ]
        for path in traversals:
            files = [ParsedFile(path=path, content="malicious", action="write")]
            count = adapter.apply_agent_output("dev1", files, _agents_config())
            assert count == 0, f"Path traversal not blocked: {path}"

    def test_env_file_write_blocked_by_traversal(self, tmp_path):
        adapter, _ = _adapter(tmp_path)
        # Trying to write outside project dir
        files = [ParsedFile(path="../../.env", content="SECRET=bad", action="write")]
        count = adapter.apply_agent_output("dev1", files, _agents_config())
        assert count == 0


# =============================================================================
# STORY_BUG_ID_RE regex edge cases
# =============================================================================

class TestStoryBugIdRegex:
    def test_basic_story_match(self):
        assert STORY_BUG_ID_RE.findall("STORY-001") == ["STORY-001"]

    def test_basic_bug_match(self):
        assert STORY_BUG_ID_RE.findall("BUG-042") == ["BUG-042"]

    def test_case_insensitive(self):
        assert STORY_BUG_ID_RE.findall("story-001") == ["story-001"]
        assert STORY_BUG_ID_RE.findall("Story-001") == ["Story-001"]

    def test_multiple_ids_in_one_line(self):
        matches = STORY_BUG_ID_RE.findall("STORY-001 depends on BUG-002 and STORY-003")
        assert len(matches) == 3

    def test_no_match_without_number(self):
        assert STORY_BUG_ID_RE.findall("STORY-") == []

    def test_no_match_without_dash(self):
        assert STORY_BUG_ID_RE.findall("STORY001") == []

    def test_embedded_in_url(self):
        matches = STORY_BUG_ID_RE.findall("https://example.com/STORY-001/details")
        assert "STORY-001" in matches

    def test_surrounded_by_markdown(self):
        matches = STORY_BUG_ID_RE.findall("**STORY-001**: Fix login")
        assert "STORY-001" in matches

    def test_very_large_id_number(self):
        assert STORY_BUG_ID_RE.findall("STORY-999999999") == ["STORY-999999999"]

    def test_zero_id(self):
        assert STORY_BUG_ID_RE.findall("STORY-000") == ["STORY-000"]

    def test_no_match_for_other_prefixes(self):
        assert STORY_BUG_ID_RE.findall("TASK-001") == []
        assert STORY_BUG_ID_RE.findall("FEAT-001") == []
        assert STORY_BUG_ID_RE.findall("EPIC-001") == []


# =============================================================================
# Board health edge cases
# =============================================================================

class TestBoardHealthEdgeCases:
    def test_empty_sprint_file_unhealthy(self, tmp_path):
        adapter, board = _adapter(tmp_path, sprint="")
        # File exists but has 0 bytes
        health = adapter.check_board_health()
        assert health["sprint.md"] is False

    def test_whitespace_only_file_healthy(self, tmp_path):
        adapter, board = _adapter(tmp_path, sprint="  \n")
        # File has content (whitespace) so st_size > 0
        health = adapter.check_board_health()
        assert health["sprint.md"] is True

    def test_snapshot_with_no_files(self, tmp_path):
        board = tmp_path / "board"
        board.mkdir()
        adapter = MarkdownBoardAdapter(board, tmp_path, tmp_path)
        count = adapter.create_snapshot()
        assert count == 0

    def test_snapshot_creates_dir(self, tmp_path):
        adapter, board = _adapter(tmp_path, sprint="# Sprint")
        adapter.create_snapshot()
        assert (board / ".snapshot").is_dir()


# =============================================================================
# Init standup edge cases
# =============================================================================

class TestInitStandupEdgeCases:
    def test_init_with_empty_standup(self, tmp_path):
        adapter, board = _adapter(tmp_path, standup="")
        adapter.init_standup(1, 1)
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "Sprint 1" in content
        assert "Cycle 1" in content

    def test_init_standup_preserves_previous(self, tmp_path):
        adapter, board = _adapter(tmp_path, standup="# Old\nSome work done.\n")
        adapter.init_standup(1, 2)
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "<details>" in content
        assert "Some work done." in content

    def test_init_standup_strips_nested_details(self, tmp_path):
        old = "Current info\n<details><summary>Even older</summary>\nancient\n</details>\n"
        adapter, board = _adapter(tmp_path, standup=old)
        adapter.init_standup(1, 2)
        content = (board / "standup.md").read_text(encoding="utf-8")
        # Old <details> should be stripped, only one level of wrapping
        assert "ancient" not in content
        assert "Current info" in content

    def test_init_standup_huge_previous(self, tmp_path):
        old = "Important\n" + "x" * (MAX_INBOX_CHARS + 5000) + "\n"
        adapter, board = _adapter(tmp_path, standup=old)
        adapter.init_standup(1, 2)
        content = (board / "standup.md").read_text(encoding="utf-8")
        assert "_(truncated)_" in content


# =============================================================================
# Ensure board ready edge cases
# =============================================================================

class TestEnsureBoardReadyEdgeCases:
    def test_empty_agents_config(self, tmp_path):
        board = tmp_path / "board"
        adapter = MarkdownBoardAdapter(board, tmp_path, tmp_path)
        # Config with no 'agents' key falls back to defaults
        adapter.ensure_board_ready(agents_config={})
        assert (board / "inbox" / "po.md").exists()

    def test_agent_names_with_special_chars(self, tmp_path):
        board = tmp_path / "board"
        adapter = MarkdownBoardAdapter(board, tmp_path, tmp_path)
        config = {"agents": {"agent-with-dashes": {}, "agent_with_underscores": {}}}
        adapter.ensure_board_ready(agents_config=config)
        assert (board / "inbox" / "agent-with-dashes.md").exists()
        assert (board / "inbox" / "agent_with_underscores.md").exists()


# =============================================================================
# parse_sprint_statuses edge cases
# =============================================================================

class TestParseSprintStatusesEdgeCases:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "sprint.md"
        p.write_text("", encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        assert statuses == {}

    def test_only_header(self, tmp_path):
        p = tmp_path / "sprint.md"
        p.write_text("# Sprint 1\n", encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        assert statuses == {}

    def test_block_based_status_with_garbage(self, tmp_path):
        content = "# Sprint 1\n\n### STORY-200: Widget\n**Status**: XYZZY\n"
        p = tmp_path / "sprint.md"
        p.write_text(content, encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        # normalize_status("XYZZY") returns "todo"
        assert statuses.get("STORY-200") == "todo"

    def test_h3_story_without_status_field(self, tmp_path):
        content = "# Sprint 1\n\n### STORY-201: No status\nJust description.\n"
        p = tmp_path / "sprint.md"
        p.write_text(content, encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        # No **Status** field found, and not in a section, so not added
        assert "STORY-201" not in statuses

    def test_multiple_stories_block_based(self, tmp_path):
        content = (
            "# Sprint 1\n\n"
            "### STORY-202: First\n**Status**: REVIEW\n\n"
            "### STORY-203: Second\n**Status**: TESTING\n"
        )
        p = tmp_path / "sprint.md"
        p.write_text(content, encoding="utf-8")
        statuses = parse_sprint_statuses(p)
        assert statuses.get("STORY-202") == "review"
        assert statuses.get("STORY-203") == "testing"
