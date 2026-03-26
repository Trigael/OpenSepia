"""
AI Dev Team — Board sync step.

Syncs board/backlog.md and board/sprint.md to provider issues.
"""

import logging

from opensepia.pipeline import PipelineContext

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
            from opensepia.integrations.providers import detect_provider
            from opensepia.board.sync import parse_backlog, parse_sprint_statuses, sync_to_provider

            provider = detect_provider()
            if not provider or not provider.enabled:
                print("  Board sync: no provider configured, skipping")
                return ctx

            backlog_path = ctx.board_dir / "backlog.md"
            sprint_path = ctx.board_dir / "sprint.md"

            if not backlog_path.exists():
                logger.warning("backlog.md does not exist, skipping board sync")
                return ctx

            items = parse_backlog(backlog_path)
            sprint_statuses = {}
            if sprint_path.exists():
                sprint_statuses = parse_sprint_statuses(sprint_path)

            created, updated = sync_to_provider(items, sprint_statuses, provider, ctx.board_dir)
            print(f"  Board sync: {created} created, {updated} updated")

        except Exception as e:
            logger.warning("Board sync failed: %s", e)
            print(f"  Board sync failed (non-critical): {e}")

        return ctx
