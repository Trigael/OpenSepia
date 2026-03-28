"""Tests for evolution/memory.py — agent persistent memory."""

import pytest
from pathlib import Path

from opensepia.evolution.memory import AgentMemory, MAX_MEMORY_CHARS


@pytest.fixture
def memory(tmp_path):
    board_dir = tmp_path / "board"
    board_dir.mkdir()
    return AgentMemory(board_dir)


class TestAgentMemory:
    def test_load_empty(self, memory):
        assert memory.load("dev1") == ""

    def test_append_and_load(self, memory):
        memory.append("dev1", "Learned pytest fixtures", 1, 3)
        content = memory.load("dev1")
        assert "pytest fixtures" in content
        assert "[S1C3]" in content

    def test_append_multiple(self, memory):
        memory.append("dev1", "First learning", 1, 1)
        memory.append("dev1", "Second learning", 1, 2)
        content = memory.load("dev1")
        assert "First learning" in content
        assert "Second learning" in content

    def test_append_respects_limit(self, memory):
        # Fill up memory near the limit
        big_entry = "x" * (MAX_MEMORY_CHARS - 100)
        memory.ensure_dir()
        path = memory.memory_dir / "dev1.md"
        path.write_text(big_entry, encoding="utf-8")

        # This should be rejected
        result = memory.append("dev1", "y" * 200, 1, 1)
        assert result is False

    def test_separate_agents(self, memory):
        memory.append("dev1", "Dev1 learning", 1, 1)
        memory.append("dev2", "Dev2 learning", 1, 1)
        assert "Dev1" in memory.load("dev1")
        assert "Dev2" not in memory.load("dev1")
        assert "Dev2" in memory.load("dev2")

    def test_get_context_snippet_empty(self, memory):
        assert memory.get_context_snippet("dev1") == ""

    def test_get_context_snippet_truncates(self, memory):
        for i in range(50):
            memory.append("dev1", f"Learning number {i} about testing patterns", 1, i)
        snippet = memory.get_context_snippet("dev1", max_chars=500)
        assert len(snippet) <= 600  # Allow some margin for line breaks

    def test_get_context_snippet_most_recent(self, memory):
        memory.append("dev1", "Old learning from sprint 1", 1, 1)
        memory.append("dev1", "New learning from sprint 5", 5, 1)
        snippet = memory.get_context_snippet("dev1", max_chars=200)
        # Should include recent entries
        assert "sprint 5" in snippet

    def test_list_agents_with_memory(self, memory):
        memory.append("dev1", "Something", 1, 1)
        memory.append("po", "Something else", 1, 1)
        agents = memory.list_agents_with_memory()
        assert "dev1" in agents
        assert "po" in agents
        assert "dev2" not in agents

    def test_ensure_dir_creates_directory(self, memory):
        memory.ensure_dir()
        assert memory.memory_dir.exists()

    def test_timestamp_added_if_missing(self, memory):
        memory.append("dev1", "Learning without timestamp", 2, 5)
        content = memory.load("dev1")
        assert "[S2C5]" in content
