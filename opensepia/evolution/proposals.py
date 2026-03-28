"""
AI Dev Team — Evolution Proposal Lifecycle.

Manages the proposal pipeline: create → validate → approve/reject → apply.
Proposals are YAML files in evolution/proposals/{pending,approved,rejected}/.
"""

import logging
import shutil
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia.evolution.guardrails import validate_prompt, validate_spawn

logger = logging.getLogger(__name__)


class ProposalManager:
    """Manages the proposal lifecycle for all evolution changes."""

    def __init__(self, board_dir: Path, agents_config: dict | None = None):
        self.proposals_dir = board_dir / "evolution" / "proposals"
        self.board_dir = board_dir
        self.agents_config = agents_config or {}

    def create_proposal(
        self,
        proposal_type: str,
        proposed_by: str,
        details: dict[str, Any],
        sprint: int,
        cycle: int,
    ) -> Path:
        """Create a new proposal file in pending/."""
        pending_dir = self.proposals_dir / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{proposed_by}_{proposal_type}.yaml"
        path = pending_dir / filename

        proposal = {
            "type": proposal_type,
            "proposed_by": proposed_by,
            "proposed_at": datetime.now().isoformat(),
            "sprint": sprint,
            "cycle": cycle,
            "status": "pending",
            "details": details,
        }

        path.write_text(
            yaml.dump(proposal, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("Proposal created: %s by %s (%s)", proposal_type, proposed_by, filename)
        return path

    def get_pending(self) -> list[dict[str, Any]]:
        """List all pending proposals."""
        pending_dir = self.proposals_dir / "pending"
        if not pending_dir.exists():
            return []

        proposals = []
        for path in sorted(pending_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if data:
                    data["path"] = str(path)
                    proposals.append(data)
            except (yaml.YAMLError, OSError) as e:
                logger.warning("Invalid proposal %s: %s", path.name, e)
        return proposals

    def approve(self, proposal_path: str | Path) -> dict[str, Any]:
        """Approve and execute a proposal. Moves to approved/."""
        path = Path(proposal_path)
        if not path.exists():
            return {"error": f"Proposal not found: {path}"}

        try:
            proposal = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as e:
            return {"error": f"Invalid proposal: {e}"}

        if not proposal:
            return {"error": "Empty proposal"}

        # Execute based on type
        result = self._execute(proposal)
        if "error" in result:
            return result

        # Move to approved
        proposal["status"] = "approved"
        proposal["approved_at"] = datetime.now().isoformat()
        proposal["result"] = result

        approved_dir = self.proposals_dir / "approved"
        approved_dir.mkdir(parents=True, exist_ok=True)
        approved_path = approved_dir / path.name
        approved_path.write_text(
            yaml.dump(proposal, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        path.unlink()

        logger.info("Proposal approved: %s", path.name)
        return result

    def reject(self, proposal_path: str | Path, reason: str = "") -> None:
        """Reject a proposal. Moves to rejected/."""
        path = Path(proposal_path)
        if not path.exists():
            return

        try:
            proposal = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            proposal = {}

        if proposal:
            proposal["status"] = "rejected"
            proposal["rejected_at"] = datetime.now().isoformat()
            proposal["rejection_reason"] = reason

        rejected_dir = self.proposals_dir / "rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        rejected_path = rejected_dir / path.name
        rejected_path.write_text(
            yaml.dump(proposal or {}, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        path.unlink()
        logger.info("Proposal rejected: %s — %s", path.name, reason)

    def auto_process(self, auto_approve_config: dict[str, bool]) -> list[dict]:
        """Process proposals that can be auto-approved based on config.

        Returns list of applied proposals.
        """
        applied = []
        for proposal in self.get_pending():
            ptype = proposal.get("type", "")
            should_auto = auto_approve_config.get(ptype, False)

            # Memory and skills default to auto-approve
            if ptype in ("memory", "skill") and auto_approve_config.get(ptype, True):
                should_auto = True

            if should_auto:
                result = self.approve(proposal["path"])
                if "error" not in result:
                    applied.append(proposal)
                else:
                    logger.warning("Auto-approve failed for %s: %s", proposal.get("path"), result)

        return applied

    def _execute(self, proposal: dict) -> dict[str, Any]:
        """Execute a proposal based on its type."""
        ptype = proposal.get("type", "")
        details = proposal.get("details", {})

        if ptype == "prompt_refine":
            return self._execute_prompt_refine(proposal)
        elif ptype == "spawn_agent":
            return self._execute_spawn(proposal)
        elif ptype == "skill":
            return {"status": "ok", "note": "Skill files are written directly"}
        elif ptype == "memory":
            return {"status": "ok", "note": "Memory entries are written directly"}
        else:
            return {"error": f"Unknown proposal type: {ptype}"}

    def _execute_prompt_refine(self, proposal: dict) -> dict[str, Any]:
        """Execute a prompt refinement proposal."""
        details = proposal.get("details", {})
        agent_id = proposal.get("proposed_by", "")
        new_prompt = details.get("new_prompt", "")
        reason = details.get("reason", "")
        diff_summary = details.get("diff_summary", "")

        if not new_prompt:
            return {"error": "No new_prompt in proposal details"}

        # Validate
        validation = validate_prompt(agent_id, new_prompt, self.agents_config)
        if not validation.valid:
            return {"error": f"Validation failed: {validation.errors}"}

        # Apply
        from opensepia.evolution.prompts import PromptManager
        pm = PromptManager(self.board_dir)
        version = pm.apply_refinement(agent_id, new_prompt, agent_id, reason, diff_summary)

        return {"status": "ok", "version": version.version, "agent_id": agent_id}

    def _execute_spawn(self, proposal: dict) -> dict[str, Any]:
        """Execute an agent spawn proposal."""
        details = proposal.get("details", {})
        parent_id = proposal.get("proposed_by", "")
        child_id = details.get("child_id", "")
        child_name = details.get("child_name", "")
        child_prompt = details.get("child_prompt", "")

        if not all([child_id, child_name, child_prompt]):
            return {"error": "Missing required spawn fields: child_id, child_name, child_prompt"}

        # Validate
        existing = set(self.agents_config.get("agents", {}).keys())
        validation = validate_spawn(parent_id, child_id, child_prompt, existing)
        if not validation.valid:
            return {"error": f"Validation failed: {validation.errors}"}

        # Execute spawn
        from opensepia.evolution.spawning import AgentSpawner
        spawner = AgentSpawner(self.board_dir)
        spawned = spawner.execute_spawn_from_details(
            parent_id=parent_id,
            child_id=child_id,
            child_name=child_name,
            child_prompt=child_prompt,
            sprint=proposal.get("sprint", 0),
            cycle=proposal.get("cycle", 0),
        )
        return {"status": "ok", "agent_id": spawned.agent_id}
