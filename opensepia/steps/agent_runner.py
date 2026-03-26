"""
AI Dev Team — Agent runner step.

Runs all agents in sequence, building context, invoking Claude CLI,
parsing output, and applying changes. Handles retry logic.
"""

import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia import log
from opensepia.pipeline import PipelineContext
from opensepia.agents.context import build_agent_context
from opensepia.agents.invoker import invoke_agent
from opensepia.config import DEFAULT_EXECUTION, MAX_STANDUP_CHARS, MAX_INBOX_CHARS
from opensepia.agents.writer import (
    apply_output, read_file_safe, write_file, archive_inbox,
)

logger = logging.getLogger(__name__)


def initialize_standup_file(board_dir: Path, sprint_num: int, cycle: int) -> None:
    """Initialize standup file for a new cycle.

    Archives old standup and keeps last cycle as context,
    removing nested <details> blocks to prevent accumulation.
    """
    standup_file = board_dir / "standup.md"
    old_content = read_file_safe(standup_file)

    if old_content.strip():
        archive_dir = board_dir / "archive" / "standup"
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        write_file(archive_dir / f"s{sprint_num}_c{cycle - 1}_{timestamp}.md", old_content)

        # Keep last cycle as context — without nested <details>
        details_pos = old_content.find("<details>")
        if details_pos > 0:
            clean_content = old_content[:details_pos].strip()
        else:
            clean_content = old_content.strip()

        if len(clean_content) > MAX_INBOX_CHARS:
            clean_content = clean_content[:MAX_INBOX_CHARS] + "\n_(truncated)_"

        prev_section = f"\n\n<details><summary>Previous cycle</summary>\n\n{clean_content}\n</details>\n"
    else:
        prev_section = ""

    header = f"# Standup — Sprint {sprint_num}, Cycle {cycle}\n"
    write_file(standup_file, header + prev_section + "\n")


class AgentRunnerStep:
    """Run agents in sequence with retry logic."""

    name = "agent_runner"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skip_agents:
            logger.info("Skipping agents (sprint ended or dry-run)")
            return ctx

        if ctx.dry_run:
            self._dry_run(ctx)
            return ctx

        # Initialize standup (only if not resuming mid-agent)
        already_completed = set()
        if ctx.cycle_state and ctx.cycle_state.completed_agents:
            already_completed = set(ctx.cycle_state.completed_agents)
            log.info(f"Resuming agents — {len(already_completed)} already done, {len(ctx.agent_ids) - len(already_completed)} remaining")
        else:
            initialize_standup_file(ctx.board_dir, ctx.sprint_num, ctx.cycle_num)

        standup_file = ctx.board_dir / "standup.md"
        state_path = ctx.project_dir / "logs" / "cycle_state.json" if ctx.cycle_state else None

        log.info(f"AI Dev Team — Cycle {ctx.cycle_num}")
        log.detail(f"Mode: {ctx.mode}")
        log.detail(f"Agents: {', '.join(ctx.agent_ids)}")

        results: list[dict[str, Any]] = []
        global_params = ctx.execution_params or {}
        pause_between = global_params.get(
            "pause_between_agents",
            DEFAULT_EXECUTION["pause_between_agents"],
        )

        for i, aid in enumerate(ctx.agent_ids):
            agent_cfg = ctx.agents_config["agents"][aid]
            agent_name = agent_cfg["name"]
            agent_color = agent_cfg["color"]

            # Skip agents that already completed (on resume)
            if aid in already_completed:
                log.step_detail("agent_runner", f"Skipping {agent_name} (already done)")
                continue

            log.progress(agent_name, i + 1, len(ctx.agent_ids), agent_color)

            start_time = time.time()
            result_dict = self._run_single_agent(
                aid, agent_name, agent_color,
                ctx, standup_file,
            )
            elapsed = time.time() - start_time
            results.append(result_dict)

            if result_dict.get("error"):
                log.agent_error(agent_name, result_dict["error"])
            else:
                files_written = result_dict.get("files_written", 0)
                log.agent_done(agent_name, files_written, elapsed)

            # Checkpoint: mark agent as completed
            if ctx.cycle_state and state_path:
                ctx.cycle_state.mark_agent_complete(aid, state_path)

            # Pause between agents (skip after last agent)
            if pause_between > 0 and i < len(ctx.agent_ids) - 1:
                time.sleep(pause_between)

        ctx.agent_results = results
        ctx.agents_ok = all(not r.get("error") for r in results)

        # Cycle summary
        ok_count = sum(1 for r in results if not r.get("error"))
        err_count = sum(1 for r in results if r.get("error"))
        total_files = sum(r.get("files_written", 0) for r in results)
        total_ctx = sum(r.get("context_size", 0) for r in results)
        total_resp = sum(r.get("response_size", 0) for r in results)

        ran_count = len(results)
        skipped = len(already_completed)
        summary = f"Cycle {ctx.cycle_num} — {ok_count}/{ran_count} agents, {total_files} files"
        if skipped:
            summary += f" ({skipped} resumed)"
        log.success(summary)
        if err_count:
            failed = [r["agent_name"] for r in results if r.get("error")]
            log.error(f"Failed: {', '.join(failed)}")
        log.detail(f"Context: {total_ctx:,} chars, Response: {total_resp:,} chars")

        return ctx

    def _run_single_agent(
        self,
        agent_id: str,
        agent_name: str,
        agent_color: str,
        ctx: PipelineContext,
        standup_file: Path,
    ) -> dict[str, Any]:
        """Run a single agent with retry logic."""
        # Get execution params (global merged with per-agent overrides)
        exec_cfg = ctx.agents_config.get("execution", {})
        params = {
            "timeout": exec_cfg.get("timeout", DEFAULT_EXECUTION["timeout"]),
            "max_retries": exec_cfg.get("max_retries", DEFAULT_EXECUTION["max_retries"]),
            "retry_delay": exec_cfg.get("retry_delay", DEFAULT_EXECUTION["retry_delay"]),
        }
        overrides = exec_cfg.get("overrides", {})
        if isinstance(overrides, dict) and agent_id in overrides:
            agent_ov = overrides[agent_id]
            if isinstance(agent_ov, dict):
                params.update(agent_ov)

        max_retries = params["max_retries"]
        retry_delay = params["retry_delay"]
        timeout = params["timeout"]

        for attempt in range(1 + max_retries):
            try:
                context = build_agent_context(
                    agent_id, ctx.agents_config, ctx.project_config,
                    ctx.board_dir, ctx.workspace_dir,
                )

                agent_result = invoke_agent(
                    agent_id=agent_id,
                    context=context,
                    base_dir=ctx.project_dir,
                    agent_name=f"{agent_color} {agent_name}",
                    timeout=timeout,
                    verbose=ctx.verbose,
                )

                result_dict: dict[str, Any] = {
                    "agent_id": agent_result.agent_id,
                    "agent_name": agent_name,
                    "response": agent_result.response,
                    "timestamp": agent_result.timestamp,
                    "context_size": agent_result.context_size,
                    "response_size": agent_result.response_size,
                }

                if agent_result.error or "ERROR" in agent_result.response:
                    error_msg = agent_result.error or agent_result.response[:100]
                    if attempt < max_retries:
                        log.warn(f"{error_msg} — retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        log.error(f"{error_msg} (after {attempt + 1} attempts)")
                        result_dict["error"] = error_msg
                        self._archive_inbox_on_error(agent_id, ctx.board_dir)
                        return result_dict
                else:
                    if attempt > 0:
                        log.info(f"Retry successful (attempt {attempt + 1})")

                    files_written = apply_output(
                        agent_id, result_dict, ctx.agents_config,
                        ctx.project_dir, ctx.board_dir, standup_file,
                        verbose=ctx.verbose,
                    )
                    result_dict["files_written"] = files_written
                    return result_dict

            except Exception as e:
                if attempt < max_retries:
                    log.warn(f"Error: {e} — retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    log.error(f"Error: {e} (after {attempt + 1} attempts)")
                    logger.exception("Error for %s", agent_id)
                    self._archive_inbox_on_error(agent_id, ctx.board_dir)
                    return {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "response": "",
                        "timestamp": datetime.now().isoformat(),
                        "context_size": 0,
                        "response_size": 0,
                        "error": str(e),
                    }

        # Should not reach here, but safety fallback
        return {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "response": "",
            "timestamp": datetime.now().isoformat(),
            "context_size": 0,
            "response_size": 0,
            "error": "max retries exhausted",
        }

    def _archive_inbox_on_error(self, agent_id: str, board_dir: Path) -> None:
        """Archive inbox even when agent fails."""
        inbox_path = board_dir / "inbox" / f"{agent_id}.md"
        inbox_content = read_file_safe(inbox_path)
        if inbox_content.strip():
            archive_inbox(agent_id, inbox_content, board_dir)
            write_file(inbox_path, "")

    def _dry_run(self, ctx: PipelineContext) -> None:
        """Print context for each agent without calling Claude."""
        for aid in ctx.agent_ids:
            context = build_agent_context(
                aid, ctx.agents_config, ctx.project_config,
                ctx.board_dir, ctx.workspace_dir,
            )
            log.step("agent_runner", f"--- {aid} ({len(context)} chars) ---")
            log.info(context[:1500] + "..." if len(context) > 1500 else context)
