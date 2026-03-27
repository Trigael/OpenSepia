"""
AI Dev Team — Auto-merge approved MRs step.
"""

import logging

from opensepia import log
from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class MergeMRsStep:
    """Auto-merge approved MRs and close stale ones."""

    name = "merge_mrs"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        # Skip if using BoardServerAdapter
        if ctx.board_adapter:
            from opensepia.board_adapter_server import BoardServerAdapter
            if isinstance(ctx.board_adapter, BoardServerAdapter):
                log.step_detail("merge_mrs", "Skipping (board server adapter handles MRs)")
                return ctx

        log.step("merge_mrs", "Auto-merge approved MRs...")

        try:
            from opensepia.integrations.providers import detect_provider
            from opensepia.board.merge import merge_approved_mrs

            client = detect_provider()
            if not client or not client.enabled:
                log.step_detail("merge_mrs", "No provider configured, skipping")
                return ctx

            merged, closed = merge_approved_mrs(client)
            if merged or closed:
                log.step("merge_mrs", f"{merged} merged, {closed} closed")

        except (ImportError, OSError, ValueError, KeyError) as e:
            logger.warning("Auto-merge failed: %s", e)
            log.warn(f"Auto-merge failed (non-critical): {e}")

        return ctx
