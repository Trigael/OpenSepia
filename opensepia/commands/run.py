"""Run command and related helpers."""

import os
import sys
import shutil
import argparse
import logging
from datetime import datetime
from pathlib import Path

from opensepia import log
from opensepia.config import OrchestratorConfig, CLI_CHECK_TIMEOUT
from opensepia.errors import OrchestratorError, ConfigError, LockError
from opensepia.lockfile import ProcessLock
from opensepia.pipeline import Pipeline, PipelineContext, Step
from opensepia.steps.board_health import BoardHealthStep, SnapshotStep
from opensepia.steps.sprint_check import SprintCheckStep, SprintSyncStep
from opensepia.steps.agent_step import AgentStep, AgentCommitStep, AgentSyncStep, InitStandupStep
from opensepia.steps.standup_sync import StandupSyncStep
from opensepia.steps.merge_mrs import MergeMRsStep
from opensepia.steps.git_sync import GitSyncStep
from opensepia.steps.board_sync import BoardSyncStep
from opensepia.steps.logging_step import CycleLogStep
from opensepia.steps.alerting import AlertingStep

logger = logging.getLogger(__name__)


# Registry of non-parameterized pipeline steps
STEP_REGISTRY: dict[str, type] = {
    "board_health": BoardHealthStep,
    "sprint_check": SprintCheckStep,
    "snapshot": SnapshotStep,
    "init_standup": InitStandupStep,
    "sprint_sync": SprintSyncStep,
    "standup_sync": StandupSyncStep,
    "merge_mrs": MergeMRsStep,
    "git_sync": GitSyncStep,
    "git_push": GitSyncStep,  # alias for future rename
    "board_sync": BoardSyncStep,
    "cycle_log": CycleLogStep,
    "alerting": AlertingStep,
}

# Registry of parameterized steps (take agent_id as argument)
PARAMETERIZED_REGISTRY: dict[str, type] = {
    "run_agent": AgentStep,
    "commit": AgentCommitStep,
    "sync": AgentSyncStep,
}

# Default step order (used when YAML doesn't specify)
DEFAULT_PIPELINE = [
    "board_health", "sprint_check", "snapshot", "agent_runner",
    "sprint_sync", "standup_sync", "merge_mrs", "git_sync",
    "board_sync", "cycle_log", "alerting",
]


def build_pipeline(agents_config: dict | None = None, agent_ids: list[str] | None = None) -> Pipeline:
    """Construct the pipeline from YAML config or defaults.

    Handles three step formats:
    - Simple step name: "board_health" → STEP_REGISTRY["board_health"]()
    - agent_runner: expands to per-agent triplets (init_standup + run/commit/sync per agent)
    - Parameterized: "run_agent:dev1" → PARAMETERIZED_REGISTRY["run_agent"]("dev1")
    """
    step_names = DEFAULT_PIPELINE

    if agents_config and "pipeline" in agents_config:
        step_names = agents_config["pipeline"]

    if agent_ids is None:
        agent_ids = []

    steps: list[Step] = []
    for entry in step_names:
        if not isinstance(entry, str):
            # Future: handle dict entries like agent_group
            log.warn(f"Unsupported pipeline entry type: {type(entry)} — skipping")
            continue

        name = entry.strip()

        # Special case: agent_runner expands to per-agent steps
        if name == "agent_runner":
            steps.append(InitStandupStep())
            for aid in agent_ids:
                steps.append(AgentStep(aid))
                steps.append(AgentCommitStep(aid))
                steps.append(AgentSyncStep(aid))
            continue

        # Parameterized step: "run_agent:dev1"
        if ":" in name:
            step_type, param = name.split(":", 1)
            cls = PARAMETERIZED_REGISTRY.get(step_type)
            if cls:
                steps.append(cls(param))
            else:
                log.warn(f"Unknown parameterized step '{step_type}' — skipping")
            continue

        # Simple step
        cls = STEP_REGISTRY.get(name)
        if cls:
            steps.append(cls())
        else:
            log.warn(f"Unknown pipeline step '{name}' — skipping")

    return Pipeline(steps=steps)


def check_claude_cli() -> bool:
    """Check if Claude Code CLI is available."""
    return shutil.which("claude") is not None


def check_project_ready(config: OrchestratorConfig) -> list[str]:
    """Check if the project is ready to run. Returns list of issues (empty = ready)."""
    issues = []
    if not config.project_dir.exists():
        issues.append("Project directory does not exist. Run: opensepia init <name>")
        return issues
    if not (config.project_dir / "project.yaml").exists():
        issues.append("No project.yaml found. Run: opensepia init <name>")
        return issues
    board = config.board_dir
    if not board.exists() or not (board / "sprint.md").exists():
        issues.append("Board not initialized. Run: opensepia init <name>")
    workspace = config.workspace_dir
    if not workspace.exists():
        issues.append("Workspace directory missing. Run: opensepia init <name>")
    return issues


def check_workspace_git(config: OrchestratorConfig) -> dict:
    """Check git status of the workspace."""
    workspace = config.workspace_dir
    git_dir = workspace / ".git"
    if not workspace.exists():
        return {"initialized": False, "reason": "workspace missing"}
    if not git_dir.exists():
        return {"initialized": False, "reason": "no git"}
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True, text=True,
            cwd=str(workspace), timeout=CLI_CHECK_TIMEOUT,
        )
        has_remote = bool(result.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        has_remote = False
    repo_url = os.environ.get("GIT_REPO_URL", "")
    return {
        "initialized": True,
        "has_remote": has_remote,
        "repo_url": repo_url,
        "path": str(workspace),
    }


def cmd_run(argv: list[str]) -> None:
    """Run a single orchestrator cycle."""
    parser = argparse.ArgumentParser(prog="opensepia run", description="Run a single cycle")
    parser.add_argument("mode", nargs="?", default="dev-team", help="Execution mode (default: dev-team)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Show context without calling Claude")
    parser.add_argument("--no-increment", action="store_true", help="Don't increment cycle number")
    parser.add_argument("--project", type=str, default=None, help="Project directory path")
    args = parser.parse_args(argv)
    mode = args.mode

    log.init(verbose=args.verbose)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.CRITICAL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    os.environ.pop("CLAUDECODE", None)

    if not check_claude_cli():
        log.warn("Claude Code CLI not in PATH")
        log.info("Install: npm install -g @anthropic-ai/claude-code")

    project_dir = Path(args.project) if args.project else None
    try:
        config = OrchestratorConfig.load(project_dir=project_dir)
    except ConfigError as e:
        log.error(str(e))
        sys.exit(1)

    issues = check_project_ready(config)
    if issues and not args.dry_run:
        for issue in issues:
            log.error(issue)
        sys.exit(1)
    elif issues and args.dry_run:
        for issue in issues:
            log.warn(issue)

    config_warnings = config.validate()
    for w in config_warnings:
        log.warn(w)

    try:
        agent_ids = config.resolve_agent_ids(mode)
    except ConfigError as e:
        log.error(str(e))
        sys.exit(1)

    # Include any active spawned agents from the evolution registry
    spawned = config.get_spawned_agent_ids()
    if spawned:
        agent_ids = agent_ids + [aid for aid in spawned if aid not in agent_ids]

    git_info = check_workspace_git(config)
    git_label = " + git" if git_info["initialized"] else " (no git)"

    log.banner([
        "OpenSepia — Single Cycle",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Mode: {mode} ({len(agent_ids)} agents{git_label})",
    ])

    lock = ProcessLock(mode)
    try:
        lock.acquire()
    except LockError as e:
        log.warn(str(e))
        sys.exit(0)

    try:
        from opensepia.board_adapter import create_board_adapter
        board_adapter = create_board_adapter(
            config.board_dir, config.workspace_dir, config.project_dir,
        )

        ctx = PipelineContext(
            mode=mode,
            tool_dir=config.tool_dir,
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
            execution_params=config.get_execution_params(),
            verbose=args.verbose,
            dry_run=args.dry_run,
            no_increment=args.no_increment,
            board_adapter=board_adapter,
        )

        from opensepia.cycle_state import CycleState, CYCLE_STATE_FILE
        state_path = config.project_dir / CYCLE_STATE_FILE
        loaded_state = CycleState.load(state_path)
        resume_state: CycleState | None = None

        if loaded_state.is_interrupted:
            resume_state = loaded_state
            log.warn(f"Resuming interrupted cycle {resume_state.cycle_id}")
            log.detail(f"Completed: {', '.join(resume_state.completed_steps)}")

        pipeline = build_pipeline(config.agents, agent_ids=agent_ids)
        ctx = pipeline.run(ctx, resume_state=resume_state)

        if ctx.errors:
            log.banner([f"Completed with {len(ctx.errors)} warning(s)"])
            for err in ctx.errors:
                log.detail(f"  - {err}")
        else:
            log.banner(["Completed successfully"])

    except OrchestratorError as e:
        log.error(f"FATAL: {e}")
        sys.exit(1)
    finally:
        lock.release()
