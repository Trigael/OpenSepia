"""
AI Dev Team — Auto-merge approved MRs step.
"""

import logging

from orchestrator.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class MergeMRsStep:
    """Auto-merge approved MRs and close stale ones."""

    name = "merge_mrs"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        print("  Auto-merge approved MRs...")

        try:
            from integrations.providers import detect_provider
            from scripts.merge_approved_mrs import merge_approved_mrs

            client = detect_provider()
            if not client or not client.enabled:
                print("  Auto-merge: no provider configured, skipping")
                return ctx

            merged, closed = merge_approved_mrs(client)
            if merged or closed:
                print(f"  Auto-merge: {merged} merged, {closed} closed")

        except Exception as e:
            logger.warning("Auto-merge failed: %s", e)
            print(f"  Auto-merge failed (non-critical): {e}")

        return ctx
