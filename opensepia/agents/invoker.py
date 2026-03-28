"""
AI Dev Team — Claude Code CLI invocation with retry logic.

Enforces agent confinement:
- Per-agent tool restrictions (PO/PM can't run Bash)
- Process group cleanup on timeout (kills orphaned children)
- Working directory locked to project_dir
"""

import os
import signal
import logging
import subprocess
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


def call_claude_code(
    prompt: str,
    base_dir: Path,
    timeout: int = AGENT_TIMEOUT_SECONDS,
    verbose: bool = False,
    allowed_tools: str = DEFAULT_ALLOWED_TOOLS,
) -> str:
    """Call Claude Code CLI with a prompt.

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

    # Start in new process group so we can kill the entire tree on timeout
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(base_dir),
        env=env,
        start_new_session=True,  # New process group for clean kill
    )

    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill entire process group (including child pytest, bash, etc.)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        proc.kill()
        proc.wait()
        raise

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
