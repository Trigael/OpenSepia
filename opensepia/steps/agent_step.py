"""
AI Dev Team — Per-agent pipeline steps.

Replaces the monolithic AgentRunnerStep with individual steps per agent:
  - AgentStep: run a single agent (context → Claude → parse → apply)
  - AgentCommitStep: git commit this agent's changes on a story branch
  - AgentSyncStep: make changes visible, archive inbox, merge DONE story branches
  - InitStandupStep: initialize standup for the cycle
"""

import re
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
                        logger.warning("Agent %s failed: %s (%.0fs)", agent_id, error_msg, elapsed)
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


# =============================================================================
# Git helpers
# =============================================================================

def _git(workspace: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a git command in the workspace."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True,
        cwd=str(workspace), timeout=30,
    )


def _extract_story_id(result: dict | None) -> str | None:
    """Extract the primary story ID from an agent's result/response.

    Looks for STORY-XXX or BUG-XXX references. Returns the first one found,
    or None if no story referenced.
    """
    if not result:
        return None
    response = result.get("response", "")
    refs = re.findall(r'((?:STORY|BUG)-\d+)', response)
    return refs[0] if refs else None


def _story_branch_name(story_id: str) -> str:
    """Convert STORY-001 to story/story-001 branch name."""
    return f"story/{story_id.lower()}"


# =============================================================================
# AgentCommitStep — per-story branch commits
# =============================================================================

class AgentCommitStep:
    """Git commit this agent's workspace changes on a story branch.

    If the agent worked on a specific story, creates/switches to a
    story branch before committing. Falls back to master if no story detected.
    """

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
        if not (workspace / ".git").exists():
            return ctx

        agent_cfg = ctx.agents_config["agents"].get(self.agent_id, {})
        author_name = agent_cfg.get("name", self.agent_id)
        author_email = f"{self.agent_id}@opensepia.ai"

        try:
            # Check if there are unstaged changes (don't stage yet — may need to switch branch)
            status = _git(workspace, "status", "--porcelain")
            if not status.stdout.strip():
                log.step_detail(self._name, "No changes to commit")
                return ctx

            # Detect story from agent's result
            story_id = _extract_story_id(ctx.current_agent_result)
            branch = None

            if story_id:
                branch = _story_branch_name(story_id)

                # Switch to story branch BEFORE staging (avoids conflicts with staged files)
                existing = _git(workspace, "branch", "--list", branch)
                if branch in existing.stdout:
                    result = _git(workspace, "checkout", branch)
                    if result.returncode != 0:
                        logger.warning("Checkout %s failed: %s — merging master into branch",
                                       branch, result.stderr.strip())
                        # Branch exists but checkout fails due to conflicts.
                        # Stash, checkout, pop.
                        _git(workspace, "stash", "--include-untracked")
                        _git(workspace, "checkout", branch)
                        # Merge master to keep branch up to date
                        _git(workspace, "merge", "master", "--no-edit")
                        pop = _git(workspace, "stash", "pop")
                        if pop.returncode != 0:
                            # Stash pop conflict — accept working tree version
                            _git(workspace, "checkout", "--theirs", ".")
                            _git(workspace, "stash", "drop")
                else:
                    _git(workspace, "checkout", "-b", branch)

            # Stage all changes on the correct branch
            _git(workspace, "add", "-A")

            # Commit
            msg = f"feat({self.agent_id}): sprint {ctx.sprint_num} cycle {ctx.cycle_num}"
            if story_id:
                msg = f"feat({self.agent_id}): {story_id} (s{ctx.sprint_num}c{ctx.cycle_num})"

            _git(workspace, "commit", "-m", msg, f"--author={author_name} <{author_email}>")

            if branch:
                log.step_detail(self._name, f"Committed to {branch} as {author_name}")
                # Return to master
                _git(workspace, "checkout", "master")
            else:
                log.step_detail(self._name, f"Committed to master as {author_name}")

        except Exception as e:
            log.warn(f"Git commit for {self.agent_id} failed: {e}")
            # Ensure we're back on master
            _git(workspace, "checkout", "master")

        return ctx


# =============================================================================
# AgentSyncStep — archive inbox + merge DONE story branches
# =============================================================================

class AgentSyncStep:
    """Make changes visible to next agent. Archive inbox. Merge DONE story branches."""

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

        # Check for stories that moved to DONE and merge their branches
        self._merge_done_stories(ctx)

        return ctx

    def _merge_done_stories(self, ctx: PipelineContext) -> None:
        """If any stories moved to DONE, merge their story branches to master."""
        workspace = ctx.workspace_dir
        if not (workspace / ".git").exists():
            return

        # Get list of story branches
        result = _git(workspace, "branch", "--list", "story/*")
        if not result.stdout.strip():
            return

        branches = [b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()]

        # Check which stories are DONE (from board adapter)
        try:
            summary = ctx.board_adapter.get_board_summary()
        except Exception:
            return

        # Get sprint text to find DONE stories
        try:
            sprint_text = ctx.board_adapter.get_sprint_text()
        except Exception:
            return

        done_ids = set()
        in_done_section = False
        for line in sprint_text.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("## "):
                in_done_section = "done" in stripped
            elif in_done_section:
                refs = re.findall(r'((?:STORY|BUG)-\d+)', line, re.IGNORECASE)
                done_ids.update(r.upper() for r in refs)

        # Merge branches for DONE stories
        for branch in branches:
            # Extract story ID from branch name: story/story-001 → STORY-001
            match = re.search(r'story/((?:story|bug)-\d+)', branch)
            if not match:
                continue
            story_id = match.group(1).upper()

            if story_id in done_ids:
                # Merge to master
                _git(workspace, "checkout", "master")
                result = _git(workspace, "merge", branch, "--no-ff",
                              "-m", f"Merge {story_id}: completed")
                if result.returncode == 0:
                    # Delete the story branch
                    _git(workspace, "branch", "-d", branch)
                    logger.info("Merged story branch %s to master", branch)
                    log.step_detail(self._name, f"Merged {branch} to master")
                else:
                    logger.warning("Failed to merge %s: %s", branch, result.stderr[:100])
                    # Ensure we're back on master
                    _git(workspace, "merge", "--abort")
                    _git(workspace, "checkout", "master")
