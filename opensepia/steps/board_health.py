"""
AI Dev Team — Board health check + snapshot + restore step.
"""

import shutil
import logging
from pathlib import Path

from opensepia import log
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

        # Use adapter if available
        if ctx.board_adapter:
            health = ctx.board_adapter.check_board_health()
            unhealthy = [k for k, v in health.items() if not v]
            if unhealthy:
                log.warn(f"Board health issues: {', '.join(unhealthy)}")
                self._try_restore(ctx, board_dir)
            else:
                log.step_detail("board_health", "All board files present")

            ctx.board_adapter.ensure_board_ready()
            return ctx

        # Fallback: direct file checks
        missing = []
        for fname in CRITICAL_FILES:
            fpath = board_dir / fname
            if not fpath.exists() or fpath.stat().st_size == 0:
                missing.append(fname)

        if missing:
            log.warn(f"Board files missing: {', '.join(missing)}")
            self._try_restore(ctx, board_dir)

            still_missing = [f for f in missing
                             if not (board_dir / f).exists() or (board_dir / f).stat().st_size == 0]
            if still_missing:
                log.warn(f"Still missing after restore: {', '.join(still_missing)}")
        else:
            log.step_detail("board_health", "All board files present")

        # Ensure inbox files exist
        all_agents = list(ctx.agents_config.get("agents", {}).keys())
        inbox_dir = board_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        for agent in all_agents:
            inbox_file = inbox_dir / f"{agent}.md"
            if not inbox_file.exists():
                inbox_file.touch()

        return ctx

    def _try_restore(self, ctx: PipelineContext, board_dir: Path) -> None:
        from opensepia.board.restore import restore_from_snapshot, restore_from_provider

        snapshot_dir = board_dir / ".snapshot"
        if snapshot_dir.exists():
            log.step("board_health", "Restoring from snapshot...")
            try:
                restore_from_snapshot(board_dir)
            except Exception as e:
                log.step_detail("board_health", f"Snapshot failed: {e}")

        still_missing = any(
            not (board_dir / f).exists() or (board_dir / f).stat().st_size == 0
            for f in CRITICAL_FILES
        )
        if still_missing:
            log.step("board_health", "Trying provider restore...")
            try:
                restore_from_provider(board_dir)
            except Exception as e:
                log.step_detail("board_health", f"Provider restore failed: {e}")


class SnapshotStep:
    """Save board snapshot before agents run."""

    name = "snapshot"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        # Use adapter if available
        if ctx.board_adapter:
            count = ctx.board_adapter.create_snapshot()
            log.step_detail("snapshot", f"Saved {count} files to .snapshot/")
            return ctx

        # Fallback: direct file copy
        board_dir = ctx.board_dir
        snapshot_dir = board_dir / ".snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for fname in SNAPSHOT_FILES:
            src = board_dir / fname
            if src.exists():
                shutil.copy2(src, snapshot_dir / f"{fname}.bak")
                count += 1

        log.step_detail("snapshot", f"Saved {count} files to .snapshot/")
        return ctx
