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

import sys

from opensepia.config import OrchestratorConfig
from opensepia.errors import ConfigError
from opensepia.commands import (
    cmd_run,
    cmd_start,
    cmd_stop,
    cmd_status,
    cmd_pause,
    cmd_resume,
    cmd_logs,
    cmd_init,
    cmd_reset,
    cmd_setup,
    cmd_board,
    cmd_message,
    cmd_config,
    cmd_monitor,
    cmd_history,
    build_pipeline,
)

HELP_TEXT = """\
OpenSepia — AI Dev Team

Usage:
  opensepia <command> [options]

Getting started:
  setup                 Guided first-run wizard
  init <name> [desc]    Initialize a new project

Daemon:
  start [options]       Start the daemon (runs cycles in background)
    --mode MODE         Execution mode (default: dev-team)
    --pause SECS        Seconds between cycles (default: 60)
    --cycles N          Stop after N cycles (default: unlimited)
    --sprints N         Stop after N sprints (default: unlimited)
  stop                  Stop the running daemon
  status                Show current status
  pause / resume        Pause or resume the daemon

Run:
  run [mode]            Run a single cycle, then exit
  run [mode] --dry-run  Preview agent context without calling Claude

Interact:
  board                 Show current sprint board
  message <agent> text  Send a message to an agent
  config                Show editable configuration
  config set <key> val  Change a setting from CLI

Observe:
  logs                  View daemon logs (or --standup, --cycle)
  logs --standup        Show standup from last cycle
  logs --cycle          Show last cycle per-agent detail
  logs -f               Follow daemon log output
  monitor [days]        Show cycle statistics
  history [count]       Show recent cycle history
  history -d            Show with per-agent detail

Manage:
  reset                 Reset project state

Run modes:
  dev-team   6 agents (default)     minimal   3 agents
  all        9 agents               security  3 agents
  <agent>    Single agent (po, pm, dev1, dev2, devops, tester,
             sec_analyst, sec_engineer, sec_pentester)

Examples:
  opensepia setup                        First-time setup
  opensepia start                        Start running
  opensepia board                        Check sprint progress
  opensepia message pm "Focus on API"    Talk to an agent
  opensepia history                      Recent cycles
"""

COMMANDS = {
    "setup": cmd_setup,
    "init": cmd_init,
    "run": cmd_run,
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "logs": cmd_logs,
    "monitor": cmd_monitor,
    "history": cmd_history,
    "board": cmd_board,
    "message": cmd_message,
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
