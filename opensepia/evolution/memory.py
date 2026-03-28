"""
AI Dev Team — Agent Memory.

Persistent per-agent memory that accumulates learnings across cycles.
Agents write to their own memory via ---FILES--- output.
Memory is injected into agent context each cycle.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_MEMORY_CHARS = 10000
MAX_CONTEXT_SNIPPET = 2000


class AgentMemory:
    """Manages per-agent persistent memory across cycles."""

    def __init__(self, board_dir: Path):
        self.memory_dir = board_dir / "evolution" / "memory"

    def ensure_dir(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def load(self, agent_id: str) -> str:
        """Load agent's full memory file."""
        path = self.memory_dir / f"{agent_id}.md"
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to read memory for %s: %s", agent_id, e)
            return ""

    def append(self, agent_id: str, entry: str, sprint: int, cycle: int) -> bool:
        """Append a learning entry with sprint/cycle tag.

        Returns True if written, False if rejected (size limit).
        """
        self.ensure_dir()
        path = self.memory_dir / f"{agent_id}.md"

        existing = self.load(agent_id)
        if len(existing) + len(entry) + 50 > MAX_MEMORY_CHARS:
            logger.warning("Memory limit reached for %s (%d chars)", agent_id, len(existing))
            return False

        timestamp = f"[S{sprint}C{cycle}]"
        # Ensure entry has the timestamp tag
        if timestamp not in entry and f"[S{sprint}" not in entry:
            entry = f"- {timestamp} {entry.lstrip('- ')}"

        if existing and not existing.endswith("\n"):
            existing += "\n"

        path.write_text(existing + entry + "\n", encoding="utf-8")
        return True

    def get_context_snippet(self, agent_id: str, max_chars: int = MAX_CONTEXT_SNIPPET) -> str:
        """Return memory formatted for injection into agent context.

        Most recent entries first, truncated to max_chars.
        """
        content = self.load(agent_id)
        if not content.strip():
            return ""

        lines = content.strip().split("\n")
        # Take most recent entries (bottom of file) first
        recent = []
        total = 0
        for line in reversed(lines):
            if total + len(line) + 1 > max_chars:
                break
            recent.append(line)
            total += len(line) + 1

        recent.reverse()
        return "\n".join(recent)

    def list_agents_with_memory(self) -> list[str]:
        """List agent IDs that have memory files."""
        if not self.memory_dir.exists():
            return []
        return [
            p.stem for p in self.memory_dir.glob("*.md")
            if p.stat().st_size > 0
        ]
