"""
AI Dev Team — Orchestrator CLI.

Main entry point that replaces orchestrator_cli.sh.
Builds and runs the pipeline based on the selected mode.

Usage:
    python -m orchestrator [mode] [options]          # single cycle
    python -m orchestrator daemon start [options]     # background daemon
    python -m orchestrator daemon stop/status/pause/resume/logs

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
import signal
import time
import collections
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


# =============================================================================
# Single-cycle execution (original behavior)
# =============================================================================

def run_single_cycle() -> None:
    """Run a single orchestrator cycle. Original CLI behavior."""
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
            "\n"
            "Daemon:\n"
            "  python -m orchestrator daemon start|stop|status|pause|resume|logs\n"
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


# =============================================================================
# Daemon commands
# =============================================================================

def handle_daemon() -> None:
    """Parse and dispatch daemon subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator daemon",
        description="AI Dev Team — Daemon Management",
    )
    sub = parser.add_subparsers(dest="action")

    # start
    start_p = sub.add_parser("start", help="Start the background daemon")
    start_p.add_argument("--mode", "-m", default="dev-team",
                         help="Execution mode (default: dev-team)")
    start_p.add_argument("--pause", "-p", type=int, default=60,
                         help="Seconds between cycles (default: 60)")
    start_p.add_argument("--verbose", "-v", action="store_true",
                         help="Verbose daemon logging")

    # stop
    sub.add_parser("stop", help="Stop the running daemon")

    # status
    sub.add_parser("status", help="Show daemon status")

    # pause
    sub.add_parser("pause", help="Pause the daemon (finish current cycle, then wait)")

    # resume
    sub.add_parser("resume", help="Resume a paused daemon")

    # logs
    logs_p = sub.add_parser("logs", help="View daemon logs")
    logs_p.add_argument("--lines", "-n", type=int, default=50,
                        help="Number of lines to show (default: 50)")
    logs_p.add_argument("--follow", "-f", action="store_true",
                        help="Follow log output (like tail -f)")

    # Parse (skip "daemon" from sys.argv)
    args = parser.parse_args(sys.argv[2:])

    if args.action is None:
        parser.print_help()
        sys.exit(1)

    if args.action == "start":
        daemon_start(args)
    elif args.action == "stop":
        daemon_stop()
    elif args.action == "status":
        daemon_status()
    elif args.action == "pause":
        daemon_pause()
    elif args.action == "resume":
        daemon_resume()
    elif args.action == "logs":
        daemon_logs(args)


def daemon_start(args: argparse.Namespace) -> None:
    """Start the daemon in the background."""
    from orchestrator.daemon import OrchestratorDaemon

    mode = MODE_ALIASES.get(args.mode, args.mode)

    # Validate mode
    try:
        config = OrchestratorConfig.load()
        config.resolve_agent_ids(mode)
    except ConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Starting daemon (mode: {mode}, pause: {args.pause}s)...")

    try:
        daemon = OrchestratorDaemon(
            mode=mode,
            pause=args.pause,
            verbose=args.verbose,
        )
        pid = daemon.start()
        print(f"Daemon started (PID: {pid})")
        print(f"  View status:  python -m orchestrator daemon status")
        print(f"  View logs:    python -m orchestrator daemon logs -f")
        print(f"  Stop:         python -m orchestrator daemon stop")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def daemon_stop() -> None:
    """Stop the running daemon."""
    from orchestrator.daemon import stop_daemon, get_daemon_status

    state = get_daemon_status()
    if state.status in ("stopped", "crashed") or not state.is_process_alive():
        print("Daemon is not running.")
        return

    print(f"Stopping daemon (PID: {state.pid})...")
    stopped = stop_daemon()
    if stopped:
        print("Daemon stopped.")
    else:
        print("Daemon was not running.")


def daemon_status() -> None:
    """Print formatted daemon status."""
    from orchestrator.daemon import get_daemon_status

    state = get_daemon_status()

    status_display = {
        "running": "RUNNING",
        "paused": "PAUSED",
        "stopping": "STOPPING",
        "stopped": "STOPPED",
        "crashed": "CRASHED (stale PID)",
    }

    print()
    print(f"  Status:        {status_display.get(state.status, state.status.upper())}")
    print(f"  PID:           {state.pid or '-'}")
    print(f"  Mode:          {state.mode}")
    print(f"  Pause:         {state.pause_seconds}s between cycles")

    if state.started_at:
        print(f"  Started:       {state.started_at}")
    print(f"  Cycles:        {state.cycle_count}")

    if state.current_step:
        print(f"  Current Step:  {state.current_step}")
        if state.current_cycle_started_at:
            print(f"    Started at:  {state.current_cycle_started_at}")

    if state.last_cycle_finished_at:
        result_icon = {"ok": "+", "error": "!", "skipped": "~", "crash": "X"}.get(
            state.last_cycle_result or "", "?"
        )
        print(f"  Last Cycle:    [{result_icon}] {state.last_cycle_result} at {state.last_cycle_finished_at}")
        if state.last_cycle_errors:
            for err in state.last_cycle_errors[:3]:
                print(f"    - {err[:100]}")

    if state.next_cycle_at:
        print(f"  Next Cycle:    {state.next_cycle_at}")

    if state.paused_at:
        print(f"  Paused since:  {state.paused_at}")

    print()


def daemon_pause() -> None:
    """Pause the running daemon."""
    from orchestrator.daemon import send_pause_signal, get_daemon_status

    state = get_daemon_status()
    if not state.is_process_alive():
        print("Daemon is not running.")
        return
    if state.status == "paused":
        print("Daemon is already paused.")
        return

    try:
        new_status = send_pause_signal()
        print(f"Daemon paused (status: {new_status})")
    except RuntimeError as e:
        print(f"ERROR: {e}")


def daemon_resume() -> None:
    """Resume a paused daemon."""
    from orchestrator.daemon import send_pause_signal, get_daemon_status

    state = get_daemon_status()
    if not state.is_process_alive():
        print("Daemon is not running.")
        return
    if state.status != "paused":
        print(f"Daemon is not paused (status: {state.status}).")
        return

    try:
        new_status = send_pause_signal()
        print(f"Daemon resumed (status: {new_status})")
    except RuntimeError as e:
        print(f"ERROR: {e}")


def daemon_logs(args: argparse.Namespace) -> None:
    """View daemon log file."""
    project_dir = Path(__file__).parent.parent
    log_path = project_dir / "logs" / "daemon.log"

    if not log_path.exists():
        print("No daemon log file found. Has the daemon been started?")
        return

    if args.follow:
        _tail_follow(log_path, args.lines)
    else:
        _tail_lines(log_path, args.lines)


def _tail_lines(path: Path, n: int) -> None:
    """Print last N lines of a file."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = collections.deque(f, maxlen=n)
    for line in lines:
        print(line, end="")


def _tail_follow(path: Path, n: int) -> None:
    """Print last N lines, then follow new output."""
    _tail_lines(path, n)
    print("--- following (Ctrl+C to stop) ---")

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)  # Seek to end
            while True:
                line = f.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n--- stopped ---")


# =============================================================================
# Main entry point
# =============================================================================

def main() -> None:
    """Route to single-cycle or daemon mode."""
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        handle_daemon()
    else:
        run_single_cycle()
