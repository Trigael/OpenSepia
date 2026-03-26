"""
AI Dev Team — Sprint check step.

Detects end of sprint, runs retrospective, increments sprint/cycle,
and syncs sprint number from board back to project.yaml.
"""

import re
import logging
import yaml
from pathlib import Path
from typing import Any

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
            print(f"  Sprint completed. Running PO and PM for retrospective.")

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

            if ctx.verbose:
                print(f"  Sprint status: {ctx.cycle_num}/{max_cycles}")

        return ctx

    def _run_retrospective(self, ctx: PipelineContext) -> None:
        """Run PO and PM agents for retrospective (no cycle increment)."""
        import subprocess
        import os

        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        for agent in ["po", "pm"]:
            try:
                result = subprocess.run(
                    ["python3", "scripts/run_agent_cli.py", "--agent", agent, "--verbose", "--no-increment"],
                    capture_output=True,
                    text=True,
                    cwd=str(ctx.project_dir),
                    env=env,
                    timeout=1200,
                )
                if result.returncode != 0:
                    logger.warning("%s retrospective agent failed: %s", agent, result.stderr[:200])
                else:
                    logger.info("%s retrospective completed", agent)
            except Exception as e:
                logger.warning("%s retrospective error: %s", agent, e)

    def _advance_sprint(self, ctx: PipelineContext) -> None:
        """Increment sprint number, reset cycle to 0."""
        sprint_cfg = ctx.project_config.get("sprint", {})
        old_sprint = sprint_cfg.get("current_sprint", 1)

        # Check board for sprint number (agents may have advanced it)
        new_sprint = old_sprint + 1
        sprint_md_path = ctx.board_dir / "sprint.md"
        if sprint_md_path.exists():
            try:
                header = sprint_md_path.read_text(encoding="utf-8").split("\n")[0]
                m = re.search(r"Sprint\s+(\d+)", header)
                if m:
                    board_sprint = int(m.group(1))
                    if board_sprint > old_sprint:
                        new_sprint = board_sprint
            except Exception:
                pass

        sprint_cfg["current_sprint"] = new_sprint
        sprint_cfg["current_cycle"] = 0
        ctx.project_config["sprint"] = sprint_cfg
        ctx.sprint_num = new_sprint
        ctx.cycle_num = 0
        self._save_project(ctx)

        print(f"  Sprint {old_sprint} -> {new_sprint}, cycle reset to 0")

    def _save_project(self, ctx: PipelineContext) -> None:
        """Write project.yaml to disk."""
        with open(ctx.config_dir / "project.yaml", "w") as f:
            yaml.dump(ctx.project_config, f, default_flow_style=False, allow_unicode=True)


class SprintSyncStep:
    """Sync sprint number from board/sprint.md back to project.yaml."""

    name = "sprint_sync"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
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

        if board_sprint != yaml_sprint:
            sprint_cfg["current_sprint"] = board_sprint
            if board_sprint > yaml_sprint:
                sprint_cfg["current_cycle"] = 1
                print(f"   Sprint sync: {yaml_sprint} -> {board_sprint} (cycle reset to 1)")
            else:
                print(f"   Sprint sync: {yaml_sprint} -> {board_sprint}")

            ctx.project_config["sprint"] = sprint_cfg
            ctx.sprint_num = board_sprint
            with open(ctx.config_dir / "project.yaml", "w") as f:
                yaml.dump(ctx.project_config, f, default_flow_style=False, allow_unicode=True)

        return ctx
