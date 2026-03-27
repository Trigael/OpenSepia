"""Comprehensive unit tests for opensepia/config.py validation and loading logic."""

import os
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch

from opensepia.config import (
    OrchestratorConfig,
    _validate_agents_schema,
    _validate_project_schema,
    DEFAULT_EXECUTION,
)
from opensepia.errors import ConfigError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_agents():
    """Return a minimal valid agents dict."""
    return {
        "agents": {
            "dev": {"name": "Developer", "system_prompt": "Write code."},
        },
        "modes": {
            "dev-team": {"agents": ["dev"], "default": True},
        },
    }


def _minimal_project():
    """Return a minimal valid project dict."""
    return {
        "project": {"name": "TestProject", "description": "A test"},
        "sprint": {"current_sprint": 1, "current_cycle": 0, "cycles_per_sprint": 10},
    }


def _write_yaml(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)


def _setup_valid_dirs(tmp_path):
    """Create minimal valid tool_dir and project_dir under tmp_path."""
    tool_dir = tmp_path / "tool"
    project_dir = tmp_path / "project"
    config_dir = tool_dir / "config"
    config_dir.mkdir(parents=True)
    project_dir.mkdir(parents=True)
    _write_yaml(config_dir / "agents.yaml", _minimal_agents())
    _write_yaml(project_dir / "project.yaml", _minimal_project())
    return tool_dir, project_dir


# ===========================================================================
# 1. _validate_agents_schema
# ===========================================================================

class TestValidateAgentsSchema:
    def test_not_a_dict(self):
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            _validate_agents_schema("not a dict")

    def test_agents_section_not_a_dict(self):
        with pytest.raises(ConfigError, match="'agents' must be a mapping"):
            _validate_agents_schema({"agents": "bad"})

    def test_agent_definition_not_a_dict(self):
        with pytest.raises(ConfigError, match="agent 'dev' must be a mapping"):
            _validate_agents_schema({"agents": {"dev": "bad"}})

    def test_agent_missing_name(self):
        with pytest.raises(ConfigError, match="missing required 'name'"):
            _validate_agents_schema({"agents": {"dev": {"system_prompt": "x"}}})

    def test_agent_missing_system_prompt(self):
        with pytest.raises(ConfigError, match="missing required 'system_prompt'"):
            _validate_agents_schema({"agents": {"dev": {"name": "Dev"}}})

    def test_modes_not_a_dict(self):
        agents = _minimal_agents()
        agents["modes"] = "bad"
        with pytest.raises(ConfigError, match="'modes' must be a mapping"):
            _validate_agents_schema(agents)

    def test_mode_not_a_dict(self):
        agents = _minimal_agents()
        agents["modes"]["dev-team"] = "bad"
        with pytest.raises(ConfigError, match="mode 'dev-team' must be a mapping"):
            _validate_agents_schema(agents)

    def test_mode_missing_agents(self):
        agents = _minimal_agents()
        agents["modes"]["dev-team"] = {"description": "no agents key"}
        with pytest.raises(ConfigError, match="mode 'dev-team' missing 'agents'"):
            _validate_agents_schema(agents)

    def test_mode_agents_not_a_list(self):
        agents = _minimal_agents()
        agents["modes"]["dev-team"] = {"agents": "not-a-list"}
        with pytest.raises(ConfigError, match="'agents' must be a list"):
            _validate_agents_schema(agents)

    def test_execution_not_a_dict(self):
        agents = _minimal_agents()
        agents["execution"] = "bad"
        with pytest.raises(ConfigError, match="'execution' must be a mapping"):
            _validate_agents_schema(agents)

    def test_execution_field_not_a_number(self):
        agents = _minimal_agents()
        agents["execution"] = {"timeout": "slow"}
        with pytest.raises(ConfigError, match="execution.timeout must be a number"):
            _validate_agents_schema(agents)

    def test_execution_retry_delay_not_a_number(self):
        agents = _minimal_agents()
        agents["execution"] = {"retry_delay": "fast"}
        with pytest.raises(ConfigError, match="execution.retry_delay must be a number"):
            _validate_agents_schema(agents)

    def test_pipeline_not_a_list(self):
        agents = _minimal_agents()
        agents["pipeline"] = "bad"
        with pytest.raises(ConfigError, match="'pipeline' must be a list"):
            _validate_agents_schema(agents)

    def test_valid_passes(self):
        agents = _minimal_agents()
        agents["execution"] = {"timeout": 120, "max_retries": 2, "retry_delay": 10}
        agents["pipeline"] = ["step1", "step2"]
        _validate_agents_schema(agents)  # should not raise

    def test_modes_none_is_fine(self):
        agents = _minimal_agents()
        del agents["modes"]
        _validate_agents_schema(agents)  # no modes section is OK

    def test_execution_none_is_fine(self):
        _validate_agents_schema(_minimal_agents())  # no execution section is OK


# ===========================================================================
# 2. _validate_project_schema
# ===========================================================================

class TestValidateProjectSchema:
    def test_not_a_dict(self):
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            _validate_project_schema("string")

    def test_sprint_not_a_dict(self):
        with pytest.raises(ConfigError, match="'sprint' must be a mapping"):
            _validate_project_schema({"sprint": "bad"})

    def test_sprint_field_not_int(self):
        with pytest.raises(ConfigError, match="sprint.current_sprint must be an integer"):
            _validate_project_schema({"sprint": {"current_sprint": "one"}})

    def test_sprint_cycle_not_int(self):
        with pytest.raises(ConfigError, match="sprint.current_cycle must be an integer"):
            _validate_project_schema({"sprint": {"current_cycle": 1.5}})

    def test_limits_not_a_dict(self):
        with pytest.raises(ConfigError, match="'limits' must be a mapping"):
            _validate_project_schema({"limits": [1, 2]})

    def test_valid_passes(self):
        _validate_project_schema(_minimal_project())  # should not raise

    def test_minimal_valid(self):
        _validate_project_schema({})  # empty dict is valid (all optional)


# ===========================================================================
# 3. OrchestratorConfig.load
# ===========================================================================

class TestOrchestratorConfigLoad:
    def test_missing_agents_yaml(self, tmp_path):
        tool_dir = tmp_path / "tool"
        (tool_dir / "config").mkdir(parents=True)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_yaml(project_dir / "project.yaml", _minimal_project())

        with pytest.raises(ConfigError, match="Missing agents config"):
            OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)

    def test_invalid_agents_yaml(self, tmp_path):
        tool_dir = tmp_path / "tool"
        config_dir = tool_dir / "config"
        config_dir.mkdir(parents=True)
        # Write invalid YAML
        (config_dir / "agents.yaml").write_text(":\n  :\n    - [bad")
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_yaml(project_dir / "project.yaml", _minimal_project())

        with pytest.raises(ConfigError, match="Invalid agents.yaml"):
            OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)

    def test_missing_agents_key(self, tmp_path):
        tool_dir = tmp_path / "tool"
        config_dir = tool_dir / "config"
        config_dir.mkdir(parents=True)
        _write_yaml(config_dir / "agents.yaml", {"modes": {}})
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_yaml(project_dir / "project.yaml", _minimal_project())

        with pytest.raises(ConfigError, match="must contain an 'agents' key"):
            OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)

    def test_empty_agents_yaml(self, tmp_path):
        """An empty YAML file loads as None, which should trigger the 'agents' key error."""
        tool_dir = tmp_path / "tool"
        config_dir = tool_dir / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "agents.yaml").write_text("")
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_yaml(project_dir / "project.yaml", _minimal_project())

        with pytest.raises(ConfigError, match="must contain an 'agents' key"):
            OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)

    def test_missing_project_yaml(self, tmp_path):
        tool_dir = tmp_path / "tool"
        config_dir = tool_dir / "config"
        config_dir.mkdir(parents=True)
        _write_yaml(config_dir / "agents.yaml", _minimal_agents())
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        # No project.yaml

        with pytest.raises(ConfigError, match="Missing project config"):
            OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)

    def test_invalid_project_yaml(self, tmp_path):
        tool_dir = tmp_path / "tool"
        config_dir = tool_dir / "config"
        config_dir.mkdir(parents=True)
        _write_yaml(config_dir / "agents.yaml", _minimal_agents())
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text(":\n  :\n    - [bad")

        with pytest.raises(ConfigError, match="Invalid project.yaml"):
            OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)

    def test_env_loading(self, tmp_path):
        tool_dir, project_dir = _setup_valid_dirs(tmp_path)
        env_file = tool_dir / "config" / ".env"
        env_file.write_text("TEST_CONFIG_VAR_XYZ=hello123\n# comment\nANOTHER_VAR=world\n\n")

        # Clean up after test
        try:
            OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)
            assert os.environ.get("TEST_CONFIG_VAR_XYZ") == "hello123"
            assert os.environ.get("ANOTHER_VAR") == "world"
        finally:
            os.environ.pop("TEST_CONFIG_VAR_XYZ", None)
            os.environ.pop("ANOTHER_VAR", None)

    def test_valid_load(self, tmp_path):
        tool_dir, project_dir = _setup_valid_dirs(tmp_path)
        cfg = OrchestratorConfig.load(tool_dir=tool_dir, project_dir=project_dir)

        assert cfg.tool_dir == tool_dir
        assert cfg.project_dir == project_dir
        assert "dev" in cfg.agents["agents"]
        assert cfg.project["project"]["name"] == "TestProject"


# ===========================================================================
# 4. OrchestratorConfig.validate()
# ===========================================================================

class TestOrchestratorConfigValidate:
    def _make_config(self, agents=None, project=None, tmp_path=None):
        p = tmp_path or Path("/tmp")
        return OrchestratorConfig(
            tool_dir=p,
            project_dir=p,
            agents=agents if agents is not None else _minimal_agents(),
            project=project if project is not None else _minimal_project(),
        )

    def test_mode_references_unknown_agent(self, tmp_path):
        agents = _minimal_agents()
        agents["modes"]["dev-team"]["agents"] = ["nonexistent"]
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("unknown agent 'nonexistent'" in w for w in warnings)

    def test_agent_missing_name_warning(self, tmp_path):
        agents = _minimal_agents()
        agents["agents"]["dev"]["name"] = ""
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("missing 'name'" in w for w in warnings)

    def test_agent_missing_system_prompt_warning(self, tmp_path):
        agents = _minimal_agents()
        agents["agents"]["dev"]["system_prompt"] = ""
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("missing 'system_prompt'" in w for w in warnings)

    def test_timeout_too_low(self, tmp_path):
        agents = _minimal_agents()
        agents["execution"] = {"timeout": 10}
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("very low" in w for w in warnings)

    def test_timeout_too_high(self, tmp_path):
        agents = _minimal_agents()
        agents["execution"] = {"timeout": 5000}
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("very high" in w for w in warnings)

    def test_project_name_not_set(self, tmp_path):
        project = _minimal_project()
        project["project"]["name"] = "My Project"
        cfg = self._make_config(project=project, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("Project name not set" in w for w in warnings)

    def test_project_name_empty(self, tmp_path):
        project = _minimal_project()
        project["project"]["name"] = ""
        cfg = self._make_config(project=project, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("Project name not set" in w for w in warnings)

    def test_cycles_per_sprint_less_than_one(self, tmp_path):
        project = _minimal_project()
        project["sprint"]["cycles_per_sprint"] = 0
        cfg = self._make_config(project=project, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("cycles_per_sprint must be at least 1" in w for w in warnings)

    def test_no_warnings_for_valid_config(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        warnings = cfg.validate()
        assert warnings == []

    def test_no_project_section(self, tmp_path):
        """If project dict has no 'project' key, name check triggers warning."""
        cfg = self._make_config(project={"sprint": {"current_sprint": 1, "cycles_per_sprint": 10}}, tmp_path=tmp_path)
        warnings = cfg.validate()
        assert any("Project name not set" in w for w in warnings)


# ===========================================================================
# 5. OrchestratorConfig properties and methods
# ===========================================================================

class TestOrchestratorConfigProperties:
    def _make_config(self, agents=None, project=None, tmp_path=None):
        p = tmp_path or Path("/tmp")
        return OrchestratorConfig(
            tool_dir=p,
            project_dir=p,
            agents=agents if agents is not None else _minimal_agents(),
            project=project if project is not None else _minimal_project(),
        )

    def test_config_dir(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        assert cfg.config_dir == tmp_path / "config"

    def test_logs_dir(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        assert cfg.logs_dir == tmp_path / "logs" / "runs"

    def test_sprint_cfg(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        assert cfg.sprint_cfg["current_sprint"] == 1

    def test_sprint_cfg_default(self, tmp_path):
        cfg = self._make_config(project={}, tmp_path=tmp_path)
        assert cfg.sprint_cfg == {}

    def test_sprint_num(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        assert cfg.sprint_num == 1

    def test_sprint_num_default(self, tmp_path):
        cfg = self._make_config(project={}, tmp_path=tmp_path)
        assert cfg.sprint_num == 1

    def test_cycle_num(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        assert cfg.cycle_num == 0

    def test_cycle_num_default(self, tmp_path):
        cfg = self._make_config(project={}, tmp_path=tmp_path)
        assert cfg.cycle_num == 0

    def test_save_project(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        cfg.project["sprint"]["current_cycle"] = 5
        cfg.save_project()

        reloaded = yaml.safe_load((tmp_path / "project.yaml").read_text())
        assert reloaded["sprint"]["current_cycle"] == 5

    def test_get_default_mode_with_default(self, tmp_path):
        agents = _minimal_agents()
        agents["modes"]["dev-team"]["default"] = True
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        assert cfg.get_default_mode() == "dev-team"

    def test_get_default_mode_fallback(self, tmp_path):
        agents = _minimal_agents()
        # Remove default flag
        agents["modes"]["dev-team"].pop("default", None)
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        assert cfg.get_default_mode() == "dev-team"  # falls back to "dev-team"

    def test_get_default_mode_no_modes(self, tmp_path):
        agents = _minimal_agents()
        agents["modes"] = {}
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        assert cfg.get_default_mode() == "dev-team"

    def test_get_all_mode_names(self, tmp_path):
        agents = _minimal_agents()
        agents["modes"]["dev-team"]["aliases"] = ["dt", "team"]
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        names = cfg.get_all_mode_names()
        assert "dev-team" in names
        assert "dt" in names
        assert "team" in names
        assert "dev" in names  # agent id included

    def test_resolve_agent_ids_mode(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        ids = cfg.resolve_agent_ids("dev-team")
        assert ids == ["dev"]

    def test_resolve_agent_ids_alias(self, tmp_path):
        agents = _minimal_agents()
        agents["modes"]["dev-team"]["aliases"] = ["dt"]
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        ids = cfg.resolve_agent_ids("dt")
        assert ids == ["dev"]

    def test_resolve_agent_ids_single_agent(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        ids = cfg.resolve_agent_ids("dev")
        assert ids == ["dev"]

    def test_resolve_agent_ids_unknown(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        with pytest.raises(ConfigError, match="Unknown mode 'nope'"):
            cfg.resolve_agent_ids("nope")

    def test_resolve_agent_ids_invalid_agent_in_mode(self, tmp_path):
        agents = _minimal_agents()
        agents["modes"]["bad-mode"] = {"agents": ["ghost"]}
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        with pytest.raises(ConfigError, match="Agent 'ghost'.*not found"):
            cfg.resolve_agent_ids("bad-mode")

    def test_get_execution_params_defaults(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        params = cfg.get_execution_params()
        assert params["timeout"] == DEFAULT_EXECUTION["timeout"]
        assert params["max_retries"] == DEFAULT_EXECUTION["max_retries"]

    def test_get_execution_params_custom(self, tmp_path):
        agents = _minimal_agents()
        agents["execution"] = {"timeout": 600, "max_retries": 3}
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        params = cfg.get_execution_params()
        assert params["timeout"] == 600
        assert params["max_retries"] == 3

    def test_get_execution_params_with_overrides(self, tmp_path):
        agents = _minimal_agents()
        agents["execution"] = {
            "timeout": 600,
            "overrides": {"dev": {"timeout": 300}},
        }
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        params = cfg.get_execution_params(agent_id="dev")
        assert params["timeout"] == 300

    def test_get_execution_params_override_not_dict(self, tmp_path):
        agents = _minimal_agents()
        agents["execution"] = {
            "timeout": 600,
            "overrides": {"dev": "bad"},
        }
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        params = cfg.get_execution_params(agent_id="dev")
        # override is not a dict, so it should be ignored
        assert params["timeout"] == 600

    def test_get_execution_params_overrides_not_dict(self, tmp_path):
        agents = _minimal_agents()
        agents["execution"] = {
            "timeout": 600,
            "overrides": "bad",
        }
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        params = cfg.get_execution_params(agent_id="dev")
        assert params["timeout"] == 600

    def test_resolve_agent_execution_params_static(self):
        agents_config = {
            "execution": {"timeout": 500, "max_retries": 2},
        }
        params = OrchestratorConfig.resolve_agent_execution_params(agents_config)
        assert params["timeout"] == 500
        assert params["max_retries"] == 2

    def test_resolve_agent_execution_params_with_agent_override(self):
        agents_config = {
            "execution": {
                "timeout": 500,
                "overrides": {"dev": {"timeout": 200}},
            },
        }
        params = OrchestratorConfig.resolve_agent_execution_params(agents_config, agent_id="dev")
        assert params["timeout"] == 200

    def test_resolve_agent_execution_params_override_not_dict(self):
        agents_config = {
            "execution": {
                "timeout": 500,
                "overrides": {"dev": "bad"},
            },
        }
        params = OrchestratorConfig.resolve_agent_execution_params(agents_config, agent_id="dev")
        assert params["timeout"] == 500

    def test_resolve_agent_execution_params_overrides_not_dict(self):
        agents_config = {
            "execution": {
                "timeout": 500,
                "overrides": "bad",
            },
        }
        params = OrchestratorConfig.resolve_agent_execution_params(agents_config, agent_id="dev")
        assert params["timeout"] == 500

    def test_resolve_agent_execution_params_no_execution(self):
        params = OrchestratorConfig.resolve_agent_execution_params({})
        assert params == DEFAULT_EXECUTION

    def test_get_mode_descriptions(self, tmp_path):
        agents = _minimal_agents()
        agents["modes"]["dev-team"]["description"] = "Full dev team"
        agents["modes"]["solo"] = {"agents": ["dev"], "description": "Solo mode"}
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        descs = cfg.get_mode_descriptions()
        assert descs["dev-team"] == "Full dev team"
        assert descs["solo"] == "Solo mode"

    def test_get_mode_descriptions_missing(self, tmp_path):
        cfg = self._make_config(tmp_path=tmp_path)
        descs = cfg.get_mode_descriptions()
        assert descs["dev-team"] == ""

    def test_get_all_agent_ids(self, tmp_path):
        agents = _minimal_agents()
        agents["agents"]["tester"] = {"name": "Tester", "system_prompt": "Test."}
        cfg = self._make_config(agents=agents, tmp_path=tmp_path)
        ids = cfg.get_all_agent_ids()
        assert "dev" in ids
        assert "tester" in ids
