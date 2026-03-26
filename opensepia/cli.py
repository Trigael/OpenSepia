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

Commands:
  run [mode]            Run a single cycle, then exit
  start [--mode MODE]   Start the daemon (runs cycles in background)
  stop                  Stop the running daemon
  status                Show current status
  pause                 Pause the daemon after current cycle
  resume                Resume a paused daemon
  logs [-f] [-n N]      View daemon logs

Run modes:
  dev-team              6 agents: PO, PM, Dev1, Dev2, DevOps, Tester (default)
  minimal               3 agents: PO, Dev1, Tester
  all                   All 9 agents
  security              3 agents: Sec Analyst, Engineer, Pentester
  <agent>               Single agent (po, pm, dev1, dev2, devops, tester,
                        sec_analyst, sec_engineer, sec_pentester)

Options:
  run [mode] --dry-run       Show agent context without calling Claude
  run [mode] --no-increment  Don't increment cycle counter
  start --mode MODE          Daemon mode (default: dev-team)
  start --pause SECS         Seconds between cycles (default: 60)
  logs -f                    Follow log output (like tail -f)
  logs -n N                  Show last N lines (default: 50)

Examples:
  opensepia start                        Start with defaults (dev-team, 60s pause)
  opensepia start --mode minimal -p 120  Start minimal mode, 2min between cycles
  opensepia status                       Check what's happening
  opensepia logs -f                      Watch live logs
  opensepia pause                        Pause after current cycle finishes
  opensepia resume                       Resume cycling
  opensepia stop                         Graceful shutdown
  opensepia run po                       Run just the Product Owner agent once
  opensepia run dev-team --dry-run       Preview without calling Claude
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
# Command router
# =============================================================================

COMMANDS = {
    "run": cmd_run,
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "logs": cmd_logs,
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
