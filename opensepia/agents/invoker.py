"""
AI Dev Team — Claude Code CLI invocation with retry logic.

Enforces agent confinement:
- Per-agent tool restrictions (PO/PM can't run Bash)
- Process group cleanup on ALL exit paths (prevents zombie accumulation)
- Two-phase kill: SIGTERM → wait → SIGKILL
- Working directory locked to project_dir
"""

import os
import signal
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia import log
from opensepia.config import DEFAULT_EXECUTION

logger = logging.getLogger(__name__)

AGENT_TIMEOUT_SECONDS = DEFAULT_EXECUTION["timeout"]
DEFAULT_MAX_RETRIES = DEFAULT_EXECUTION["max_retries"]
DEFAULT_RETRY_DELAY = DEFAULT_EXECUTION["retry_delay"]

# Default tools (backward compatible)
DEFAULT_ALLOWED_TOOLS = "Bash,Edit,Write,Read,Glob,Grep"


@dataclass
class AgentResult:
    """Result of a single agent invocation."""
    agent_id: str
    agent_name: str
    response: str
    timestamp: str
    context_size: int
    response_size: int
    error: str | None = None
    attempt: int = 1


def _kill_process_group(pgid: int, grace_period: float = 2.0) -> None:
    """Two-phase kill: SIGTERM the group, wait, then SIGKILL survivors.

    Safe to call even if the group is already dead.
    """
    # Phase 1: SIGTERM
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return  # Already gone

    # Phase 2: Wait for processes to die, then SIGKILL if needed
    deadline = time.monotonic() + grace_period
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)  # Probe: is anything still alive?
        except (ProcessLookupError, OSError):
            return  # All dead
        time.sleep(0.1)

    # Survivors remain — escalate to SIGKILL
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def call_claude_code(
    prompt: str,
    base_dir: Path,
    timeout: int = AGENT_TIMEOUT_SECONDS,
    verbose: bool = False,
    allowed_tools: str = DEFAULT_ALLOWED_TOOLS,
) -> str:
    """Call Claude Code CLI with a prompt.

    Process lifecycle: Popen → communicate → finally: kill entire process group.
    The finally block ensures ALL child processes (pytest, bash, etc.) are
    killed on every exit path: success, timeout, error, or exception.

    Args:
        prompt: Full prompt text to send via stdin.
        base_dir: Working directory for the CLI (locked to project).
        timeout: Timeout in seconds.
        verbose: Print progress to stdout.
        allowed_tools: Comma-separated list of allowed tools.

    Returns:
        Response text from Claude CLI.

    Raises:
        subprocess.TimeoutExpired: If the CLI exceeds the timeout.
        FileNotFoundError: If the claude CLI is not installed.
        RuntimeError: If the CLI returns a non-zero exit code.
    """
    cmd = [
        "claude",
        "--print",
        "--allowedTools", allowed_tools,
    ]

    if verbose:
        log.detail("Calling Claude Code CLI...")

    # Unset CLAUDECODE — otherwise claude CLI refuses to run ("nested session")
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    # Start in new process group so we can kill the entire tree
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(base_dir),
        env=env,
        start_new_session=True,
    )

    # Capture process group ID immediately (before process might exit)
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pgid = None

    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the lead process first (unblocks communicate)
        proc.kill()
        proc.wait()
        raise
    finally:
        # ALWAYS clean up the entire process group — this is the critical fix.
        # Runs on success, timeout, error, and any unexpected exception.
        if pgid is not None:
            _kill_process_group(pgid)
        # Reap the lead process to prevent zombie entry in process table
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    if proc.returncode != 0:
        raise RuntimeError(f"Claude Code CLI error (exit {proc.returncode}): {stderr}")

    return stdout


def invoke_agent(
    agent_id: str,
    context: str,
    base_dir: Path,
    agent_name: str = "",
    timeout: int = AGENT_TIMEOUT_SECONDS,
    verbose: bool = False,
    allowed_tools: str = DEFAULT_ALLOWED_TOOLS,
) -> AgentResult:
    """Invoke Claude Code CLI for a single agent (no retry).

    Args:
        agent_id: Agent identifier.
        context: Full prompt context.
        base_dir: Working directory.
        agent_name: Human-readable agent name.
        timeout: Timeout in seconds.
        verbose: Print progress.
        allowed_tools: Comma-separated list of allowed tools.

    Returns:
        AgentResult with response or error.
    """
    if verbose:
        log.detail("=" * 60)
        log.detail(f"{agent_name or agent_id}")
        log.detail("=" * 60)
        log.detail(f"Context: {len(context)} chars")

    try:
        response = call_claude_code(
            context, base_dir, timeout, verbose,
            allowed_tools=allowed_tools,
        )

        if verbose:
            log.detail(f"Response: {len(response)} chars")

        # Detect empty/near-empty responses (likely rate-limited or failed silently)
        if len(response.strip()) <= 1:
            error_msg = f"Empty response ({len(response.strip())} bytes) — likely rate-limited"
            logger.warning("Agent %s: %s", agent_id, error_msg)
            return AgentResult(
                agent_id=agent_id,
                agent_name=agent_name or agent_id,
                response=f"ERROR: {error_msg}",
                timestamp=datetime.now().isoformat(),
                context_size=len(context),
                response_size=len(response),
                error=error_msg,
            )

        return AgentResult(
            agent_id=agent_id,
            agent_name=agent_name or agent_id,
            response=response,
            timestamp=datetime.now().isoformat(),
            context_size=len(context),
            response_size=len(response),
        )

    except subprocess.TimeoutExpired:
        error_msg = f"Timeout after {timeout}s"
        logger.error("Agent %s: %s", agent_id, error_msg)
        return AgentResult(
            agent_id=agent_id,
            agent_name=agent_name or agent_id,
            response=f"ERROR: {error_msg}",
            timestamp=datetime.now().isoformat(),
            context_size=len(context),
            response_size=0,
            error=error_msg,
        )

    except FileNotFoundError:
        error_msg = "Claude Code CLI is not installed. Run: npm install -g @anthropic-ai/claude-code"
        logger.error(error_msg)
        return AgentResult(
            agent_id=agent_id,
            agent_name=agent_name or agent_id,
            response=f"ERROR: {error_msg}",
            timestamp=datetime.now().isoformat(),
            context_size=len(context),
            response_size=0,
            error=error_msg,
        )

    except (subprocess.SubprocessError, RuntimeError, OSError) as e:
        error_msg = str(e)
        logger.error("Agent %s error: %s", agent_id, error_msg)
        return AgentResult(
            agent_id=agent_id,
            agent_name=agent_name or agent_id,
            response=f"ERROR: {error_msg}",
            timestamp=datetime.now().isoformat(),
            context_size=len(context),
            response_size=0,
            error=error_msg,
        )
