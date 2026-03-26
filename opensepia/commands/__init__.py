"""Command modules for OpenSepia CLI."""

from opensepia.commands.run import (
    cmd_run,
    build_pipeline,
    check_project_ready,
    check_workspace_git,
    check_claude_cli,
)
from opensepia.commands.daemon import (
    cmd_start,
    cmd_stop,
    cmd_status,
    cmd_pause,
    cmd_resume,
)
from opensepia.commands.project import (
    cmd_init,
    cmd_reset,
    cmd_setup,
)
from opensepia.commands.interact import (
    cmd_board,
    cmd_message,
    cmd_config,
)
from opensepia.commands.observe import (
    cmd_logs,
    cmd_monitor,
    cmd_history,
)

__all__ = [
    "cmd_run",
    "build_pipeline",
    "check_project_ready",
    "check_workspace_git",
    "check_claude_cli",
    "cmd_start",
    "cmd_stop",
    "cmd_status",
    "cmd_pause",
    "cmd_resume",
    "cmd_logs",
    "cmd_init",
    "cmd_reset",
    "cmd_setup",
    "cmd_board",
    "cmd_message",
    "cmd_config",
    "cmd_monitor",
    "cmd_history",
]
