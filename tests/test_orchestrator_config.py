"""Tests for orchestrator/config.py — configuration loading."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from opensepia.config import OrchestratorConfig, DEFAULT_EXECUTION
from opensepia.errors import ConfigError


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
        OrchestratorConfig.load(tool_dir=Path("/nonexistent/path"))


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


# ---------------------------------------------------------------------------
# get_all_agent_ids
# ---------------------------------------------------------------------------

def test_get_all_agent_ids():
    config = OrchestratorConfig.load()
    ids = config.get_all_agent_ids()
    assert len(ids) == 9
    assert "po" in ids
    assert "sec_pentester" in ids


# ---------------------------------------------------------------------------
# get_default_mode
# ---------------------------------------------------------------------------

def test_get_default_mode():
    config = OrchestratorConfig.load()
    default = config.get_default_mode()
    assert default == "dev-team"


# ---------------------------------------------------------------------------
# get_all_mode_names
# ---------------------------------------------------------------------------

def test_get_all_mode_names_includes_modes():
    config = OrchestratorConfig.load()
    names = config.get_all_mode_names()
    assert "all" in names
    assert "dev-team" in names
    assert "minimal" in names
    assert "security" in names


def test_get_all_mode_names_includes_aliases():
    config = OrchestratorConfig.load()
    names = config.get_all_mode_names()
    assert "dev" in names
    assert "min" in names
    assert "sec" in names


def test_get_all_mode_names_includes_agent_ids():
    config = OrchestratorConfig.load()
    names = config.get_all_mode_names()
    assert "po" in names
    assert "dev1" in names
    assert "sec_pentester" in names


# ---------------------------------------------------------------------------
# get_execution_params
# ---------------------------------------------------------------------------

def test_get_execution_params_defaults():
    config = OrchestratorConfig.load()
    params = config.get_execution_params()
    assert params["timeout"] == 900
    assert params["max_retries"] == 1
    assert params["retry_delay"] == 30
    assert "pause_between_agents" in params


def test_get_execution_params_reads_from_yaml():
    config = OrchestratorConfig.load()
    params = config.get_execution_params()
    # Should match what's in agents.yaml execution section
    assert isinstance(params["timeout"], int)
    assert isinstance(params["max_retries"], int)


def test_get_execution_params_per_agent():
    config = OrchestratorConfig.load()
    # Even without overrides, should return same as global
    params_global = config.get_execution_params()
    params_agent = config.get_execution_params("po")
    assert params_agent["timeout"] == params_global["timeout"]


# ---------------------------------------------------------------------------
# get_mode_descriptions
# ---------------------------------------------------------------------------

def test_get_mode_descriptions():
    config = OrchestratorConfig.load()
    descs = config.get_mode_descriptions()
    assert "all" in descs
    assert "dev-team" in descs
    assert len(descs["all"]) > 0
