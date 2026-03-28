"""Evolution CLI command — manage agent evolution proposals."""

import sys
import argparse
from pathlib import Path

from opensepia import log
from opensepia.config import OrchestratorConfig
from opensepia.errors import ConfigError


def cmd_evolve(argv: list[str]) -> None:
    """Manage agent evolution: proposals, prompts, lineage."""
    parser = argparse.ArgumentParser(prog="opensepia evolve", description="Manage agent evolution")
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("list", help="List pending proposals")
    sub.add_parser("status", help="Show evolution status")

    approve_p = sub.add_parser("approve", help="Approve a proposal")
    approve_p.add_argument("id", help="Proposal filename or index")

    reject_p = sub.add_parser("reject", help="Reject a proposal")
    reject_p.add_argument("id", help="Proposal filename or index")
    reject_p.add_argument("--reason", default="", help="Rejection reason")

    rollback_p = sub.add_parser("rollback", help="Rollback agent prompt")
    rollback_p.add_argument("agent_id", help="Agent ID")
    rollback_p.add_argument("--version", type=int, required=True, help="Version to rollback to")

    args = parser.parse_args(argv)
    if not args.action:
        parser.print_help()
        return

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        log.error(str(e))
        sys.exit(1)

    board_dir = config.board_dir
    evo_dir = board_dir / "evolution"

    if not evo_dir.exists():
        log.warn("Evolution not initialized. Run 'opensepia init' first.")
        return

    if args.action == "list":
        _list_proposals(board_dir, config)
    elif args.action == "status":
        _show_status(board_dir, config)
    elif args.action == "approve":
        _approve(board_dir, config, args.id)
    elif args.action == "reject":
        _reject(board_dir, config, args.id, args.reason)
    elif args.action == "rollback":
        _rollback(board_dir, args.agent_id, args.version)


def _list_proposals(board_dir: Path, config: OrchestratorConfig) -> None:
    from opensepia.evolution.proposals import ProposalManager
    pm = ProposalManager(board_dir, config.agents)
    pending = pm.get_pending()

    if not pending:
        log.info("No pending proposals.")
        return

    log.header(f"Pending Proposals ({len(pending)})")
    for i, p in enumerate(pending):
        ptype = p.get("type", "?")
        by = p.get("proposed_by", "?")
        at = p.get("proposed_at", "?")[:19]
        details = p.get("details", {})

        log.info(f"  [{i}] {ptype} by {by} at {at}")
        if ptype == "prompt_refine":
            log.info(f"      Reason: {details.get('reason', '?')}")
            log.info(f"      Diff: {details.get('diff_summary', '?')}")
        elif ptype == "spawn_agent":
            log.info(f"      Child: {details.get('child_id', '?')} ({details.get('child_name', '?')})")
        elif ptype == "split_agent":
            into = details.get("into", [])
            log.info(f"      Split {details.get('original_id', '?')} into: {[s.get('id') for s in into]}")
            log.info(f"      Reason: {details.get('reason', '?')}")


def _show_status(board_dir: Path, config: OrchestratorConfig) -> None:
    log.header("Evolution Status")

    # Memory
    from opensepia.evolution.memory import AgentMemory
    mem = AgentMemory(board_dir)
    agents_with_memory = mem.list_agents_with_memory()
    log.info(f"  Agents with memory: {len(agents_with_memory)}")
    for aid in agents_with_memory:
        content = mem.load(aid)
        log.info(f"    {aid}: {len(content)} chars")

    # Skills
    from opensepia.evolution.skills import SkillStore
    store = SkillStore(board_dir)
    skills = store.list_skills()
    log.info(f"  Skills: {len(skills)}")
    for s in skills:
        log.info(f"    {s.name} ({s.scope}) — tags: {s.tags}")

    # Prompts
    from opensepia.evolution.prompts import PromptManager
    pm = PromptManager(board_dir)
    for aid in config.get_all_agent_ids():
        ver = pm.get_current_version(aid)
        if ver > 0:
            log.info(f"  Prompt {aid}: v{ver}")

    # Spawned agents
    from opensepia.evolution.spawning import AgentSpawner
    spawner = AgentSpawner(board_dir)
    spawned = spawner.get_spawned_agents()
    if spawned:
        log.info(f"  Spawned agents: {len(spawned)}")
        for a in spawned:
            log.info(f"    {a.agent_id} (from {a.parent_id}) — {a.status}")

    # Proposals
    from opensepia.evolution.proposals import ProposalManager
    proposals = ProposalManager(board_dir, config.agents)
    pending = proposals.get_pending()
    log.info(f"  Pending proposals: {len(pending)}")


def _approve(board_dir: Path, config: OrchestratorConfig, proposal_id: str) -> None:
    from opensepia.evolution.proposals import ProposalManager
    pm = ProposalManager(board_dir, config.agents)
    pending = pm.get_pending()

    # Find by index or filename
    target = None
    try:
        idx = int(proposal_id)
        if 0 <= idx < len(pending):
            target = pending[idx]
    except ValueError:
        for p in pending:
            if proposal_id in p.get("path", ""):
                target = p
                break

    if not target:
        log.error(f"Proposal not found: {proposal_id}")
        return

    result = pm.approve(target["path"])
    if "error" in result:
        log.error(f"Failed: {result['error']}")
    else:
        log.success(f"Approved: {target.get('type', '?')} by {target.get('proposed_by', '?')}")


def _reject(board_dir: Path, config: OrchestratorConfig, proposal_id: str, reason: str) -> None:
    from opensepia.evolution.proposals import ProposalManager
    pm = ProposalManager(board_dir, config.agents)
    pending = pm.get_pending()

    target = None
    try:
        idx = int(proposal_id)
        if 0 <= idx < len(pending):
            target = pending[idx]
    except ValueError:
        for p in pending:
            if proposal_id in p.get("path", ""):
                target = p
                break

    if not target:
        log.error(f"Proposal not found: {proposal_id}")
        return

    pm.reject(target["path"], reason)
    log.success(f"Rejected: {target.get('type', '?')}")


def _rollback(board_dir: Path, agent_id: str, version: int) -> None:
    from opensepia.evolution.prompts import PromptManager
    pm = PromptManager(board_dir)
    result = pm.rollback(agent_id, version)
    if result:
        log.success(f"Rolled back {agent_id} to v{version} (now v{result.version})")
    else:
        log.error(f"Version {version} not found for {agent_id}")
