"""Tests for orchestrator/config.py — configuration loading."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from orchestrator.config import OrchestratorConfig
from orchestrator.errors import ConfigError


# ---------------------------------------------------------------------------
# OrchestratorConfig.load
# ---------------------------------------------------------------------------

def test_config_loads_from_project_dir():
    """Config should load successfully from the actual project directory."""
    config = OrchestratorConfig.load()
    assert config.project_dir.exists()
    assert config.board_dir.exists()
    assert "agents" in config.agents
    assert "project" in config.project


def test_config_sprint_properties():
    config = OrchestratorConfig.load()
    assert isinstance(config.sprint_num, int)
    assert isinstance(config.cycle_num, int)
    assert config.sprint_num >= 1


def test_config_raises_on_missing_dir():
    with pytest.raises(ConfigError, match="Missing agents config"):
        OrchestratorConfig.load(project_dir=Path("/nonexistent/path"))


# ---------------------------------------------------------------------------
# resolve_agent_ids
# ---------------------------------------------------------------------------

def test_resolve_all():
    config = OrchestratorConfig.load()
    ids = config.resolve_agent_ids("all")
    assert len(ids) == 9
    assert "po" in ids
    assert "sec_pentester" in ids


def test_resolve_dev_team():
    config = OrchestratorConfig.load()
    ids = config.resolve_agent_ids("dev-team")
    assert len(ids) == 6
    assert "po" in ids
    assert "tester" in ids
    assert "sec_analyst" not in ids


def test_resolve_minimal():
    config = OrchestratorConfig.load()
    ids = config.resolve_agent_ids("minimal")
    assert len(ids) == 3
    assert set(ids) == {"po", "dev1", "tester"}


def test_resolve_security():
    config = OrchestratorConfig.load()
    ids = config.resolve_agent_ids("security")
    assert len(ids) == 3
    assert "sec_analyst" in ids


def test_resolve_single_agent():
    config = OrchestratorConfig.load()
    ids = config.resolve_agent_ids("po")
    assert ids == ["po"]


def test_resolve_mode_aliases():
    config = OrchestratorConfig.load()
    assert config.resolve_agent_ids("dev") == config.resolve_agent_ids("dev-team")
    assert config.resolve_agent_ids("min") == config.resolve_agent_ids("minimal")
    assert config.resolve_agent_ids("sec") == config.resolve_agent_ids("security")


def test_resolve_unknown_mode_raises():
    config = OrchestratorConfig.load()
    with pytest.raises(ConfigError, match="Unknown mode"):
        config.resolve_agent_ids("nonexistent-mode")
