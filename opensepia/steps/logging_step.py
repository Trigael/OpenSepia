"""
AI Dev Team — Cycle logging step.

Writes a structured JSON log for each cycle, combining sprint/cycle
metadata with agent-level results.
"""

import os
import json
import logging
from datetime import datetime

from opensepia import log
from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class CycleLogStep:
    """Write JSON cycle log to logs/runs/."""

    name = "cycle_log"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        ctx.logs_dir.mkdir(parents=True, exist_ok=True)

        # Build agent details from results
        agent_details = []
        for r in ctx.agent_results:
            entry: dict = {"agent": r.get("agent_name", r.get("agent_id", "unknown"))}
            if r.get("context_size"):
                entry["context_chars"] = r["context_size"]
            if r.get("response_size"):
                entry["response_chars"] = r["response_size"]
            if r.get("error"):
                entry["error"] = r["error"]
            agent_details.append(entry)

        failed = [a["agent"] for a in agent_details if a.get("error")]
        ok = [a["agent"] for a in agent_details if not a.get("error")]

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": ctx.mode,
            "sprint": ctx.sprint_num,
            "cycle": ctx.cycle_num,
            "agents_ok": ok,
            "agents_failed": failed,
            "agents_ok_count": len(ok),
            "agents_failed_count": len(failed),
            "agents": agent_details,
            "status": "error" if failed else "ok",
            "git_sync": bool(os.environ.get("GIT_REPO_URL", "")),
            "provider_sync": bool(
                os.environ.get("GITLAB_TOKEN", "")
                or os.environ.get("GITHUB_TOKEN", "")
                or os.environ.get("BOARD_SERVER_URL", "")
            ),
        }

        # Write cycle log
        fname = datetime.now().strftime("cycle_%Y%m%d_%H%M%S.json")
        log_path = ctx.logs_dir / fname
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_entry, f, indent=2, ensure_ascii=False)

        log.step_detail("cycle_log", f"Wrote {fname}")

        return ctx
