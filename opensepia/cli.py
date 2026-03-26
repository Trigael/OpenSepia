"""
AI Dev Team — Orchestrator CLI.

Entry point for all OpenSepia commands:
  opensepia run [mode]         Run a single cycle
  opensepia start [options]    Start background daemon
  opensepia stop               Stop the daemon
  opensepia status             Show daemon & project status
  opensepia pause              Pause the daemon
  opensepia resume             Resume the daemon
  opensepia logs [-f]          View daemon logs
  opensepia help               Show this help
"""

import os
import sys
import shutil
import argparse
import logging
import time
import collections
from datetime import datetime
from pathlib import Path

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

HELP_TEXT = """\
OpenSepia — AI Dev Team

Usage:
  opensepia <command> [options]

Project:
  init <name> [desc]    Initialize a new project
  reset                 Reset project (clears board, workspace, logs)

Daemon:
  start [--mode MODE]   Start the daemon (runs cycles in background)
  stop                  Stop the running daemon
  status                Show current status
  pause                 Pause the daemon after current cycle
  resume                Resume a paused daemon

Run:
  run [mode]            Run a single cycle, then exit
  run [mode] --dry-run  Preview agent context without calling Claude

Observe:
  logs [-f] [-n N]      View daemon logs
  monitor [days]        Show cycle statistics

Configure:
  config                Show all editable configuration
  config project        Show project settings
  config agents         Show agent modes and execution params
  config env            Show provider integration status

Run modes:
  dev-team              6 agents: PO, PM, Dev1, Dev2, DevOps, Tester (default)
  minimal               3 agents: PO, Dev1, Tester
  all                   All 9 agents
  security              3 agents: Sec Analyst, Engineer, Pentester
  <agent>               Single agent (po, pm, dev1, dev2, devops, tester,
                        sec_analyst, sec_engineer, sec_pentester)

Examples:
  opensepia init "My API" "REST API with FastAPI"
  opensepia start
  opensepia status
  opensepia config
  opensepia run po --dry-run
"""


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


# =============================================================================
# Command: run
# =============================================================================

def cmd_run(argv: list[str]) -> None:
    """Run a single orchestrator cycle."""
    parser = argparse.ArgumentParser(prog="opensepia run", description="Run a single cycle")
    parser.add_argument("mode", nargs="?", default="dev-team", help="Execution mode (default: dev-team)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Show context without calling Claude")
    parser.add_argument("--no-increment", action="store_true", help="Don't increment cycle number")
    args = parser.parse_args(argv)
    mode = args.mode

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    os.environ.pop("CLAUDECODE", None)

    if not check_claude_cli():
        print("  WARNING: Claude Code CLI not in PATH")
        print("  Install: npm install -g @anthropic-ai/claude-code")

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    try:
        agent_ids = config.resolve_agent_ids(mode)
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print()
    print("============================================")
    print("  OpenSepia — Single Cycle")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {mode} ({len(agent_ids)} agents)")
    print("============================================")

    lock = ProcessLock(mode)
    try:
        lock.acquire()
    except LockError as e:
        print(f"  {e}")
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

        print()
        print("============================================")
        if ctx.errors:
            print(f"  Completed with {len(ctx.errors)} warning(s)")
            if args.verbose:
                for e in ctx.errors:
                    print(f"  - {e}")
        else:
            print("  Completed successfully")
        print("============================================")

    except OrchestratorError as e:
        print(f"\nFATAL: {e}")
        sys.exit(1)
    finally:
        lock.release()


# =============================================================================
# Command: start
# =============================================================================

def cmd_start(argv: list[str]) -> None:
    """Start the background daemon."""
    from opensepia.daemon import OrchestratorDaemon

    parser = argparse.ArgumentParser(prog="opensepia start", description="Start background daemon")
    parser.add_argument("--mode", "-m", default="dev-team", help="Execution mode (default: dev-team)")
    parser.add_argument("--pause", "-p", type=int, default=60, help="Seconds between cycles (default: 60)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose daemon logging")
    args = parser.parse_args(argv)

    mode = args.mode

    try:
        config = OrchestratorConfig.load()
        config.resolve_agent_ids(mode)
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Starting daemon (mode: {mode}, pause: {args.pause}s)...")

    try:
        daemon = OrchestratorDaemon(mode=mode, pause=args.pause, verbose=args.verbose)
        pid = daemon.start()
        print(f"Daemon started (PID: {pid})")
        print()
        print(f"  opensepia status    Check status")
        print(f"  opensepia logs -f   Follow logs")
        print(f"  opensepia stop      Stop daemon")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


# =============================================================================
# Command: stop
# =============================================================================

def cmd_stop(argv: list[str]) -> None:
    """Stop the running daemon."""
    from opensepia.daemon import stop_daemon, get_daemon_status

    state = get_daemon_status()
    if state.status in ("stopped", "crashed") or not state.is_process_alive():
        print("Daemon is not running.")
        return

    print(f"Stopping daemon (PID: {state.pid})...")
    stopped = stop_daemon()
    print("Daemon stopped." if stopped else "Daemon was not running.")


# =============================================================================
# Command: status
# =============================================================================

def cmd_status(argv: list[str]) -> None:
    """Show daemon and project status."""
    from opensepia.daemon import get_daemon_status

    state = get_daemon_status()

    status_icons = {
        "running": "\u2022 RUNNING",
        "paused": "\u25cb PAUSED",
        "stopping": "~ STOPPING",
        "stopped": "\u25cb STOPPED",
        "crashed": "! CRASHED",
    }

    # Load project info if available
    sprint_info = ""
    try:
        config = OrchestratorConfig.load()
        sprint_info = f"Sprint {config.sprint_num}, Cycle {config.cycle_num}"
    except Exception:
        pass

    print()
    print(f"  Daemon:   {status_icons.get(state.status, state.status.upper())}")

    if state.is_process_alive():
        print(f"  PID:      {state.pid}")
        print(f"  Mode:     {state.mode}")
        print(f"  Interval: every {state.pause_seconds}s")

        if state.started_at:
            started = state.started_at[:19].replace("T", " ")
            print(f"  Started:  {started}")

        print(f"  Cycles:   {state.cycle_count}")

        if state.current_step:
            print(f"  Doing:    {state.current_step}")

        if state.last_cycle_result:
            icon = {"ok": "+", "error": "!", "skipped": "~"}.get(state.last_cycle_result, "?")
            finished = (state.last_cycle_finished_at or "")[:19].replace("T", " ")
            print(f"  Last:     [{icon}] {state.last_cycle_result} ({finished})")

        if state.last_cycle_errors:
            for err in state.last_cycle_errors[:3]:
                print(f"            - {err[:80]}")

        if state.next_cycle_at:
            next_at = state.next_cycle_at[:19].replace("T", " ")
            print(f"  Next:     {next_at}")

        if state.paused_at:
            paused = state.paused_at[:19].replace("T", " ")
            print(f"  Paused:   since {paused}")

    if sprint_info:
        print(f"  Project:  {sprint_info}")

    print()


# =============================================================================
# Command: pause / resume
# =============================================================================

def cmd_pause(argv: list[str]) -> None:
    """Pause the running daemon."""
    from opensepia.daemon import send_pause_command, get_daemon_status

    state = get_daemon_status()
    if not state.is_process_alive():
        print("Daemon is not running.")
        return
    if state.status == "paused":
        print("Daemon is already paused.")
        return

    try:
        send_pause_command(pause=True)
        print("Daemon paused. Run 'opensepia resume' to continue.")
    except RuntimeError as e:
        print(f"ERROR: {e}")


def cmd_resume(argv: list[str]) -> None:
    """Resume a paused daemon."""
    from opensepia.daemon import send_pause_command, get_daemon_status

    state = get_daemon_status()
    if not state.is_process_alive():
        print("Daemon is not running.")
        return
    if state.status != "paused":
        print(f"Daemon is not paused (status: {state.status}).")
        return

    try:
        send_pause_command(pause=False)
        print("Daemon resumed.")
    except RuntimeError as e:
        print(f"ERROR: {e}")


# =============================================================================
# Command: logs
# =============================================================================

def cmd_logs(argv: list[str]) -> None:
    """View daemon log file."""
    parser = argparse.ArgumentParser(prog="opensepia logs", description="View daemon logs")
    parser.add_argument("--lines", "-n", type=int, default=50, help="Number of lines (default: 50)")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow log output")
    args = parser.parse_args(argv)

    project_dir = Path(__file__).parent.parent
    log_path = project_dir / "logs" / "daemon.log"

    if not log_path.exists():
        print("No daemon log file yet. Start the daemon first:")
        print("  opensepia start")
        return

    if args.follow:
        _tail_follow(log_path, args.lines)
    else:
        _tail_lines(log_path, args.lines)


def _tail_lines(path: Path, n: int) -> None:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = collections.deque(f, maxlen=n)
    for line in lines:
        print(line, end="")


def _tail_follow(path: Path, n: int) -> None:
    _tail_lines(path, n)
    print("--- following (Ctrl+C to stop) ---")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n--- stopped ---")


# =============================================================================
# Command: init
# =============================================================================

def cmd_init(argv: list[str]) -> None:
    """Initialize a new project."""
    import yaml as _yaml

    parser = argparse.ArgumentParser(prog="opensepia init", description="Initialize a new project")
    parser.add_argument("name", help="Project name")
    parser.add_argument("description", nargs="?", default="New project", help="Project description")
    args = parser.parse_args(argv)

    tool_dir = Path(__file__).parent.parent
    project_dir = tool_dir / "project"
    board_dir = project_dir / "board"
    workspace_dir = project_dir / "workspace"

    print(f"Initializing project: {args.name}")

    # Create directories
    for d in ["inbox", "archive", ".snapshot"]:
        (board_dir / d).mkdir(parents=True, exist_ok=True)
    for d in ["src", "tests", "docs", "config"]:
        (workspace_dir / d).mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    (board_dir / "project.md").write_text(
        f"# {args.name}\n\n## Description\n{args.description}\n\n"
        f"## Status\n- **Created**: {now}\n- **Phase**: Initialization\n- **Sprint**: 1\n\n"
        f"## Goals\n- [ ] Define product vision and MVP\n- [ ] Create initial architecture\n"
        f"- [ ] Set up development environment\n- [ ] Implement first feature\n",
        encoding="utf-8",
    )

    (board_dir / "backlog.md").write_text(
        f"# Product Backlog — {args.name}\n\n"
        f"## CRITICAL\n\n## HIGH\n"
        f"### STORY-001: Define MVP scope\n"
        f"**Priority**: HIGH\n**Status**: TODO\n\n"
        f"## MEDIUM\n"
        f"### STORY-002: Set up development environment\n"
        f"**Priority**: MEDIUM\n**Status**: TODO\n\n"
        f"## LOW\n\n## DONE\n",
        encoding="utf-8",
    )

    (board_dir / "sprint.md").write_text(
        f"# Sprint 1 — Initialization\n\n"
        f"**Goal**: Define the project, create a foundation\n"
        f"**Start**: {now}\n\n"
        f"## TODO\n- [ ] STORY-001: Define MVP scope (PO)\n"
        f"- [ ] STORY-002: Set up development environment (DevOps + Dev)\n\n"
        f"## IN PROGRESS\n\n## DONE\n\n## BLOCKED\n",
        encoding="utf-8",
    )

    (board_dir / "architecture.md").write_text(
        f"# Architecture — {args.name}\n\n## Overview\n(To be defined after MVP)\n\n"
        f"## Tech Stack\n(To be decided)\n",
        encoding="utf-8",
    )

    (board_dir / "decisions.md").write_text(
        f"# Decisions (Decision Log)\n\n"
        f"### DEC-001: Project initialization ({datetime.now().strftime('%Y-%m-%d')})\n"
        f"- **Context**: New project {args.name}\n"
        f"- **Decision**: Starting Sprint 1\n- **Who**: System (init)\n",
        encoding="utf-8",
    )

    # Create agent inboxes
    try:
        config = OrchestratorConfig.load()
        agent_ids = config.get_all_agent_ids()
    except ConfigError:
        agent_ids = ["po", "pm", "dev1", "dev2", "devops", "tester",
                     "sec_analyst", "sec_engineer", "sec_pentester"]

    for aid in agent_ids:
        inbox = board_dir / "inbox" / f"{aid}.md"
        if not inbox.exists():
            inbox.write_text("", encoding="utf-8")

    # Seed PO inbox
    (board_dir / "inbox" / "po.md").write_text(
        f"## System message — Initialization\n\n"
        f"Project **{args.name}** has just been created.\n\n"
        f"**Description**: {args.description}\n\n"
        f"### Your first task:\n"
        f"1. Define the product vision\n"
        f"2. Break down the MVP into user stories\n"
        f"3. Prioritize the backlog\n"
        f"4. Send PM instructions for Sprint 1\n",
        encoding="utf-8",
    )

    # Update project.yaml
    project_file = project_dir / "project.yaml"
    if project_file.exists():
        with open(project_file, "r", encoding="utf-8") as f:
            project_cfg = _yaml.safe_load(f) or {}
    else:
        project_cfg = {"project": {}, "sprint": {}, "limits": {}}

    project_cfg.setdefault("project", {})["name"] = args.name
    project_cfg["project"]["description"] = args.description
    project_cfg.setdefault("sprint", {})["current_sprint"] = 1
    project_cfg["sprint"]["current_cycle"] = 0

    with open(project_file, "w", encoding="utf-8") as f:
        _yaml.dump(project_cfg, f, default_flow_style=False, allow_unicode=True)

    print(f"Project initialized!")
    print(f"  Board:     {board_dir}")
    print(f"  Workspace: {workspace_dir}")
    print()
    print(f"Next: opensepia start")


# =============================================================================
# Command: monitor
# =============================================================================

def cmd_monitor(argv: list[str]) -> None:
    """Show cycle statistics."""
    import json as _json
    from collections import defaultdict

    parser = argparse.ArgumentParser(prog="opensepia monitor", description="Cycle statistics")
    parser.add_argument("days", nargs="?", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--last", action="store_true", help="Show only last cycle")
    args = parser.parse_args(argv)

    tool_dir = Path(__file__).parent.parent
    try:
        config = OrchestratorConfig.load()
        logs_dir = config.logs_dir
    except ConfigError:
        logs_dir = tool_dir / "project" / "logs" / "runs"

    if args.last:
        latest = logs_dir / "latest.json"
        if not latest.exists():
            print("No logs yet.")
            return
        with open(latest, encoding="utf-8") as f:
            data = _json.load(f)
        print(f"\n  Last cycle: {data.get('timestamp', '?')}")
        for a in data.get("agents", []):
            ctx = a.get("context_chars", 0)
            resp = a.get("response_chars", 0)
            err = f" [ERROR: {a['error']}]" if a.get("error") else ""
            print(f"    {a['agent']}: {ctx} ctx / {resp} resp{err}")
        print()
        return

    # Summary
    from datetime import timedelta as _td
    cutoff = datetime.now() - _td(days=args.days)
    logs = []
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("*.json")):
            if f.name == "latest.json":
                continue
            try:
                ts = datetime.strptime(f.stem, "%Y%m%d_%H%M%S")
                if ts >= cutoff:
                    with open(f, encoding="utf-8") as fh:
                        data = _json.load(fh)
                    data["_ts"] = ts
                    logs.append(data)
            except (ValueError, _json.JSONDecodeError):
                continue

    if not logs:
        print(f"  No logs for the last {args.days} days.")
        return

    total_ctx = sum(sum(a.get("context_chars", 0) for a in l.get("agents", [])) for l in logs)
    total_resp = sum(sum(a.get("response_chars", 0) for a in l.get("agents", [])) for l in logs)

    daily = defaultdict(lambda: {"cycles": 0, "chars": 0})
    for l in logs:
        day = l["_ts"].strftime("%Y-%m-%d")
        daily[day]["cycles"] += 1
        daily[day]["chars"] += sum(a.get("context_chars", 0) + a.get("response_chars", 0) for a in l.get("agents", []))

    agent_stats = defaultdict(lambda: {"runs": 0, "ctx": 0, "resp": 0})
    for l in logs:
        for a in l.get("agents", []):
            n = a["agent"]
            agent_stats[n]["runs"] += 1
            agent_stats[n]["ctx"] += a.get("context_chars", 0)
            agent_stats[n]["resp"] += a.get("response_chars", 0)

    print(f"\n  Report ({args.days} days)")
    print(f"  {'─' * 40}")
    print(f"  Cycles:  {len(logs)}")
    print(f"  Context: {total_ctx:,} chars")
    print(f"  Output:  {total_resp:,} chars")

    if daily:
        print(f"\n  Daily:")
        for day in sorted(daily):
            d = daily[day]
            print(f"    {day}:  {d['cycles']} cycles, {d['chars']:,} chars")

    if agent_stats:
        print(f"\n  Agents:")
        for name in sorted(agent_stats):
            s = agent_stats[name]
            print(f"    {name:<20} {s['runs']:>3} runs  {s['ctx'] + s['resp']:>10,} chars")
    print()


# =============================================================================
# Command: reset
# =============================================================================

def cmd_reset(argv: list[str]) -> None:
    """Reset project — clears board, workspace, and logs."""
    import shutil as _shutil

    parser = argparse.ArgumentParser(prog="opensepia reset", description="Reset project")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    args = parser.parse_args(argv)

    tool_dir = Path(__file__).parent.parent
    project_dir = tool_dir / "project"

    if not args.yes:
        print("This will delete:")
        print(f"  - {project_dir / 'board'}/ (sprint, backlog, inbox)")
        print(f"  - {project_dir / 'workspace' / 'src'}/")
        print(f"  - {project_dir / 'logs'}/")
        print()
        confirm = input("Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return

    # Stop daemon if running
    try:
        from opensepia.daemon import stop_daemon, get_daemon_status
        state = get_daemon_status()
        if state.is_process_alive():
            print("Stopping daemon...")
            stop_daemon()
    except Exception:
        pass

    board = project_dir / "board"
    if board.exists():
        _shutil.rmtree(board)
    for d in ["inbox", "archive", ".snapshot"]:
        (board / d).mkdir(parents=True, exist_ok=True)
    print("  Board cleared")

    workspace_src = project_dir / "workspace" / "src"
    if workspace_src.exists():
        _shutil.rmtree(workspace_src)
    workspace_src.mkdir(parents=True, exist_ok=True)
    (workspace_src / ".gitkeep").touch()
    print("  Workspace cleared")

    logs = project_dir / "logs"
    if logs.exists():
        _shutil.rmtree(logs)
    logs.mkdir(parents=True, exist_ok=True)
    print("  Logs cleared")

    print()
    print("Reset complete. Run 'opensepia init <name>' to start a new project.")


# =============================================================================
# Command: config
# =============================================================================

def cmd_config(argv: list[str]) -> None:
    """Show editable configuration."""
    import os

    section = argv[0] if argv else "all"

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return

    tool_dir = config.tool_dir
    project_dir = config.project_dir

    if section in ("all", "project"):
        proj = config.project.get("project", {})
        sprint = config.project.get("sprint", {})

        print()
        print("  Project Settings")
        print(f"  {'─' * 50}")
        print(f"  Name:         {proj.get('name', '(not set)')}")
        print(f"  Description:  {proj.get('description', '(not set)')}")

        tech = proj.get("tech_stack", {})
        if tech:
            print(f"  Tech stack:   {tech.get('language', '-')} / {tech.get('framework', '-')}")
            print(f"                {tech.get('database', '-')} / {tech.get('deployment', '-')}")

        print(f"  Sprint:       {sprint.get('current_sprint', 1)}")
        print(f"  Cycle:        {sprint.get('current_cycle', 0)}")
        print(f"  Cycles/sprint:{sprint.get('cycles_per_sprint', 10)}")
        print(f"  Edit:         {project_dir / 'project.yaml'}")

    if section in ("all", "agents"):
        modes = config.agents.get("modes", {})
        exec_cfg = config.agents.get("execution", {})

        print()
        print("  Agent Modes")
        print(f"  {'─' * 50}")
        for name, defn in modes.items():
            agents = defn.get("agents", [])
            aliases = defn.get("aliases", [])
            default = " (default)" if defn.get("default") else ""
            alias_str = f" (alias: {', '.join(aliases)})" if aliases else ""
            print(f"  {name:<14} {len(agents)} agents{default}{alias_str}")
            print(f"                 {', '.join(agents)}")

        print()
        print("  Execution Parameters")
        print(f"  {'─' * 50}")
        print(f"  Timeout:         {exec_cfg.get('timeout', 900)}s per agent")
        print(f"  Max retries:     {exec_cfg.get('max_retries', 1)}")
        print(f"  Retry delay:     {exec_cfg.get('retry_delay', 30)}s")
        print(f"  Pause between:   {exec_cfg.get('pause_between_agents', 0)}s")

        overrides = exec_cfg.get("overrides", {})
        if overrides and isinstance(overrides, dict) and any(overrides.values()):
            print(f"  Per-agent:")
            for aid, ov in overrides.items():
                if isinstance(ov, dict) and ov:
                    print(f"    {aid}: {ov}")

        print(f"  Edit:            {tool_dir / 'config' / 'agents.yaml'}")

    if section in ("all", "env"):
        print()
        print("  Provider Integration")
        print(f"  {'─' * 50}")

        gl_url = os.environ.get("GITLAB_URL", "")
        gl_token = os.environ.get("GITLAB_TOKEN", "")
        gl_project = os.environ.get("GITLAB_PROJECT_ID", "")
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        gh_owner = os.environ.get("GITHUB_OWNER", "")
        gh_repo = os.environ.get("GITHUB_REPO", "")
        git_url = os.environ.get("GIT_REPO_URL", "")

        if gl_url and gl_token:
            print(f"  GitLab:       {gl_url}")
            print(f"  Project:      {gl_project}")
            print(f"  Token:        {'*' * 8}...{gl_token[-4:]}" if len(gl_token) > 4 else "  Token:        (set)")
        elif gh_token and gh_repo:
            print(f"  GitHub:       {gh_owner}/{gh_repo}")
            print(f"  Token:        {'*' * 8}...{gh_token[-4:]}" if len(gh_token) > 4 else "  Token:        (set)")
        else:
            print(f"  Provider:     (not configured)")
            print(f"  Set GitLab or GitHub credentials in config/.env")

        if git_url:
            print(f"  Git repo:     {git_url}")
        else:
            print(f"  Git repo:     (not configured)")

        print(f"  Edit:         {tool_dir / 'config' / '.env'}")

    if section not in ("all", "project", "agents", "env"):
        print(f"Unknown config section: {section}")
        print(f"Valid: project, agents, env (or no argument for all)")
        return

    print()
    print(f"  Editable files:")
    print(f"    {str(project_dir / 'project.yaml'):<50} Project name, tech stack, sprint")
    print(f"    {str(tool_dir / 'config' / 'agents.yaml'):<50} Modes, execution params, agent prompts")
    print(f"    {str(tool_dir / 'config' / '.env'):<50} Provider tokens (GitLab/GitHub)")
    print()


# =============================================================================
# Command router
# =============================================================================

COMMANDS = {
    "init": cmd_init,
    "run": cmd_run,
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "logs": cmd_logs,
    "monitor": cmd_monitor,
    "reset": cmd_reset,
    "config": cmd_config,
    # Legacy: "daemon" subcommand still works
    "daemon": None,
}


def _handle_legacy_daemon(argv: list[str]) -> None:
    """Handle 'opensepia daemon <action>' by mapping to top-level commands."""
    if not argv:
        print(HELP_TEXT)
        return
    action = argv[0]
    rest = argv[1:]
    handler = COMMANDS.get(action)
    if handler:
        handler(rest)
    else:
        print(f"Unknown daemon action: {action}")
        print(HELP_TEXT)
        sys.exit(1)


def main() -> None:
    """Main entry point — route to the appropriate command."""
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        print(HELP_TEXT)
        return

    command = sys.argv[1]
    rest = sys.argv[2:]

    # Legacy: "daemon" subcommand maps actions to top-level commands
    if command == "daemon":
        _handle_legacy_daemon(rest)
        return

    handler = COMMANDS.get(command)
    if handler:
        handler(rest)
        return

    # If the argument looks like a mode name, treat as "run <mode>"
    try:
        config = OrchestratorConfig.load()
        all_modes = config.get_all_mode_names()
    except ConfigError:
        all_modes = set()
    if command in all_modes:
        cmd_run([command] + rest)
        return

    print(f"Unknown command: {command}")
    print()
    print(HELP_TEXT)
    sys.exit(1)
