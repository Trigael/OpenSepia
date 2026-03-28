"""
AI Dev Team — Agent Spawning & Lineage.

Handles creation of new specialist agents by parent agents.
Tracks lineage (ancestor/descendant tree) for all agents.
"""

import logging
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SpawnedAgent:
    """A dynamically created specialist agent."""
    agent_id: str
    name: str
    color: str
    parent_id: str
    lineage: list[str]
    system_prompt: str
    spawned_at: str
    sprint: int
    cycle: int
    status: str = "active"  # active | pending_approval | inactive


class AgentSpawner:
    """Handles creation of new specialist agents and lineage tracking."""

    def __init__(self, board_dir: Path):
        self.board_dir = board_dir
        self.registry_path = board_dir / "evolution" / "registry.yaml"
        self.lineage_path = board_dir / "evolution" / "lineage" / "lineage.yaml"

    # ----- Lineage -----

    def initialize_lineage(self, agent_ids: list[str]) -> None:
        """Initialize lineage with base agents from config."""
        self.lineage_path.parent.mkdir(parents=True, exist_ok=True)

        existing = self._load_lineage()
        agents = existing.get("agents", {})

        for aid in agent_ids:
            if aid not in agents:
                agents[aid] = {
                    "type": "original",
                    "created": datetime.now().isoformat(),
                    "children": [],
                }

        existing["agents"] = agents
        self._save_lineage(existing)

    def get_lineage(self, agent_id: str) -> dict[str, Any]:
        """Get lineage info for an agent."""
        data = self._load_lineage()
        return data.get("agents", {}).get(agent_id, {})

    def get_lineage_context(self, agent_id: str) -> str:
        """Get human-readable lineage context for agent prompt."""
        info = self.get_lineage(agent_id)
        if not info or info.get("type") == "original":
            return ""
        parent = info.get("parent", "unknown")
        ancestors = info.get("lineage", [parent])
        return f"You were spawned from {parent}. Ancestors: {ancestors}"

    # ----- Spawning -----

    def execute_spawn_from_details(
        self,
        parent_id: str,
        child_id: str,
        child_name: str,
        child_prompt: str,
        sprint: int,
        cycle: int,
    ) -> SpawnedAgent:
        """Create a new agent from spawn details."""
        # Determine lineage
        parent_lineage = self.get_lineage(parent_id)
        parent_ancestors = parent_lineage.get("lineage", [])
        if parent_lineage.get("type") == "original":
            child_lineage = [parent_id]
        else:
            child_lineage = list(parent_ancestors) + [parent_id]

        spawned = SpawnedAgent(
            agent_id=child_id,
            name=child_name,
            color="🔧",  # Default color for spawned agents
            parent_id=parent_id,
            lineage=child_lineage,
            system_prompt=child_prompt,
            spawned_at=datetime.now().isoformat(),
            sprint=sprint,
            cycle=cycle,
        )

        # Add to registry
        self._add_to_registry(spawned)

        # Update lineage
        self._add_to_lineage(spawned)

        # Create inbox file
        inbox_dir = self.board_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        inbox_file = inbox_dir / f"{child_id}.md"
        if not inbox_file.exists():
            inbox_file.write_text("", encoding="utf-8")

        # Create memory directory
        memory_dir = self.board_dir / "evolution" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        # Copy parent's memory as starting context
        parent_memory = memory_dir / f"{parent_id}.md"
        child_memory = memory_dir / f"{child_id}.md"
        if parent_memory.exists() and not child_memory.exists():
            content = parent_memory.read_text(encoding="utf-8")
            child_memory.write_text(
                f"# Inherited from {parent_id}\n{content}\n\n# Own learnings\n",
                encoding="utf-8",
            )

        logger.info("Spawned agent %s from %s (lineage: %s)",
                     child_id, parent_id, child_lineage)
        return spawned

    def get_spawned_agents(self) -> list[SpawnedAgent]:
        """List all spawned agents from the registry."""
        registry = self._load_registry()
        agents = []
        for aid, defn in registry.get("agents", {}).items():
            if defn.get("status") == "active":
                agents.append(SpawnedAgent(
                    agent_id=aid,
                    name=defn.get("name", aid),
                    color=defn.get("color", "🔧"),
                    parent_id=defn.get("parent", ""),
                    lineage=defn.get("lineage", []),
                    system_prompt=defn.get("system_prompt", ""),
                    spawned_at=defn.get("spawned_at", ""),
                    sprint=defn.get("sprint", 0),
                    cycle=defn.get("cycle", 0),
                    status="active",
                ))
        return agents

    def get_active_agent_ids(self) -> list[str]:
        """Get IDs of all active spawned agents."""
        return [a.agent_id for a in self.get_spawned_agents()]

    def deactivate_agent(self, agent_id: str) -> None:
        """Mark a spawned agent as inactive."""
        registry = self._load_registry()
        if agent_id in registry.get("agents", {}):
            registry["agents"][agent_id]["status"] = "inactive"
            self._save_registry(registry)
            logger.info("Deactivated spawned agent: %s", agent_id)

    # ----- Internal helpers -----

    def _load_registry(self) -> dict:
        if not self.registry_path.exists():
            return {"agents": {}}
        try:
            data = yaml.safe_load(self.registry_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"agents": {}}
        except (yaml.YAMLError, OSError):
            return {"agents": {}}

    def _save_registry(self, data: dict) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _add_to_registry(self, agent: SpawnedAgent) -> None:
        registry = self._load_registry()
        registry.setdefault("agents", {})[agent.agent_id] = {
            "name": agent.name,
            "color": agent.color,
            "parent": agent.parent_id,
            "lineage": agent.lineage,
            "system_prompt": agent.system_prompt,
            "spawned_at": agent.spawned_at,
            "sprint": agent.sprint,
            "cycle": agent.cycle,
            "status": agent.status,
        }
        self._save_registry(registry)

    def _load_lineage(self) -> dict:
        if not self.lineage_path.exists():
            return {"agents": {}}
        try:
            data = yaml.safe_load(self.lineage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"agents": {}}
        except (yaml.YAMLError, OSError):
            return {"agents": {}}

    def _save_lineage(self, data: dict) -> None:
        self.lineage_path.parent.mkdir(parents=True, exist_ok=True)
        self.lineage_path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _add_to_lineage(self, agent: SpawnedAgent) -> None:
        lineage = self._load_lineage()
        agents = lineage.setdefault("agents", {})

        # Add child
        agents[agent.agent_id] = {
            "type": "spawned",
            "parent": agent.parent_id,
            "lineage": agent.lineage,
            "created": agent.spawned_at,
            "children": [],
        }

        # Update parent's children list
        if agent.parent_id in agents:
            children = agents[agent.parent_id].setdefault("children", [])
            if agent.agent_id not in children:
                children.append(agent.agent_id)

        self._save_lineage(lineage)
