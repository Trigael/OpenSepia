"""
AI Dev Team — Centralized configuration loading.

Loads agents.yaml, project.yaml, and .env in one place.
All mode resolution and execution parameters are driven by YAML.
"""

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.errors import ConfigError

# Default execution parameters (used when YAML doesn't specify)
DEFAULT_EXECUTION = {
    "timeout": 900,
    "max_retries": 1,
    "retry_delay": 30,
    "pause_between_agents": 0,
}


@dataclass
class OrchestratorConfig:
    """Centralized configuration loaded once at startup."""
    project_dir: Path
    agents: dict[str, Any]
    project: dict[str, Any]
    board_dir: Path
    workspace_dir: Path
    config_dir: Path
    logs_dir: Path

    @classmethod
    def load(cls, project_dir: Path | None = None) -> "OrchestratorConfig":
        """Load all configuration files.

        Args:
            project_dir: Project root. Defaults to two levels up from this file.

        Returns:
            Populated OrchestratorConfig instance.

        Raises:
            ConfigError: If required config files are missing or invalid.
        """
        if project_dir is None:
            project_dir = Path(__file__).parent.parent

        config_dir = project_dir / "config"
        board_dir = project_dir / "board"
        workspace_dir = project_dir / "workspace"
        logs_dir = project_dir / "logs" / "runs"

        # Load .env
        env_file = config_dir / ".env"
        if env_file.exists():
            import os
            for line in env_file.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

        # Load agents.yaml
        agents_file = config_dir / "agents.yaml"
        if not agents_file.exists():
            raise ConfigError(f"Missing agents config: {agents_file}")
        try:
            with open(agents_file, "r") as f:
                agents = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid agents.yaml: {e}") from e

        if not agents or "agents" not in agents:
            raise ConfigError("agents.yaml must contain an 'agents' key")

        # Load project.yaml
        project_file = config_dir / "project.yaml"
        if not project_file.exists():
            raise ConfigError(f"Missing project config: {project_file}")
        try:
            with open(project_file, "r") as f:
                project = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid project.yaml: {e}") from e

        return cls(
            project_dir=project_dir,
            agents=agents,
            project=project,
            board_dir=board_dir,
            workspace_dir=workspace_dir,
            config_dir=config_dir,
            logs_dir=logs_dir,
        )

    @property
    def sprint_cfg(self) -> dict[str, Any]:
        """Shortcut to sprint configuration."""
        return self.project.get("sprint", {})

    @property
    def sprint_num(self) -> int:
        return self.sprint_cfg.get("current_sprint", 1)

    @property
    def cycle_num(self) -> int:
        return self.sprint_cfg.get("current_cycle", 0)

    def save_project(self) -> None:
        """Write project.yaml back to disk."""
        with open(self.config_dir / "project.yaml", "w") as f:
            yaml.dump(self.project, f, default_flow_style=False, allow_unicode=True)

    # ----- Agent & Mode Resolution -----

    def get_all_agent_ids(self) -> list[str]:
        """All agent IDs defined in agents.yaml."""
        return list(self.agents.get("agents", {}).keys())

    def get_default_mode(self) -> str:
        """Mode marked as default in YAML, or 'dev-team'."""
        modes = self.agents.get("modes", {})
        for name, defn in modes.items():
            if defn.get("default"):
                return name
        return "dev-team"

    def get_all_mode_names(self) -> set[str]:
        """All valid mode names, aliases, and single agent names."""
        names: set[str] = set()
        modes = self.agents.get("modes", {})
        for name, defn in modes.items():
            names.add(name)
            for alias in defn.get("aliases", []):
                names.add(alias)
        names.update(self.agents.get("agents", {}).keys())
        return names

    def _build_alias_map(self) -> dict[str, str]:
        """Build alias -> canonical mode name mapping from YAML."""
        alias_map: dict[str, str] = {}
        modes = self.agents.get("modes", {})
        for name, defn in modes.items():
            alias_map[name] = name
            for alias in defn.get("aliases", []):
                alias_map[alias] = name
        return alias_map

    def resolve_agent_ids(self, mode: str) -> list[str]:
        """Resolve mode name (or alias or agent name) to agent ID list.

        Reads from the 'modes' section in agents.yaml. Falls back to
        legacy 'global.*_order' keys for backward compatibility.

        Args:
            mode: Mode name, alias, or single agent name.

        Returns:
            Ordered list of agent IDs to run.

        Raises:
            ConfigError: If mode is unknown or references undefined agents.
        """
        modes_cfg = self.agents.get("modes", {})
        known_agents = set(self.agents.get("agents", {}).keys())

        # Try modes section first (with alias resolution)
        if modes_cfg:
            alias_map = self._build_alias_map()
            canonical = alias_map.get(mode)
            if canonical and canonical in modes_cfg:
                ids = modes_cfg[canonical].get("agents", [])
                self._validate_agent_ids(ids, mode, known_agents)
                return ids

        # Single agent name
        if mode in known_agents:
            return [mode]

        # Legacy fallback: global.*_order keys
        ids = self._resolve_legacy_mode(mode)
        if ids is not None:
            self._validate_agent_ids(ids, mode, known_agents)
            return ids

        # Nothing matched
        valid = sorted(self.get_all_mode_names())
        raise ConfigError(
            f"Unknown mode '{mode}'. Valid: {', '.join(valid)}"
        )

    def _resolve_legacy_mode(self, mode: str) -> list[str] | None:
        """Fallback: resolve mode from legacy global.*_order keys."""
        global_cfg = self.agents.get("global", {})
        legacy_map = {
            "all": "execution_order",
            "dev-team": "dev_team_order",
            "dev": "dev_team_order",
            "minimal": "minimal_order",
            "min": "minimal_order",
            "security": "security_order",
            "sec": "security_order",
        }
        key = legacy_map.get(mode)
        if key and key in global_cfg:
            return global_cfg[key]
        return None

    def _validate_agent_ids(self, ids: list[str], mode: str, known: set[str]) -> None:
        """Raise ConfigError if any agent ID is undefined."""
        for aid in ids:
            if aid not in known:
                raise ConfigError(
                    f"Agent '{aid}' referenced in mode '{mode}' not found in agents.yaml"
                )

    # ----- Execution Parameters -----

    def get_execution_params(self, agent_id: str | None = None) -> dict[str, Any]:
        """Get execution parameters, optionally merged with per-agent overrides.

        Args:
            agent_id: If provided, merge agent-specific overrides.

        Returns:
            Dict with keys: timeout, max_retries, retry_delay, pause_between_agents
        """
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
        """Get mode name -> description mapping for help text."""
        modes = self.agents.get("modes", {})
        return {name: defn.get("description", "") for name, defn in modes.items()}
