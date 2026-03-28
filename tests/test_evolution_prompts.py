"""Tests for evolution/prompts.py — prompt self-refinement."""

import pytest
from pathlib import Path

from opensepia.evolution.prompts import PromptManager


@pytest.fixture
def pm(tmp_path):
    board_dir = tmp_path / "board"
    (board_dir / "evolution" / "prompts").mkdir(parents=True)
    return PromptManager(board_dir)


class TestPromptManager:
    def test_get_active_prompt_none(self, pm):
        assert pm.get_active_prompt("dev1") is None

    def test_initialize_from_config(self, pm):
        pm.initialize_from_config("dev1", "You are Developer 1.\n\nWrite code.")
        history = pm.get_version_history("dev1")
        assert len(history) == 1
        assert history[0].version == 1
        assert "Developer 1" in history[0].system_prompt

    def test_initialize_idempotent(self, pm):
        pm.initialize_from_config("dev1", "Prompt v1")
        pm.initialize_from_config("dev1", "Prompt v1 again")
        history = pm.get_version_history("dev1")
        assert len(history) == 1  # Only one v001

    def test_apply_refinement(self, pm):
        pm.initialize_from_config("dev1", "Original prompt")
        version = pm.apply_refinement(
            "dev1", "Refined prompt with better instructions",
            proposed_by="dev1", reason="Improve code quality guidance",
        )
        assert version.version == 2
        assert version.parent_version == 1

        # Active prompt should be the refined one
        active = pm.get_active_prompt("dev1")
        assert active == "Refined prompt with better instructions"

    def test_version_history(self, pm):
        pm.initialize_from_config("dev1", "v1")
        pm.apply_refinement("dev1", "v2 prompt", "dev1", "first refine")
        pm.apply_refinement("dev1", "v3 prompt", "dev1", "second refine")

        history = pm.get_version_history("dev1")
        assert len(history) == 3
        assert [h.version for h in history] == [1, 2, 3]

    def test_rollback(self, pm):
        pm.initialize_from_config("dev1", "Original")
        pm.apply_refinement("dev1", "Bad change", "dev1", "oops")
        pm.rollback("dev1", 1)

        active = pm.get_active_prompt("dev1")
        assert active == "Original"

        # History should have 3 entries (original, bad, rollback)
        history = pm.get_version_history("dev1")
        assert len(history) == 3

    def test_rollback_nonexistent_version(self, pm):
        result = pm.rollback("dev1", 99)
        assert result is None

    def test_get_current_version(self, pm):
        assert pm.get_current_version("dev1") == 0
        pm.initialize_from_config("dev1", "v1")
        pm.apply_refinement("dev1", "v2", "dev1", "test")
        assert pm.get_current_version("dev1") == 2

    def test_separate_agents(self, pm):
        pm.initialize_from_config("dev1", "Dev1 prompt")
        pm.initialize_from_config("dev2", "Dev2 prompt")
        pm.apply_refinement("dev1", "Dev1 refined", "dev1", "test")

        assert pm.get_active_prompt("dev1") == "Dev1 refined"
        assert pm.get_active_prompt("dev2") is None  # No refinement applied
