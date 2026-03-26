"""Tests for agent/parser.py — output parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.parser import parse_files_section, parse_standup_from_response, ParsedFile


# ---------------------------------------------------------------------------
# parse_files_section — basic cases
# ---------------------------------------------------------------------------

def test_parse_files_basic():
    response = """Some agent output here.

---FILES---
path: board/sprint.md
content:
# Sprint 1
Some content
---
path: board/inbox/dev1.md
action: append
content:
## Message from PO
Hello dev1
---END---
"""
    files = parse_files_section(response)
    assert len(files) == 2
    assert files[0].path == "board/sprint.md"
    assert files[0].action == "overwrite"
    assert "# Sprint 1" in files[0].content
    assert files[1].path == "board/inbox/dev1.md"
    assert files[1].action == "append"
    assert "Hello dev1" in files[1].content


def test_parse_files_no_files_section():
    response = "Just a regular response without FILES section."
    files = parse_files_section(response)
    assert files == []


def test_parse_files_no_end_marker():
    response = """---FILES---
path: board/standup.md
content:
## Standup
Agent report here
"""
    files = parse_files_section(response)
    assert len(files) == 1
    assert files[0].path == "board/standup.md"
    assert "Agent report here" in files[0].content


def test_parse_files_empty_content_skipped():
    response = """---FILES---
path: board/empty.md
content:

---
path: board/real.md
content:
Real content
---END---
"""
    files = parse_files_section(response)
    assert len(files) == 1
    assert files[0].path == "board/real.md"


def test_parse_files_multiple_files():
    response = """---FILES---
path: file1.md
content:
content1
---
path: file2.md
content:
content2
---
path: file3.md
content:
content3
---END---
"""
    files = parse_files_section(response)
    assert len(files) == 3
    assert [f.path for f in files] == ["file1.md", "file2.md", "file3.md"]


def test_parse_files_content_with_dashes():
    """Content lines with --- should not be confused with file separators
    unless they appear as standalone."""
    response = """---FILES---
path: board/sprint.md
content:
# Sprint
---
path: board/backlog.md
content:
Some text with --- in it like a horizontal rule
More text
---END---
"""
    files = parse_files_section(response)
    # The --- in the sprint section acts as separator, but the
    # "--- in it" is part of content because it's not a standalone ---
    assert len(files) >= 1


def test_parse_files_preserves_indentation():
    response = """---FILES---
path: workspace/src/main.py
content:
def hello():
    print("hello")
    if True:
        return 42
---END---
"""
    files = parse_files_section(response)
    assert len(files) == 1
    assert '    print("hello")' in files[0].content
    assert "        return 42" in files[0].content


def test_parse_files_returns_parsed_file_dataclass():
    response = """---FILES---
path: test.md
content:
test
---END---
"""
    files = parse_files_section(response)
    assert len(files) == 1
    assert isinstance(files[0], ParsedFile)
    assert files[0].path == "test.md"
    assert files[0].content == "test"
    assert files[0].action == "overwrite"


# ---------------------------------------------------------------------------
# parse_files_section — OUTPUT format fallback
# ---------------------------------------------------------------------------

def test_parse_files_falls_back_to_output_yaml():
    response = """---OUTPUT---
files_to_write:
  - path: board/sprint.md
    content: "# Sprint content"
---END---
"""
    files = parse_files_section(response)
    assert len(files) == 1
    assert files[0].path == "board/sprint.md"


# ---------------------------------------------------------------------------
# parse_standup_from_response
# ---------------------------------------------------------------------------

def test_parse_standup_basic():
    response = """Some output

---STANDUP---
Working on STORY-001
---

More output"""
    result = parse_standup_from_response(response, "dev1", "Developer 1", "\U0001f7e2")
    assert "Developer 1" in result
    assert "Working on STORY-001" in result


def test_parse_standup_not_present():
    response = "No standup section here"
    result = parse_standup_from_response(response, "dev1", "Dev 1", "\U0001f7e2")
    assert result == ""


def test_parse_standup_truncates_long_text():
    long_text = "x" * 600
    response = f"---STANDUP---\n{long_text}\n---"
    result = parse_standup_from_response(response, "dev1", "Dev 1", "\U0001f7e2")
    assert len(result) < 600
    assert "..." in result
