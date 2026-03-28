"""
AI Dev Team — Prompt Self-Refinement.

Manages versioned prompt history. Agents can propose refinements
to their own system prompts, which are validated and versioned.
"""

import logging
import yaml
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PromptVersion:
    """A versioned snapshot of an agent's system prompt."""
    version: int
    agent_id: str
    parent_version: int | None
    timestamp: str
    proposed_by: str
    reason: str
    system_prompt: str
    diff_summary: str


class PromptManager:
    """Manages versioned prompt history and self-refinement."""

    def __init__(self, board_dir: Path):
        self.prompts_dir = board_dir / "evolution" / "prompts"

    def get_active_prompt(self, agent_id: str) -> str | None:
        """Get the active refined prompt, or None to use agents.yaml default."""
        active_path = self.prompts_dir / agent_id / "active.yaml"
        if not active_path.exists():
            return None

        try:
            data = yaml.safe_load(active_path.read_text(encoding="utf-8"))
            if not data:
                return None
            version = data.get("active_version")
            if version is None:
                return None
            return self._load_version_prompt(agent_id, version)
        except (yaml.YAMLError, OSError) as e:
            logger.warning("Failed to read active prompt for %s: %s", agent_id, e)
            return None

    def _load_version_prompt(self, agent_id: str, version: int) -> str | None:
        """Load the system_prompt from a specific version file."""
        history_dir = self.prompts_dir / agent_id / "history"
        if not history_dir.exists():
            return None

        # Find version file by prefix
        prefix = f"v{version:03d}_"
        for path in history_dir.glob(f"{prefix}*.yaml"):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                return data.get("system_prompt")
            except (yaml.YAMLError, OSError):
                continue
        return None

    def get_version_history(self, agent_id: str) -> list[PromptVersion]:
        """Get full version history for an agent's prompt."""
        history_dir = self.prompts_dir / agent_id / "history"
        if not history_dir.exists():
            return []

        versions = []
        for path in sorted(history_dir.glob("v*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if data:
                    versions.append(PromptVersion(
                        version=data.get("version", 0),
                        agent_id=data.get("agent_id", agent_id),
                        parent_version=data.get("parent_version"),
                        timestamp=data.get("timestamp", ""),
                        proposed_by=data.get("proposed_by", ""),
                        reason=data.get("reason", ""),
                        system_prompt=data.get("system_prompt", ""),
                        diff_summary=data.get("diff_summary", ""),
                    ))
            except (yaml.YAMLError, OSError):
                continue
        return versions

    def initialize_from_config(self, agent_id: str, base_prompt: str) -> None:
        """Create v001 from the agents.yaml prompt (idempotent)."""
        agent_dir = self.prompts_dir / agent_id / "history"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Check if v001 already exists
        if list(agent_dir.glob("v001_*.yaml")):
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version_file = agent_dir / f"v001_{timestamp}.yaml"
        version_file.write_text(yaml.dump({
            "version": 1,
            "agent_id": agent_id,
            "parent_version": None,
            "timestamp": datetime.now().isoformat(),
            "proposed_by": "system",
            "reason": "Initial prompt from agents.yaml",
            "system_prompt": base_prompt,
            "diff_summary": "Initial version",
        }, default_flow_style=False, allow_unicode=True), encoding="utf-8")

    def apply_refinement(
        self,
        agent_id: str,
        new_prompt: str,
        proposed_by: str,
        reason: str,
        diff_summary: str = "",
    ) -> PromptVersion:
        """Apply a validated prompt refinement, creating a new version."""
        history = self.get_version_history(agent_id)
        new_version = (history[-1].version + 1) if history else 1
        parent_version = history[-1].version if history else None

        agent_dir = self.prompts_dir / agent_id / "history"
        agent_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version_data = {
            "version": new_version,
            "agent_id": agent_id,
            "parent_version": parent_version,
            "timestamp": datetime.now().isoformat(),
            "proposed_by": proposed_by,
            "reason": reason,
            "system_prompt": new_prompt,
            "diff_summary": diff_summary or f"Refinement by {proposed_by}",
        }

        version_file = agent_dir / f"v{new_version:03d}_{timestamp}.yaml"
        version_file.write_text(
            yaml.dump(version_data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        # Update active pointer
        active_path = self.prompts_dir / agent_id / "active.yaml"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_text(
            yaml.dump({"active_version": new_version, "agent_id": agent_id},
                      default_flow_style=False),
            encoding="utf-8",
        )

        logger.info("Prompt refined: %s v%d by %s — %s", agent_id, new_version, proposed_by, reason)

        return PromptVersion(
            version=new_version,
            agent_id=agent_id,
            parent_version=parent_version,
            timestamp=datetime.now().isoformat(),
            proposed_by=proposed_by,
            reason=reason,
            system_prompt=new_prompt,
            diff_summary=diff_summary,
        )

    def rollback(self, agent_id: str, to_version: int) -> PromptVersion | None:
        """Rollback to a previous prompt version."""
        prompt = self._load_version_prompt(agent_id, to_version)
        if not prompt:
            logger.warning("Cannot rollback %s to v%d — version not found", agent_id, to_version)
            return None

        return self.apply_refinement(
            agent_id, prompt,
            proposed_by="system",
            reason=f"Rollback to version {to_version}",
            diff_summary=f"Rollback to v{to_version}",
        )

    def get_current_version(self, agent_id: str) -> int:
        """Get the current active version number."""
        active_path = self.prompts_dir / agent_id / "active.yaml"
        if not active_path.exists():
            return 0
        try:
            data = yaml.safe_load(active_path.read_text(encoding="utf-8"))
            return data.get("active_version", 0) if data else 0
        except (yaml.YAMLError, OSError):
            return 0
