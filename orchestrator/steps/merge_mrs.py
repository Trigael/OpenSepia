"""
AI Dev Team — Auto-merge approved MRs step.

Delegates to scripts/merge_approved_mrs.py.
"""

import subprocess
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
            result = subprocess.run(
                ["python3", "scripts/merge_approved_mrs.py"],
                capture_output=True,
                text=True,
                cwd=str(ctx.project_dir),
                timeout=120,
            )

            if result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    print(f"  {line}")

            if result.returncode != 0:
                logger.warning("Auto-merge returned non-zero: %s", result.stderr[:200])

        except Exception as e:
            logger.warning("Auto-merge failed: %s", e)
            print(f"  Auto-merge failed (non-critical): {e}")

        return ctx
