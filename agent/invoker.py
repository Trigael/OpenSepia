"""
AI Dev Team — Claude Code CLI invocation with retry logic.
"""

import os
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AGENT_TIMEOUT_SECONDS = 900
DEFAULT_MAX_RETRIES = 1
DEFAULT_RETRY_DELAY = 30


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
) -> str:
    """Call Claude Code CLI with a prompt.

    Args:
        prompt: Full prompt text to send via stdin.
        base_dir: Working directory for the CLI.
        timeout: Timeout in seconds.
        verbose: Print progress to stdout.

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
        "--allowedTools", "Bash,Edit,Write,Read,Glob,Grep",
    ]

    if verbose:
        print("    Calling Claude Code CLI...")

    # Unset CLAUDECODE — otherwise claude CLI refuses to run ("nested session")
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(base_dir),
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude Code CLI error (exit {result.returncode}): {result.stderr}")

    return result.stdout


def invoke_agent(
    agent_id: str,
    context: str,
    base_dir: Path,
    agent_name: str = "",
    timeout: int = AGENT_TIMEOUT_SECONDS,
    verbose: bool = False,
) -> AgentResult:
    """Invoke Claude Code CLI for a single agent (no retry).

    Args:
        agent_id: Agent identifier.
        context: Full prompt context.
        base_dir: Working directory.
        agent_name: Human-readable agent name.
        timeout: Timeout in seconds.
        verbose: Print progress.

    Returns:
        AgentResult with response or error.
    """
    if verbose:
        print(f"\n{'=' * 60}")
        print(f"  {agent_name or agent_id}")
        print(f"{'=' * 60}")
        print(f"  Context: {len(context)} chars")

    try:
        response = call_claude_code(context, base_dir, timeout, verbose)

        if verbose:
            print(f"  Response: {len(response)} chars")

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

    except Exception as e:
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
