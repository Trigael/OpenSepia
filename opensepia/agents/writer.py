"""
AI Dev Team — Agent output writer.

Applies parsed agent output to disk with security checks (path traversal
protection) and handles standup fallback + provider comment posting.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia.agents.parser import ParsedFile, parse_files_section, parse_standup_from_response

logger = logging.getLogger(__name__)


def read_file_safe(path: Path) -> str:
    """Safely read a file, return empty string if it does not exist."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as e:
        return f"[READ ERROR: {e}]"


def write_file(path: Path, content: str) -> None:
    """Write to a file, create directories if they do not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def archive_inbox(agent_id: str, content: str, board_dir: Path) -> None:
    """Archive processed inbox to board/archive/{agent_id}/."""
    if not content.strip():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = board_dir / "archive" / agent_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{timestamp}.md"
    write_file(archive_path, content)


def apply_agent_output(
    agent_id: str,
    parsed_files: list[ParsedFile],
    base_dir: Path,
    verbose: bool = False,
) -> int:
    """Write parsed files to disk with path traversal protection.

    Args:
        agent_id: Agent identifier (for logging).
        parsed_files: List of ParsedFile objects from the parser.
        base_dir: Project root directory — all paths must resolve under this.
        verbose: Print progress to stdout.

    Returns:
        Number of files successfully written.
    """
    written = 0
    resolved_base = base_dir.resolve()

    for pf in parsed_files:
        if not pf.path or not pf.content:
            continue

        # Security: ensure path resolves under base_dir
        full_path = (base_dir / pf.path).resolve()
        if not str(full_path).startswith(str(resolved_base)):
            logger.warning(
                "SECURITY: %s attempted to write outside the project: %s",
                agent_id, pf.path,
            )
            continue

        if verbose:
            icon = "\U0001f4dd" if pf.action == "overwrite" else "\U0001f4ce"
            print(f"    {icon} {pf.path}")

        if pf.action == "append":
            existing = read_file_safe(full_path)
            write_file(full_path, existing + "\n" + pf.content)
        else:
            write_file(full_path, pf.content)

        written += 1

    return written


def apply_output(
    agent_id: str,
    result: dict[str, Any],
    agents_config: dict[str, Any],
    base_dir: Path,
    board_dir: Path,
    standup_file: Path,
    verbose: bool = False,
) -> int:
    """Full output processing: parse, write files, handle standup fallback,
    post provider comments, archive inbox.

    This is the high-level function that orchestrates all post-agent output
    handling. It delegates to apply_agent_output for the actual file writing.

    Args:
        agent_id: Agent identifier.
        result: Agent result dict containing 'response' key.
        agents_config: Full agents.yaml config.
        base_dir: Project root directory.
        board_dir: Board directory path.
        standup_file: Path to standup.md.
        verbose: Print progress to stdout.

    Returns:
        Number of files written.
    """
    parsed_files = parse_files_section(result["response"])

    if "integration_actions" in result["response"]:
        logger.warning(
            "%s: Response contains integration_actions, which the CLI version "
            "does not support. Use the API version (run_agent.py) for full "
            "integration support.",
            agent_id,
        )

    if verbose:
        print(f"  Files to write: {len(parsed_files)}")

    written = apply_agent_output(agent_id, parsed_files, base_dir, verbose)

    # Standup fallback: if agent did not write to board/standup.md via FILES
    standup_written = any("board/standup.md" in pf.path for pf in parsed_files)
    if not standup_written:
        agent = agents_config["agents"].get(agent_id, {})
        fallback = parse_standup_from_response(
            result["response"],
            agent_id,
            agent.get("name", agent_id),
            agent.get("color", "\U0001f4ac"),
        )
        if fallback:
            existing = read_file_safe(standup_file)
            write_file(standup_file, existing + "\n" + fallback)
            if verbose:
                print("    \U0001f4cb Standup (fallback) written")

    # Provider comments (WRITE path)
    try:
        from opensepia.integrations.providers import detect_provider
        from opensepia.board.comments import post_agent_messages_to_provider, reset_mr_cache
        provider = detect_provider()
        if provider and provider.enabled:
            reset_mr_cache()
            # Convert ParsedFile list to dict list for sync_comments compatibility
            files_as_dicts = [
                {"path": pf.path, "content": pf.content, "action": pf.action}
                for pf in parsed_files
            ]
            posted = post_agent_messages_to_provider(agent_id, files_as_dicts, provider)
            if posted and verbose:
                print(f"    \U0001f4ac Provider: {posted} comments sent")
    except Exception as e:
        logger.warning("Provider comments: %s", e)

    # Archive and clear inbox
    inbox_path = board_dir / "inbox" / f"{agent_id}.md"
    inbox_content = read_file_safe(inbox_path)
    if inbox_content.strip():
        archive_inbox(agent_id, inbox_content, board_dir)
        write_file(inbox_path, "")

    return written
