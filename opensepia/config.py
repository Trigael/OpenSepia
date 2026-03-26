"""
AI Dev Team — Centralized configuration loading.

Loads agents.yaml (tool config) and project.yaml (product config).
Separates the OpenSepia tool root from the product project directory.
"""

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensepia.errors import ConfigError

# Default execution parameters (used when YAML doesn't specify)
DEFAULT_EXECUTION = {
    "timeout": 900,
    "max_retries": 1,
    "retry_delay": 30,
    "pause_between_agents": 0,
}


@dataclass
class OrchestratorConfig:
    """Centralized configuration loaded once at startup.

    Two directory roots:
    - tool_dir: OpenSepia tool root (where opensepia/ package lives)
    - project_dir: Product being worked on (board/, workspace/, project.yaml)
    """
    tool_dir: Path        # OpenSepia root (contains opensepia/, config/, tests/)
    project_dir: Path     # Product root (contains board/, workspace/, project.yaml)
    agents: dict[str, Any]
    project: dict[str, Any]

    @property
    def config_dir(self) -> Path:
        """Tool config directory (agents.yaml, .env)."""
        return self.tool_dir / "config"

    @property
    def board_dir(self) -> Path:
        return self.project_dir / "board"

    @property
    def workspace_dir(self) -> Path:
        return self.project_dir / "workspace"

    @property
    def logs_dir(self) -> Path:
        return self.project_dir / "logs" / "runs"

    @classmethod
    def load(cls, tool_dir: Path | None = None, project_dir: Path | None = None) -> "OrchestratorConfig":
        """Load all configuration files.

        Args:
            tool_dir: OpenSepia tool root. Defaults to two levels up from this file.
            project_dir: Product project root. Defaults to tool_dir/project/.

        Returns:
            Populated OrchestratorConfig instance.

        Raises:
            ConfigError: If required config files are missing or invalid.
        """
        if tool_dir is None:
            tool_dir = Path(__file__).parent.parent

        if project_dir is None:
            project_dir = tool_dir / "project"

        config_dir = tool_dir / "config"

        # Load .env
        env_file = config_dir / ".env"
        if env_file.exists():
            import os
            for line in env_file.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

        # Load agents.yaml (tool config)
        agents_file = config_dir / "agents.yaml"
        if not agents_file.exists():
            raise ConfigError(f"Missing agents config: {agents_file}")
        try:
            with open(agents_file, "r", encoding="utf-8") as f:
                agents = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid agents.yaml: {e}") from e

        if not agents or "agents" not in agents:
            raise ConfigError("agents.yaml must contain an 'agents' key")

        # Load project.yaml (product config — inside project_dir)
        project_file = project_dir / "project.yaml"
        if not project_file.exists():
            raise ConfigError(f"Missing project config: {project_file}")
        try:
            with open(project_file, "r", encoding="utf-8") as f:
                project = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid project.yaml: {e}") from e

        return cls(
            tool_dir=tool_dir,
            project_dir=project_dir,
            agents=agents,
            project=project,
        )

    @property
    def sprint_cfg(self) -> dict[str, Any]:
        return self.project.get("sprint", {})

    @property
    def sprint_num(self) -> int:
        return self.sprint_cfg.get("current_sprint", 1)

    @property
    def cycle_num(self) -> int:
        return self.sprint_cfg.get("current_cycle", 0)

    def save_project(self) -> None:
        """Write project.yaml back to disk."""
        with open(self.project_dir / "project.yaml", "w", encoding="utf-8") as f:
            yaml.dump(self.project, f, default_flow_style=False, allow_unicode=True)

    # ----- Validation -----

    def validate(self) -> list[str]:
        """Validate configuration. Returns list of warnings (empty = all good)."""
        warnings = []
        known_agents = set(self.agents.get("agents", {}).keys())

        # Check modes reference valid agents
        modes = self.agents.get("modes", {})
        for mode_name, mode_def in modes.items():
            agents_in_mode = mode_def.get("agents", [])
            for aid in agents_in_mode:
                if aid not in known_agents:
                    warnings.append(
                        f"Mode '{mode_name}' references unknown agent '{aid}'"
                    )

        # Check agents have required fields
        for aid, agent_def in self.agents.get("agents", {}).items():
            if not agent_def.get("name"):
                warnings.append(f"Agent '{aid}' missing 'name' field")
            if not agent_def.get("system_prompt"):
                warnings.append(f"Agent '{aid}' missing 'system_prompt' field")

        # Check execution params are reasonable
        exec_cfg = self.agents.get("execution", {})
        timeout = exec_cfg.get("timeout", 900)
        if timeout < 30:
            warnings.append(f"Execution timeout ({timeout}s) is very low — agents may time out")
        if timeout > 3600:
            warnings.append(f"Execution timeout ({timeout}s) is very high — cycles may stall")

        # Check project.yaml has a name
        proj = self.project.get("project", {})
        if not proj.get("name") or proj.get("name") == "My Project":
            warnings.append("Project name not set — run: opensepia init <name>")

        # Check sprint config
        sprint = self.project.get("sprint", {})
        if sprint.get("cycles_per_sprint", 10) < 1:
            warnings.append("cycles_per_sprint must be at least 1")

        return warnings

    # ----- Agent & Mode Resolution -----

    def get_all_agent_ids(self) -> list[str]:
        return list(self.agents.get("agents", {}).keys())

    def get_default_mode(self) -> str:
        modes = self.agents.get("modes", {})
        for name, defn in modes.items():
            if defn.get("default"):
                return name
        return "dev-team"

    def get_all_mode_names(self) -> set[str]:
        names: set[str] = set()
        modes = self.agents.get("modes", {})
        for name, defn in modes.items():
            names.add(name)
            for alias in defn.get("aliases", []):
                names.add(alias)
        names.update(self.agents.get("agents", {}).keys())
        return names

    def _build_alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        modes = self.agents.get("modes", {})
        for name, defn in modes.items():
            alias_map[name] = name
            for alias in defn.get("aliases", []):
                alias_map[alias] = name
        return alias_map

    def resolve_agent_ids(self, mode: str) -> list[str]:
        """Resolve mode name to agent ID list."""
        modes_cfg = self.agents.get("modes", {})
        known_agents = set(self.agents.get("agents", {}).keys())

        if modes_cfg:
            alias_map = self._build_alias_map()
            canonical = alias_map.get(mode)
            if canonical and canonical in modes_cfg:
                ids = modes_cfg[canonical].get("agents", [])
                self._validate_agent_ids(ids, mode, known_agents)
                return ids

        if mode in known_agents:
            return [mode]

        ids = self._resolve_legacy_mode(mode)
        if ids is not None:
            self._validate_agent_ids(ids, mode, known_agents)
            return ids

        valid = sorted(self.get_all_mode_names())
        raise ConfigError(f"Unknown mode '{mode}'. Valid: {', '.join(valid)}")

    def _resolve_legacy_mode(self, mode: str) -> list[str] | None:
        global_cfg = self.agents.get("global", {})
        legacy_map = {
            "all": "execution_order",
            "dev-team": "dev_team_order", "dev": "dev_team_order",
            "minimal": "minimal_order", "min": "minimal_order",
            "security": "security_order", "sec": "security_order",
        }
        key = legacy_map.get(mode)
        if key and key in global_cfg:
            return global_cfg[key]
        return None

    def _validate_agent_ids(self, ids: list[str], mode: str, known: set[str]) -> None:
        for aid in ids:
            if aid not in known:
                raise ConfigError(f"Agent '{aid}' in mode '{mode}' not found in agents.yaml")

    # ----- Execution Parameters -----

    def get_execution_params(self, agent_id: str | None = None) -> dict[str, Any]:
        exec_cfg = self.agents.get("execution", {})
        params = {
            "timeout": exec_cfg.get("timeout", DEFAULT_EXECUTION["timeout"]),
            "max_retries": exec_cfg.get("max_retries", DEFAULT_EXECUTION["max_retries"]),
            "retry_delay": exec_cfg.get("retry_delay", DEFAULT_EXECUTION["retry_delay"]),
            "pause_between_agents": exec_cfg.get("pause_between_agents", DEFAULT_EXECUTION["pause_between_agents"]),
        }
        if agent_id:
            overrides = exec_cfg.get("overrides", {})
            if isinstance(overrides, dict) and agent_id in overrides:
                agent_overrides = overrides[agent_id]
                if isinstance(agent_overrides, dict):
                    params.update(agent_overrides)
        return params

    def get_mode_descriptions(self) -> dict[str, str]:
        modes = self.agents.get("modes", {})
        return {name: defn.get("description", "") for name, defn in modes.items()}
