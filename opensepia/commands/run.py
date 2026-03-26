"""Run command and related helpers."""

import os
import sys
import shutil
import argparse
import logging
from datetime import datetime
from pathlib import Path

from opensepia import log
from opensepia.config import OrchestratorConfig
from opensepia.errors import OrchestratorError, ConfigError, LockError
from opensepia.lockfile import ProcessLock
from opensepia.pipeline import Pipeline, PipelineContext
from opensepia.steps.board_health import BoardHealthStep, SnapshotStep
from opensepia.steps.sprint_check import SprintCheckStep, SprintSyncStep
from opensepia.steps.agent_runner import AgentRunnerStep
from opensepia.steps.standup_sync import StandupSyncStep
from opensepia.steps.merge_mrs import MergeMRsStep
from opensepia.steps.git_sync import GitSyncStep
from opensepia.steps.board_sync import BoardSyncStep
from opensepia.steps.logging_step import CycleLogStep
from opensepia.steps.alerting import AlertingStep

logger = logging.getLogger(__name__)


def build_pipeline() -> Pipeline:
    """Construct the full orchestrator pipeline."""
    return Pipeline(steps=[
        BoardHealthStep(),
        SprintCheckStep(),
        SnapshotStep(),
        AgentRunnerStep(),
        SprintSyncStep(),
        StandupSyncStep(),
        MergeMRsStep(),
        GitSyncStep(),
        BoardSyncStep(),
        CycleLogStep(),
        AlertingStep(),
    ])


def check_claude_cli() -> bool:
    """Check if Claude Code CLI is available."""
    return shutil.which("claude") is not None


def check_project_ready(config: OrchestratorConfig) -> list[str]:
    """Check if the project is ready to run. Returns list of issues (empty = ready)."""
    issues = []

    # Check project dir exists
    if not config.project_dir.exists():
        issues.append("Project directory does not exist. Run: opensepia init <name>")
        return issues

    # Check project.yaml
    if not (config.project_dir / "project.yaml").exists():
        issues.append("No project.yaml found. Run: opensepia init <name>")
        return issues

    # Check board files
    board = config.board_dir
    if not board.exists() or not (board / "sprint.md").exists():
        issues.append("Board not initialized. Run: opensepia init <name>")

    # Check workspace
    workspace = config.workspace_dir
    if not workspace.exists():
        issues.append("Workspace directory missing. Run: opensepia init <name>")

    return issues


def check_workspace_git(config: OrchestratorConfig) -> dict:
    """Check git status of the workspace. Returns status dict."""
    workspace = config.workspace_dir
    git_dir = workspace / ".git"

    if not workspace.exists():
        return {"initialized": False, "reason": "workspace missing"}

    if not git_dir.exists():
        return {"initialized": False, "reason": "no git"}

    # Check for remote
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True, text=True,
            cwd=str(workspace), timeout=5,
        )
        has_remote = bool(result.stdout.strip())
    except Exception:
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

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Check project is ready
    issues = check_project_ready(config)
    if issues:
        for issue in issues:
            log.error(issue)
        sys.exit(1)

    # Config validation warnings (non-blocking)
    config_warnings = config.validate()
    for w in config_warnings:
        log.warn(w)

    try:
        agent_ids = config.resolve_agent_ids(mode)
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Git status hint (not an error — git is optional)
    git_info = check_workspace_git(config)
    git_label = ""
    if git_info["initialized"]:
        git_label = " + git"
    else:
        git_label = " (no git)"

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
        )

        pipeline = build_pipeline()
        ctx = pipeline.run(ctx)

        if ctx.errors:
            log.banner([f"Completed with {len(ctx.errors)} warning(s)"])
            for e in ctx.errors:
                log.detail(f"  - {e}")
        else:
            log.banner(["Completed successfully"])

    except OrchestratorError as e:
        log.error(f"FATAL: {e}")
        sys.exit(1)
    finally:
        lock.release()
