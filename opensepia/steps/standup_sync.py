"""
AI Dev Team — Standup sync step.

Posts standup.md content to provider issues.
"""

import logging
from pathlib import Path

from opensepia import log
from opensepia.pipeline import PipelineContext
from opensepia.errors import ProviderError

logger = logging.getLogger(__name__)


class StandupSyncStep:
    """Post standup to provider issues."""

    name = "standup_sync"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        # Skip if using BoardServerAdapter or PlaneBoardAdapter — they handle sync internally
        if ctx.board_adapter:
            from opensepia.board_adapter_server import BoardServerAdapter
            if isinstance(ctx.board_adapter, BoardServerAdapter):
                log.step_detail("standup_sync", "Skipping (board server adapter handles sync)")
                return ctx
            from opensepia.board_adapter_plane import PlaneBoardAdapter
            if isinstance(ctx.board_adapter, PlaneBoardAdapter):
                log.step_detail("standup_sync", "Skipping (Plane adapter handles sync)")
                return ctx

        log.step("standup_sync", "Standup -> provider sync...")

        try:
            from opensepia.integrations.providers import detect_provider
            from opensepia.board.comments import post_standup_to_provider

            client = detect_provider()
            if client and client.enabled:
                standup_path = ctx.board_dir / "standup.md"
                posted = post_standup_to_provider(standup_path, client)
                log.step("standup_sync", f"{posted} comments posted to provider")
            else:
                log.step_detail("standup_sync", "Provider not configured, skipping")

        except (ImportError, OSError, ValueError, KeyError) as e:
            logger.warning("Standup provider sync failed: %s", e)
            log.warn(f"Standup sync failed (non-critical): {e}")

        return ctx
