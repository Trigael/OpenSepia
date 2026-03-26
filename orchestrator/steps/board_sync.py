"""
AI Dev Team — Board sync step.

Syncs board/backlog.md and board/sprint.md to provider issues.
Delegates to scripts/sync_board.py.
"""

import subprocess
import logging

from orchestrator.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class BoardSyncStep:
    """Sync board state to provider issues."""

    name = "board_sync"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        print("  Board sync...")

        try:
            result = subprocess.run(
                ["python3", "scripts/sync_board.py"],
                capture_output=True,
                text=True,
                cwd=str(ctx.project_dir),
                timeout=120,
            )

            if result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    print(f"  {line}")

            if result.returncode != 0:
                logger.warning("Board sync returned non-zero: %s", result.stderr[:200])

        except Exception as e:
            logger.warning("Board sync failed: %s", e)
            print(f"  Board sync failed (non-critical): {e}")

        return ctx
