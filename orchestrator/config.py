"""
AI Dev Team — Centralized configuration loading.

Loads agents.yaml, project.yaml, and .env in one place.
"""

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.errors import ConfigError


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

    def resolve_agent_ids(self, mode: str) -> list[str]:
        """Resolve mode name to list of agent IDs.

        Args:
            mode: One of 'all', 'dev-team', 'minimal', 'security', or a single agent name.

        Returns:
            List of agent IDs to run.

        Raises:
            ConfigError: If mode is unknown or agent not found.
        """
        global_cfg = self.agents.get("global", {})
        known_agents = set(self.agents.get("agents", {}).keys())

        if mode in ("all",):
            ids = global_cfg.get("execution_order", list(known_agents))
        elif mode in ("dev-team", "dev"):
            ids = global_cfg.get("dev_team_order", ["po", "pm", "dev1", "dev2", "devops", "tester"])
        elif mode in ("minimal", "min"):
            ids = global_cfg.get("minimal_order", ["po", "dev1", "tester"])
        elif mode in ("security", "sec"):
            ids = global_cfg.get("security_order", ["sec_analyst", "sec_engineer", "sec_pentester"])
        elif mode in known_agents:
            ids = [mode]
        else:
            raise ConfigError(
                f"Unknown mode '{mode}'. Valid: all, dev-team, minimal, security, "
                f"or a single agent: {', '.join(sorted(known_agents))}"
            )

        # Validate all agent IDs exist
        for aid in ids:
            if aid not in known_agents:
                raise ConfigError(f"Agent '{aid}' referenced in mode '{mode}' not found in agents.yaml")

        return ids
