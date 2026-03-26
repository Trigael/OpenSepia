"""Daemon commands: start, stop, status, pause, resume, logs."""

import sys
import time
import argparse
import collections
from pathlib import Path

from opensepia import log
from opensepia.config import OrchestratorConfig
from opensepia.errors import ConfigError
from opensepia.commands.run import check_project_ready, check_workspace_git


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

    # Check project is ready
    issues = check_project_ready(config)
    if issues:
        for issue in issues:
            log.error(issue)
        sys.exit(1)

    # Config validation warnings
    config_warnings = config.validate()
    for w in config_warnings:
        log.warn(w)

    # Git status hint
    git_info = check_workspace_git(config)
    git_note = ""
    if not git_info["initialized"]:
        git_note = " (git sync disabled — no git repo in workspace)"

    print(f"Starting daemon (mode: {mode}, pause: {args.pause}s{git_note})...")

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

    # Git status
    try:
        config = OrchestratorConfig.load()
        git_info = check_workspace_git(config)
        if git_info["initialized"]:
            remote_str = git_info.get("repo_url", "")
            if git_info.get("has_remote"):
                print(f"  Git:      {remote_str or 'configured'}")
            else:
                print(f"  Git:      initialized (no remote — run: cd project/workspace && git remote add origin <url>)")
        else:
            print(f"  Git:      not set up (optional — run: cd project/workspace && git init)")
    except Exception:
        pass

    print()


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


def cmd_logs(argv: list[str]) -> None:
    """View daemon log file."""
    parser = argparse.ArgumentParser(prog="opensepia logs", description="View daemon logs")
    parser.add_argument("--lines", "-n", type=int, default=50, help="Number of lines (default: 50)")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow log output")
    args = parser.parse_args(argv)

    project_dir = Path(__file__).parent.parent.parent
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
