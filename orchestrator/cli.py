"""
AI Dev Team — Orchestrator CLI.

Main entry point that replaces orchestrator_cli.sh.
Builds and runs the pipeline based on the selected mode.

Usage:
    python -m orchestrator [mode] [options]

Modes:
    all          All 9 agents
    dev-team     6 agents (core team) [default]
    minimal      3 agents (PO, Dev1, Tester)
    security     3 agents (security team)
    <agent>      Single agent (po, pm, dev1, dev2, devops, tester,
                 sec_analyst, sec_engineer, sec_pentester)
"""

import os
import sys
import shutil
import argparse
import logging
from datetime import datetime
from pathlib import Path

from orchestrator.config import OrchestratorConfig
from orchestrator.errors import OrchestratorError, ConfigError, LockError
from orchestrator.lockfile import ProcessLock
from orchestrator.pipeline import Pipeline, PipelineContext
from orchestrator.steps.board_health import BoardHealthStep, SnapshotStep
from orchestrator.steps.sprint_check import SprintCheckStep, SprintSyncStep
from orchestrator.steps.agent_runner import AgentRunnerStep
from orchestrator.steps.standup_sync import StandupSyncStep
from orchestrator.steps.merge_mrs import MergeMRsStep
from orchestrator.steps.git_sync import GitSyncStep
from orchestrator.steps.board_sync import BoardSyncStep
from orchestrator.steps.logging_step import CycleLogStep
from orchestrator.steps.alerting import AlertingStep

logger = logging.getLogger(__name__)

# Valid single-agent names
SINGLE_AGENTS = {
    "po", "pm", "dev1", "dev2", "devops", "tester",
    "sec_analyst", "sec_engineer", "sec_pentester",
}

# Mode aliases
MODE_ALIASES = {
    "dev": "dev-team",
    "min": "minimal",
    "sec": "security",
}


def build_pipeline() -> Pipeline:
    """Construct the full orchestrator pipeline.

    Step order:
    1. Board health check + restore if needed
    2. Sprint check (detect end, increment cycle)
    3. Board snapshot (before agents modify anything)
    4. Agent runner (the main work)
    5. Sprint sync (board -> project.yaml)
    6. Standup sync (standup.md -> provider)
    7. Auto-merge approved MRs
    8. Git sync (workspace -> repo -> branch -> MR)
    9. Board sync (board -> provider issues)
    10. Cycle log (JSON)
    11. Alerting (on failure)
    """
    return Pipeline(steps=[
        # PRE-AGENT PHASE
        BoardHealthStep(),
        SprintCheckStep(),
        SnapshotStep(),

        # AGENT PHASE
        AgentRunnerStep(),

        # POST-AGENT PHASE
        SprintSyncStep(),
        StandupSyncStep(),
        MergeMRsStep(),
        GitSyncStep(),
        BoardSyncStep(),

        # HOUSEKEEPING
        CycleLogStep(),
        AlertingStep(),
    ])


def check_claude_cli() -> bool:
    """Check if Claude Code CLI is available."""
    return shutil.which("claude") is not None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Dev Team — Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modes:\n"
            "  all          All 9 agents\n"
            "  dev-team     6 agents (core team) [default]\n"
            "  minimal      3 agents (PO, Dev1, Tester)\n"
            "  security     3 agents (security team)\n"
            "  <agent>      Single agent (po, pm, dev1, dev2, devops, tester,\n"
            "               sec_analyst, sec_engineer, sec_pentester)\n"
        ),
    )
    parser.add_argument(
        "mode", nargs="?", default="dev-team",
        help="Execution mode or agent name (default: dev-team)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Show context without calling Claude")
    parser.add_argument("--no-increment", action="store_true", help="Don't increment cycle number")

    args = parser.parse_args()

    # Resolve mode aliases
    mode = MODE_ALIASES.get(args.mode, args.mode)

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Unset CLAUDECODE to prevent "nested session" errors
    os.environ.pop("CLAUDECODE", None)

    print()
    print("============================================")
    print("  AI Dev Team — Orchestrator")
    print(f"  {datetime.now()}")
    print(f"  Mode: {mode}")
    print("============================================")

    # Check Claude CLI
    if not check_claude_cli():
        print("  WARNING: Claude Code CLI not in PATH — agents will not run")
        print("  Install: npm install -g @anthropic-ai/claude-code")

    # Load configuration
    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Resolve agent IDs for mode
    try:
        agent_ids = config.resolve_agent_ids(mode)
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Acquire lock
    lock = ProcessLock(mode)
    try:
        lock.acquire()
    except LockError as e:
        print(f"  {e}")
        sys.exit(0)

    try:
        # Build pipeline context
        ctx = PipelineContext(
            mode=mode,
            project_dir=config.project_dir,
            agents_config=config.agents,
            project_config=config.project,
            board_dir=config.board_dir,
            workspace_dir=config.workspace_dir,
            config_dir=config.config_dir,
            logs_dir=config.logs_dir,
            sprint_num=config.sprint_num,
            cycle_num=config.cycle_num,
            agent_ids=agent_ids,
            verbose=args.verbose,
            dry_run=args.dry_run,
            no_increment=args.no_increment,
        )

        # Build and run pipeline
        pipeline = build_pipeline()
        ctx = pipeline.run(ctx)

        print()
        print("============================================")
        if ctx.errors:
            non_critical = [str(e) for e in ctx.errors]
            print(f"  Completed with {len(non_critical)} warning(s)")
            if args.verbose:
                for e in non_critical:
                    print(f"  - {e}")
        else:
            print("  Completed successfully")
        print("============================================")

    except OrchestratorError as e:
        print(f"\nFATAL: {e}")
        sys.exit(1)
    finally:
        lock.release()
