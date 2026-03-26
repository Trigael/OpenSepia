"""
AI Dev Team — Board health check + snapshot + restore step.

Ensures critical board files exist before agents run.
Attempts recovery from snapshots or provider if files are missing.
"""

import shutil
import logging
from pathlib import Path

from opensepia.errors import BoardHealthError
from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)

CRITICAL_FILES = ["sprint.md", "backlog.md"]
SNAPSHOT_FILES = ["sprint.md", "backlog.md", "project.md", "architecture.md", "decisions.md"]


class BoardHealthStep:
    """Check board health, restore if needed, ensure inbox files exist."""

    name = "board_health"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        board_dir = ctx.board_dir

        # Check critical files
        missing = []
        for fname in CRITICAL_FILES:
            fpath = board_dir / fname
            if not fpath.exists() or fpath.stat().st_size == 0:
                missing.append(fname)

        if missing:
            logger.warning("Critical board files missing or empty: %s", ", ".join(missing))
            self._try_restore(ctx, board_dir)

            # Re-check
            still_missing = []
            for fname in missing:
                fpath = board_dir / fname
                if not fpath.exists() or fpath.stat().st_size == 0:
                    still_missing.append(fname)

            if still_missing:
                logger.warning(
                    "Board files still missing after restore: %s. Continuing anyway.",
                    ", ".join(still_missing),
                )

        # Ensure inbox directory and files exist
        inbox_dir = board_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        all_agents = list(ctx.agents_config.get("agents", {}).keys())
        for agent in all_agents:
            inbox_file = inbox_dir / f"{agent}.md"
            if not inbox_file.exists():
                inbox_file.touch()

        return ctx

    def _try_restore(self, ctx: PipelineContext, board_dir: Path) -> None:
        """Attempt restore from snapshot, then from provider."""
        from opensepia.board.restore import restore_from_snapshot, restore_from_provider

        # Try snapshot first
        snapshot_dir = board_dir / ".snapshot"
        if snapshot_dir.exists():
            logger.info("Attempting board restore from snapshot...")
            try:
                restore_from_snapshot(board_dir)
            except Exception as e:
                logger.warning("Snapshot restore failed: %s", e)

        # Re-check and try provider if still missing
        still_missing = False
        for fname in CRITICAL_FILES:
            fpath = board_dir / fname
            if not fpath.exists() or fpath.stat().st_size == 0:
                still_missing = True
                break

        if still_missing:
            logger.info("Snapshot restore insufficient, trying provider...")
            try:
                restore_from_provider(board_dir)
            except Exception as e:
                logger.warning("Provider restore failed: %s", e)


class SnapshotStep:
    """Save board snapshot before agents run."""

    name = "snapshot"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        board_dir = ctx.board_dir
        snapshot_dir = board_dir / ".snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        for fname in SNAPSHOT_FILES:
            src = board_dir / fname
            if src.exists():
                shutil.copy2(src, snapshot_dir / f"{fname}.bak")

        if ctx.verbose:
            print("  Board snapshot: saved to board/.snapshot/")

        return ctx
