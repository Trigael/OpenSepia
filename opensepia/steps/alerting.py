"""
AI Dev Team — Alerting step.

Creates alerts on agent failure — writes to local log and
optionally creates a provider issue.
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class AlertingStep:
    """Alert on agent failures via local log and provider issue."""

    name = "alerting"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        failed = [r["agent_name"] for r in ctx.agent_results if r.get("error")]
        if not failed:
            return ctx

        failed_str = ", ".join(failed)
        now = datetime.now()
        alert_msg = f"[AI Dev Team ALERT] Failed agents: {failed_str} ({now}, mode: {ctx.mode})"
        print(f"  ALERT: {alert_msg}")

        # Write to local log
        logs_dir = ctx.project_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        alerts_log = logs_dir / "alerts.log"
        with open(alerts_log, "a", encoding="utf-8") as f:
            f.write(alert_msg + "\n")

        # Create provider issue
        self._create_provider_alert(ctx, failed_str, now)

        return ctx

    def _create_provider_alert(self, ctx: PipelineContext, failed_str: str, now: datetime) -> None:
        """Create an alert issue on the provider."""
        try:
            sys.path.insert(0, str(ctx.project_dir))
            from opensepia.integrations.providers import detect_provider

            client = detect_provider()
            if not client or not client.enabled:
                print("  Provider not configured, local log only")
                return

            title = f"[Alert] Agent failure: {failed_str} ({now.strftime('%Y-%m-%d %H:%M')})"
            body = (
                f"## Agent Failure Alert\n\n"
                f"**Time**: {now.isoformat()}\n"
                f"**Mode**: {ctx.mode}\n"
                f"**Failed**: {failed_str}\n\n"
                f"Check logs in `logs/runs/` for details.\n\n---\n"
                f"*Automatic alert from the AI Dev Team orchestrator.*\n"
            )
            result = client.create_issue(title, body, labels=["alert", "bug"])
            if isinstance(result, dict) and "iid" in result:
                print(f"  Alert issue #{result['iid']} created on provider")
            else:
                print(f"  Alert issue creation returned: {result}")
        except Exception as e:
            logger.warning("Provider alert failed: %s", e)
            print(f"  Provider alert failed (non-critical): {e}")
