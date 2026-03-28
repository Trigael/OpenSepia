"""
AI Dev Team — Evolution pipeline step.

Processes evolution proposals after all agents have run each cycle.
Auto-approves memory/skill writes, queues prompt/spawn/split for review.
Runs over-generalization detection.
"""

import logging
from opensepia import log
from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class EvolutionStep:
    """Process evolution proposals after all agents run.

    Non-critical: failures don't abort the pipeline.
    No-op if evolution is not enabled or evolution directory doesn't exist.
    """

    name = "evolution"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run or ctx.skip_agents:
            return ctx

        # Check if evolution is enabled
        evo_config = ctx.agents_config.get("evolution", {})
        if not evo_config.get("enabled", False):
            return ctx

        evo_dir = ctx.board_dir / "evolution"
        if not evo_dir.exists():
            return ctx

        auto_approve = evo_config.get("auto_approve", {})

        try:
            from opensepia.evolution.proposals import ProposalManager
            pm = ProposalManager(ctx.board_dir, ctx.agents_config)

            # Auto-process proposals based on config
            applied = pm.auto_process(auto_approve)
            if applied:
                log.step_detail("evolution", f"Auto-approved {len(applied)} proposals")

            # Count remaining pending
            pending = pm.get_pending()
            if pending:
                log.step_detail(
                    "evolution",
                    f"{len(pending)} proposals pending human review",
                )

        except (ImportError, OSError, ValueError) as e:
            logger.warning("Evolution step error: %s", e)

        return ctx
