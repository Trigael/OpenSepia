"""
AI Dev Team — Sprint check step.

Detects end of sprint, runs retrospective, increments sprint/cycle,
and syncs sprint number from board back to project.yaml.
"""

import re
import logging
import subprocess
import yaml
from pathlib import Path
from typing import Any

from opensepia import log
from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class SprintCheckStep:
    """Check if sprint has ended. If so, run retrospective and advance sprint."""

    name = "sprint_check"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        sprint_cfg = ctx.project_config.get("sprint", {})
        cycle = sprint_cfg.get("current_cycle", 0)
        max_cycles = sprint_cfg.get("cycles_per_sprint", 10)

        if cycle >= max_cycles:
            logger.info("Sprint completed (cycle %d/%d). Running retrospective.", cycle, max_cycles)
            log.step("sprint_check", "Sprint completed. Running PO and PM for retrospective.")

            self._run_retrospective(ctx)
            self._advance_sprint(ctx)
            ctx.skip_agents = True
        else:
            # Increment cycle for this run
            if not ctx.no_increment and not ctx.dry_run:
                new_cycle = cycle + 1
                sprint_cfg["current_cycle"] = new_cycle
                ctx.cycle_num = new_cycle
                ctx.project_config["sprint"] = sprint_cfg
                self._save_project(ctx)
            else:
                ctx.cycle_num = cycle

            log.step_detail("sprint_check", f"Sprint status: {ctx.cycle_num}/{max_cycles}")

        return ctx

    def _run_retrospective(self, ctx: PipelineContext) -> None:
        """Run PO and PM agents for retrospective (no cycle increment)."""
        from opensepia.agents.context import build_agent_context_from_adapter
        from opensepia.agents.invoker import invoke_agent
        from opensepia.agents.parser import parse_files_section
        from opensepia.agents.writer import _handle_standup_fallback, _handle_provider_comments

        if ctx.board_adapter is None:
            return
        adapter = ctx.board_adapter
        standup_file = ctx.board_dir / "standup.md"

        retro_agents = ctx.agents_config.get("global", {}).get(
            "retrospective_agents", ["po", "pm"],
        )
        for agent_id in retro_agents:
            try:
                agent_cfg = ctx.agents_config["agents"].get(agent_id)
                if not agent_cfg:
                    continue

                agent_ctx = adapter.get_agent_context(agent_id, ctx.agents_config, ctx.project_config)
                context = build_agent_context_from_adapter(
                    agent_id, ctx.agents_config, agent_ctx,
                )
                result = invoke_agent(
                    agent_id=agent_id,
                    context=context,
                    base_dir=ctx.project_dir,
                    agent_name=agent_cfg.get("name", agent_id),
                    verbose=ctx.verbose,
                )

                if not result.error:
                    result_dict = {
                        "agent_id": result.agent_id,
                        "agent_name": result.agent_name,
                        "response": result.response,
                        "timestamp": result.timestamp,
                        "context_size": result.context_size,
                        "response_size": result.response_size,
                    }
                    parsed = parse_files_section(result.response)
                    adapter.apply_agent_output(agent_id, parsed, ctx.agents_config)
                    _handle_standup_fallback(agent_id, result_dict, parsed, ctx.agents_config, standup_file)
                    _handle_provider_comments(agent_id, parsed)
                    adapter.archive_inbox(agent_id)
                    logger.info("%s retrospective completed", agent_id)
                else:
                    logger.warning("%s retrospective failed: %s", agent_id, result.error)
            except (subprocess.SubprocessError, OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("%s retrospective error: %s", agent_id, e)

    def _advance_sprint(self, ctx: PipelineContext) -> None:
        """Increment sprint number, reset cycle to 0."""
        sprint_cfg = ctx.project_config.get("sprint", {})
        old_sprint = sprint_cfg.get("current_sprint", 1)

        # Check board for sprint number (agents may have advanced it)
        new_sprint = old_sprint + 1
        if ctx.board_adapter:
            board_sprint = ctx.board_adapter.get_sprint_number()
            if board_sprint > old_sprint:
                new_sprint = board_sprint
        else:
            sprint_md_path = ctx.board_dir / "sprint.md"
            if sprint_md_path.exists():
                try:
                    header = sprint_md_path.read_text(encoding="utf-8").split("\n")[0]
                    m = re.search(r"Sprint\s+(\d+)", header)
                    if m:
                        board_sprint = int(m.group(1))
                        if board_sprint > old_sprint:
                            new_sprint = board_sprint
                except (OSError, ValueError):
                    logger.debug("Could not parse sprint number from board file", exc_info=True)

        sprint_cfg["current_sprint"] = new_sprint
        sprint_cfg["current_cycle"] = 0
        ctx.project_config["sprint"] = sprint_cfg
        ctx.sprint_num = new_sprint
        ctx.cycle_num = 0
        self._save_project(ctx)

        log.step("sprint_check", f"Sprint {old_sprint} -> {new_sprint}, cycle reset to 0")

    def _save_project(self, ctx: PipelineContext) -> None:
        """Write project.yaml to disk."""
        with open(ctx.project_dir / "project.yaml", "w", encoding="utf-8") as f:
            yaml.dump(ctx.project_config, f, default_flow_style=False, allow_unicode=True)


class SprintSyncStep:
    """Sync sprint number from board/sprint.md back to project.yaml."""

    name = "sprint_sync"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.board_adapter:
            board_sprint = ctx.board_adapter.get_sprint_number()
        else:
            sprint_md_path = ctx.board_dir / "sprint.md"
            if not sprint_md_path.exists():
                return ctx

            content = sprint_md_path.read_text(encoding="utf-8")
            all_sprints = re.findall(r"#\s*Sprint\s+(\d+)", content)
            if not all_sprints:
                return ctx

            board_sprint = max(int(s) for s in all_sprints)
        sprint_cfg = ctx.project_config.get("sprint", {})
        yaml_sprint = sprint_cfg.get("current_sprint", 1)

        # Only advance forward — never let the board pull the sprint number backward
        # (agents may write "Sprint 1" in their markdown even after the system advanced to Sprint 2)
        if board_sprint > yaml_sprint:
            sprint_cfg["current_sprint"] = board_sprint
            sprint_cfg["current_cycle"] = 1
            ctx.project_config["sprint"] = sprint_cfg
            ctx.sprint_num = board_sprint
            with open(ctx.project_dir / "project.yaml", "w", encoding="utf-8") as f:
                yaml.dump(ctx.project_config, f, default_flow_style=False, allow_unicode=True)
            log.step("sprint_sync", f"Sprint sync: {yaml_sprint} -> {board_sprint} (cycle reset to 1)")

        return ctx
