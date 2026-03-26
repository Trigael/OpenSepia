"""Daemon commands: start, stop, status, pause, resume."""

import sys
import argparse
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
        log.error(str(e))
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

    log.info(f"Starting daemon (mode: {mode}, pause: {args.pause}s{git_note})...")

    try:
        daemon = OrchestratorDaemon(mode=mode, pause=args.pause, verbose=args.verbose)
        pid = daemon.start()
        log.success(f"Daemon started (PID: {pid})")
        log.info("")
        log.info("opensepia status    Check status")
        log.info("opensepia logs -f   Follow logs")
        log.info("opensepia stop      Stop daemon")
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)


def cmd_stop(argv: list[str]) -> None:
    """Stop the running daemon."""
    from opensepia.daemon import stop_daemon, get_daemon_status

    state = get_daemon_status()
    if state.status in ("stopped", "crashed") or not state.is_process_alive():
        log.info("Daemon is not running.")
        return

    log.info(f"Stopping daemon (PID: {state.pid})...")
    stopped = stop_daemon()
    log.success("Daemon stopped.") if stopped else log.info("Daemon was not running.")


def cmd_status(argv: list[str]) -> None:
    """Show daemon, project, and last cycle status."""
    import json as _json
    import os
    from opensepia.daemon import get_daemon_status

    state = get_daemon_status()

    status_icons = {
        "running": "\u2022 RUNNING",
        "paused": "\u25cb PAUSED",
        "stopping": "~ STOPPING",
        "stopped": "\u25cb STOPPED",
        "crashed": "! CRASHED",
    }

    # Load config
    config = None
    try:
        config = OrchestratorConfig.load()
    except Exception:
        pass

    # --- Daemon ---
    print()
    log.info(f"Daemon:    {status_icons.get(state.status, state.status.upper())}")

    if state.is_process_alive():
        log.info(f"PID:       {state.pid}")
        log.info(f"Mode:      {state.mode}")
        log.info(f"Interval:  every {state.pause_seconds}s")

        if state.started_at:
            log.info(f"Started:   {state.started_at[:19].replace('T', ' ')}")

        log.info(f"Cycles:    {state.cycle_count}")

        if state.current_step:
            log.info(f"Doing:     {state.current_step}")

        if state.last_cycle_result:
            icon = {"ok": "+", "error": "!", "skipped": "~"}.get(state.last_cycle_result, "?")
            finished = (state.last_cycle_finished_at or "")[:19].replace("T", " ")
            log.info(f"Last:      [{icon}] {state.last_cycle_result} ({finished})")

        if state.next_cycle_at:
            log.info(f"Next:      {state.next_cycle_at[:19].replace('T', ' ')}")

        if state.paused_at:
            log.info(f"Paused:    since {state.paused_at[:19].replace('T', ' ')}")

    # --- Project ---
    if config:
        proj = config.project.get("project", {})
        name = proj.get("name", "(not set)")
        log.info(f"Project:   {name}")
        log.info(f"Sprint:    {config.sprint_num}, Cycle {config.cycle_num}")

        # Board summary — count stories by status
        sprint_path = config.board_dir / "sprint.md"
        if sprint_path.exists():
            import re
            content = sprint_path.read_text(encoding="utf-8")
            todo = len(re.findall(r'- \[ \]', content))
            done = len(re.findall(r'- \[x\]', content, re.IGNORECASE))
            in_progress = len(re.findall(r'IN.PROGRESS', content, re.IGNORECASE))
            review = len(re.findall(r'REVIEW', content, re.IGNORECASE))
            if todo or done or in_progress:
                log.info(f"Stories:   {done} done, {in_progress} in progress, {review} review, {todo} todo")

        # Last cycle from log files
        if not state.is_process_alive():
            logs_dir = config.logs_dir
            if logs_dir.exists():
                log_files = sorted(logs_dir.glob("cycle_*.json"), reverse=True)
                if log_files:
                    try:
                        with open(log_files[0], encoding="utf-8") as f:
                            last = _json.load(f)
                        ts = last.get("timestamp", "")
                        if isinstance(ts, str) and "T" in ts:
                            ts = ts[:19].replace("T", " ")
                        status = last.get("status", "?")
                        ok_count = last.get("agents_ok_count", 0)
                        fail_count = last.get("agents_failed_count", 0)
                        mode = last.get("mode", "?")
                        icon = "+" if status == "ok" else "!"
                        log.info(f"Last run:  [{icon}] {mode}, {ok_count} ok, {fail_count} failed ({ts})")
                    except Exception:
                        pass

    # --- Provider ---
    if config:
        board_url = os.environ.get("BOARD_SERVER_URL", "")
        gl = os.environ.get("GITLAB_URL", "")
        gh = os.environ.get("GITHUB_REPO", "")
        if board_url:
            log.info(f"Provider:  Board Server ({board_url})")
        elif gl:
            log.info(f"Provider:  GitLab ({gl})")
        elif gh:
            log.info(f"Provider:  GitHub ({gh})")
        else:
            log.info(f"Provider:  (not configured)")

    # --- Git ---
    if config:
        git_info = check_workspace_git(config)
        if git_info["initialized"]:
            remote = git_info.get("repo_url", "")
            if git_info.get("has_remote"):
                log.info(f"Git:       {remote or 'configured'}")
            else:
                log.info(f"Git:       initialized (no remote)")
        else:
            log.info(f"Git:       not set up")

    print()


def cmd_pause(argv: list[str]) -> None:
    """Pause the running daemon."""
    from opensepia.daemon import send_pause_command, get_daemon_status

    state = get_daemon_status()
    if not state.is_process_alive():
        log.info("Daemon is not running.")
        return
    if state.status == "paused":
        log.info("Daemon is already paused.")
        return

    try:
        send_pause_command(pause=True)
        log.success("Daemon paused. Run 'opensepia resume' to continue.")
    except RuntimeError as e:
        log.error(str(e))


def cmd_resume(argv: list[str]) -> None:
    """Resume a paused daemon."""
    from opensepia.daemon import send_pause_command, get_daemon_status

    state = get_daemon_status()
    if not state.is_process_alive():
        log.info("Daemon is not running.")
        return
    if state.status != "paused":
        log.info(f"Daemon is not paused (status: {state.status}).")
        return

    try:
        send_pause_command(pause=False)
        log.success("Daemon resumed.")
    except RuntimeError as e:
        log.error(str(e))


    # cmd_logs moved to observe.py (now supports --standup, --cycle, not just daemon log)
