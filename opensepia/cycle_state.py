"""
AI Dev Team — Cycle state persistence.

Tracks pipeline progress within a cycle for resumability.
Written after each step/agent completes so interrupted cycles
can be resumed from where they stopped.
"""

import json
import os
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CYCLE_STATE_FILE = "logs/cycle_state.json"


@dataclass
class CycleState:
    """Tracks progress within a single cycle."""

    cycle_id: str = ""                     # e.g. "s1c3"
    sprint: int = 0
    cycle: int = 0
    mode: str = ""
    status: str = "pending"                # pending | in_progress | completed | failed
    completed_steps: list[str] = field(default_factory=list)
    current_step: Optional[str] = None
    completed_agents: list[str] = field(default_factory=list)
    agent_ids: list[str] = field(default_factory=list)
    started_at: Optional[str] = None
    updated_at: Optional[str] = None

    def save(self, state_path: Path) -> None:
        """Atomically write cycle state."""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(state_path))
        except Exception as e:
            logger.warning("Failed to write cycle state: %s", e)
            tmp_path.unlink(missing_ok=True)

    @classmethod
    def load(cls, state_path: Path) -> "CycleState":
        """Load cycle state. Returns empty state if missing/corrupt."""
        if not state_path.exists():
            return cls()
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            known = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Corrupt cycle state, starting fresh: %s", e)
            return cls()

    def mark_step_complete(self, step_name: str, state_path: Path) -> None:
        """Mark a step as completed and save."""
        if step_name not in self.completed_steps:
            self.completed_steps.append(step_name)
        self.current_step = None
        self.updated_at = datetime.now().isoformat()
        self.save(state_path)

    def mark_agent_complete(self, agent_id: str, state_path: Path) -> None:
        """Mark an agent as completed within the agent_runner step."""
        if agent_id not in self.completed_agents:
            self.completed_agents.append(agent_id)
        self.updated_at = datetime.now().isoformat()
        self.save(state_path)

    def mark_completed(self, state_path: Path) -> None:
        """Mark the entire cycle as completed."""
        self.status = "completed"
        self.current_step = None
        self.updated_at = datetime.now().isoformat()
        self.save(state_path)

    def mark_failed(self, state_path: Path) -> None:
        """Mark the cycle as failed."""
        self.status = "failed"
        self.updated_at = datetime.now().isoformat()
        self.save(state_path)

    @property
    def is_interrupted(self) -> bool:
        """Was this cycle interrupted (in_progress but not completed)?"""
        return self.status == "in_progress"

    def remaining_steps(self, all_steps: list[str]) -> list[str]:
        """Get steps that haven't completed yet."""
        done = set(self.completed_steps)
        return [s for s in all_steps if s not in done]

    def remaining_agents(self) -> list[str]:
        """Get agents that haven't completed yet."""
        done = set(self.completed_agents)
        return [a for a in self.agent_ids if a not in done]
