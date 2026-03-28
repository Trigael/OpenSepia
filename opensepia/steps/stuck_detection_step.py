"""
AI Dev Team — Stuck Story Detection pipeline step.

Runs at the start of each cycle to detect stories that haven't
progressed for too many cycles. Escalates to PO via inbox.
"""

import logging
from opensepia import log
from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class StuckDetectionStep:
    """Detect stuck stories and escalate to PO."""

    name = "stuck_detection"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run or ctx.skip_agents or ctx.board_adapter is None:
            return ctx

        try:
            from opensepia.work_detection import detect_stuck_stories, escalate_stuck_stories

            sprint_text = ctx.board_adapter.get_sprint_text()
            stuck = detect_stuck_stories(sprint_text, ctx.board_dir, ctx.cycle_num)

            if stuck:
                count = escalate_stuck_stories(stuck, ctx.board_dir)
                if count:
                    log.step_detail(
                        "stuck_detection",
                        f"{count} stuck stories escalated to PO",
                    )
                    for s in stuck:
                        log.warn(
                            f"  {s['story_id']} stuck in {s['status'].upper()} "
                            f"for {s['cycles_stuck']} cycles"
                        )
            else:
                log.step_detail("stuck_detection", "No stuck stories")

        except (ImportError, OSError, ValueError) as e:
            logger.warning("Stuck detection error: %s", e)

        return ctx
