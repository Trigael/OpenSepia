"""Tests for opensepia/cycle_state.py — cycle checkpointing."""

import json
import pytest
from pathlib import Path

from opensepia.cycle_state import CycleState


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "cycle_state.json"


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

def test_default_state():
    s = CycleState()
    assert s.status == "pending"
    assert s.completed_steps == []
    assert s.completed_agents == []
    assert s.cycle_id == ""


def test_state_with_values():
    s = CycleState(cycle_id="s1c3", sprint=1, cycle=3, mode="dev-team", status="in_progress")
    assert s.cycle_id == "s1c3"
    assert s.status == "in_progress"


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------

def test_save_and_load(state_path):
    s = CycleState(
        cycle_id="s2c5", sprint=2, cycle=5, mode="minimal",
        status="in_progress",
        completed_steps=["board_health", "sprint_check"],
        completed_agents=["po"],
        agent_ids=["po", "dev1", "tester"],
    )
    s.save(state_path)

    loaded = CycleState.load(state_path)
    assert loaded.cycle_id == "s2c5"
    assert loaded.status == "in_progress"
    assert loaded.completed_steps == ["board_health", "sprint_check"]
    assert loaded.completed_agents == ["po"]
    assert loaded.agent_ids == ["po", "dev1", "tester"]


def test_load_missing_file(state_path):
    loaded = CycleState.load(state_path)
    assert loaded.status == "pending"


def test_load_corrupt_file(state_path):
    state_path.write_text("{broken json", encoding="utf-8")
    loaded = CycleState.load(state_path)
    assert loaded.status == "pending"


def test_save_atomic(state_path):
    s = CycleState(cycle_id="test")
    s.save(state_path)
    assert not state_path.with_suffix(".tmp").exists()


# ---------------------------------------------------------------------------
# Step tracking
# ---------------------------------------------------------------------------

def test_mark_step_complete(state_path):
    s = CycleState(cycle_id="s1c1", status="in_progress")
    s.save(state_path)

    s.mark_step_complete("board_health", state_path)
    assert "board_health" in s.completed_steps
    assert s.current_step is None
    assert s.updated_at is not None

    # Reload and verify persistence
    loaded = CycleState.load(state_path)
    assert "board_health" in loaded.completed_steps


def test_mark_step_no_duplicates(state_path):
    s = CycleState(cycle_id="s1c1", status="in_progress")
    s.mark_step_complete("board_health", state_path)
    s.mark_step_complete("board_health", state_path)
    assert s.completed_steps.count("board_health") == 1


# ---------------------------------------------------------------------------
# Agent tracking
# ---------------------------------------------------------------------------

def test_mark_agent_complete(state_path):
    s = CycleState(
        cycle_id="s1c1", status="in_progress",
        agent_ids=["po", "dev1", "tester"],
    )
    s.mark_agent_complete("po", state_path)
    assert "po" in s.completed_agents

    loaded = CycleState.load(state_path)
    assert "po" in loaded.completed_agents


def test_mark_agent_no_duplicates(state_path):
    s = CycleState(cycle_id="s1c1", status="in_progress")
    s.mark_agent_complete("po", state_path)
    s.mark_agent_complete("po", state_path)
    assert s.completed_agents.count("po") == 1


# ---------------------------------------------------------------------------
# Completion / failure
# ---------------------------------------------------------------------------

def test_mark_completed(state_path):
    s = CycleState(cycle_id="s1c1", status="in_progress", current_step="alerting")
    s.mark_completed(state_path)
    assert s.status == "completed"
    assert s.current_step is None


def test_mark_failed(state_path):
    s = CycleState(cycle_id="s1c1", status="in_progress")
    s.mark_failed(state_path)
    assert s.status == "failed"


# ---------------------------------------------------------------------------
# is_interrupted
# ---------------------------------------------------------------------------

def test_is_interrupted_true():
    s = CycleState(status="in_progress")
    assert s.is_interrupted is True


def test_is_interrupted_false_pending():
    s = CycleState(status="pending")
    assert s.is_interrupted is False


def test_is_interrupted_false_completed():
    s = CycleState(status="completed")
    assert s.is_interrupted is False


# ---------------------------------------------------------------------------
# Remaining steps / agents
# ---------------------------------------------------------------------------

def test_remaining_steps():
    s = CycleState(completed_steps=["board_health", "sprint_check"])
    remaining = s.remaining_steps(["board_health", "sprint_check", "snapshot", "agent_runner"])
    assert remaining == ["snapshot", "agent_runner"]


def test_remaining_agents():
    s = CycleState(agent_ids=["po", "pm", "dev1"], completed_agents=["po"])
    assert s.remaining_agents() == ["pm", "dev1"]


def test_remaining_agents_empty_when_all_done():
    s = CycleState(agent_ids=["po", "dev1"], completed_agents=["po", "dev1"])
    assert s.remaining_agents() == []
