"""
AI Dev Team — Per-agent pipeline steps.

Replaces the monolithic AgentRunnerStep with individual steps per agent:
  - AgentStep: run a single agent (context → Claude → parse → apply)
  - AgentCommitStep: git commit this agent's changes
  - AgentSyncStep: make changes visible to the next agent (archive inbox)
  - InitStandupStep: initialize standup for the cycle
"""

import subprocess
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia import log
from opensepia.pipeline import PipelineContext
from opensepia.agents.context import build_agent_context_from_adapter
from opensepia.agents.invoker import invoke_agent
from opensepia.agents.parser import parse_files_section
from opensepia.agents.writer import _handle_standup_fallback, _handle_provider_comments
from opensepia.config import DEFAULT_EXECUTION

logger = logging.getLogger(__name__)


class InitStandupStep:
    """Initialize standup file for the cycle."""

    name = "init_standup"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skip_agents or ctx.dry_run:
            return ctx
        ctx.board_adapter.init_standup(ctx.sprint_num, ctx.cycle_num)
        return ctx


class AgentStep:
    """Run a single agent: build context, invoke Claude, parse output, apply changes."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._name = f"run_agent:{agent_id}"

    @property
    def name(self) -> str:
        return self._name

    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skip_agents:
            return ctx

        adapter = ctx.board_adapter
        agent_id = self.agent_id
        agent_cfg = ctx.agents_config["agents"].get(agent_id)

        if not agent_cfg:
            log.warn(f"Agent '{agent_id}' not found in config")
            return ctx

        agent_name = agent_cfg["name"]
        agent_color = agent_cfg["color"]

        if ctx.dry_run:
            agent_ctx = adapter.get_agent_context(agent_id, ctx.agents_config, ctx.project_config)
            context = build_agent_context_from_adapter(agent_id, ctx.agents_config, agent_ctx)
            log.info(f"--- {agent_id} ({len(context)} chars) ---")
            print(context[:1500] + "..." if len(context) > 1500 else context)
            return ctx

        log.progress(agent_name, len(ctx.agent_results) + 1, len(ctx.agent_ids), agent_color)

        # Get execution params with per-agent overrides
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

        standup_file = ctx.board_dir / "standup.md"
        start_time = time.time()
        logger.info("Agent %s (%s) starting — timeout %ds, %d retries",
                     agent_id, agent_name, timeout, max_retries)

        for attempt in range(1 + max_retries):
            try:
                agent_ctx = adapter.get_agent_context(agent_id, ctx.agents_config, ctx.project_config)
                context = build_agent_context_from_adapter(agent_id, ctx.agents_config, agent_ctx)
                logger.info("Agent %s context: %d chars, inbox: %d chars",
                            agent_id, len(context), len(agent_ctx.inbox))

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
                        log.agent_retry(retry_delay)
                        time.sleep(retry_delay)
                        continue
                    else:
                        result_dict["error"] = error_msg
                        elapsed = time.time() - start_time
                        log.agent_error(agent_name, error_msg)
                        ctx.agent_results.append(result_dict)
                        ctx.current_agent_id = agent_id
                        ctx.current_agent_result = result_dict
                        return ctx
                else:
                    if attempt > 0:
                        log.info(f"Retry successful (attempt {attempt + 1})")

                    parsed = parse_files_section(result_dict["response"])
                    files_written = adapter.apply_agent_output(agent_id, parsed, ctx.agents_config)
                    result_dict["files_written"] = files_written

                    _handle_standup_fallback(agent_id, result_dict, parsed, ctx.agents_config, standup_file)
                    _handle_provider_comments(agent_id, parsed)

                    elapsed = time.time() - start_time
                    log.agent_done(agent_name, files_written, elapsed)
                    logger.info("Agent %s done — %d files, %.0fs, %d ctx / %d resp chars",
                                agent_id, files_written, elapsed,
                                agent_result.context_size, agent_result.response_size)

                    ctx.agent_results.append(result_dict)
                    ctx.current_agent_id = agent_id
                    ctx.current_agent_result = result_dict
                    return ctx

            except Exception as e:
                if attempt < max_retries:
                    log.warn(f"Error: {e} — retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    log.error(f"Error: {e} (after {attempt + 1} attempts)")
                    logger.exception("Error for %s", agent_id)
                    result_dict = {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "response": "",
                        "timestamp": datetime.now().isoformat(),
                        "context_size": 0,
                        "response_size": 0,
                        "error": str(e),
                    }
                    ctx.agent_results.append(result_dict)
                    ctx.current_agent_id = agent_id
                    ctx.current_agent_result = result_dict
                    return ctx

        return ctx


class AgentCommitStep:
    """Git commit this agent's workspace changes."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._name = f"commit:{agent_id}"

    @property
    def name(self) -> str:
        return self._name

    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run or ctx.skip_agents:
            return ctx

        workspace = ctx.workspace_dir
        git_dir = workspace / ".git"

        if not git_dir.exists():
            return ctx

        # Get agent display name for commit author
        agent_cfg = ctx.agents_config["agents"].get(self.agent_id, {})
        author_name = agent_cfg.get("name", self.agent_id)
        author_email = f"{self.agent_id}@opensepia.ai"

        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, text=True,
                cwd=str(workspace), timeout=30,
            )

            # Check if there are changes to commit
            diff = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                capture_output=True, text=True,
                cwd=str(workspace), timeout=10,
            )
            if diff.returncode == 0:
                log.step_detail(self._name, "No changes to commit")
                return ctx

            # Commit with agent as author
            msg = f"feat({self.agent_id}): sprint {ctx.sprint_num} cycle {ctx.cycle_num}"
            subprocess.run(
                ["git", "commit", "-m", msg, f"--author={author_name} <{author_email}>"],
                capture_output=True, text=True,
                cwd=str(workspace), timeout=30,
            )

            log.step_detail(self._name, f"Committed as {author_name}")

        except Exception as e:
            log.warn(f"Git commit for {self.agent_id} failed: {e}")

        return ctx


class AgentSyncStep:
    """Make this agent's changes visible to subsequent agents. Archives inbox."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._name = f"sync:{agent_id}"

    @property
    def name(self) -> str:
        return self._name

    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run or ctx.skip_agents:
            return ctx

        adapter = ctx.board_adapter
        adapter.archive_inbox(self.agent_id)

        return ctx
