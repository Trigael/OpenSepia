"""
AI Dev Team — Standup sync step.

Posts standup.md content to provider issues.
"""

import logging
from pathlib import Path

from orchestrator.pipeline import PipelineContext
from orchestrator.errors import ProviderError

logger = logging.getLogger(__name__)


class StandupSyncStep:
    """Post standup to provider issues."""

    name = "standup_sync"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        print("  Standup -> provider sync...")

        try:
            from integrations.providers import detect_provider
            from orchestrator.board.comments import post_standup_to_provider

            client = detect_provider()
            if client and client.enabled:
                standup_path = ctx.board_dir / "standup.md"
                posted = post_standup_to_provider(standup_path, client)
                print(f"  Standup: {posted} comments posted to provider")
            else:
                print("  Standup: provider not configured, skipping")

        except Exception as e:
            logger.warning("Standup provider sync failed: %s", e)
            print(f"  Standup sync failed (non-critical): {e}")

        return ctx
