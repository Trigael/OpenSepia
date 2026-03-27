"""
AI Dev Team — Agent output writer.

Handles standup fallback + provider comment posting for agent output.
File writing is handled by the board adapter.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia.agents.parser import ParsedFile, parse_standup_from_response

logger = logging.getLogger(__name__)


def read_file_safe(path: Path) -> str:
    """Safely read a file, return empty string if it does not exist."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as e:
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


def _handle_standup_fallback(
    agent_id: str,
    result: dict[str, Any],
    parsed_files: list[ParsedFile],
    agents_config: dict[str, Any],
    standup_file: Path,
) -> None:
    """Write standup fallback if agent didn't include it in ---FILES---."""
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


def _handle_provider_comments(
    agent_id: str,
    parsed_files: list[ParsedFile],
) -> None:
    """Post review comments to the provider."""
    try:
        from opensepia.integrations.providers import detect_provider
        from opensepia.board.comments import post_agent_messages_to_provider, reset_mr_cache
        provider = detect_provider()
        if provider and provider.enabled:
            reset_mr_cache()
            files_as_dicts = [
                {"path": pf.path, "content": pf.content, "action": pf.action}
                for pf in parsed_files
            ]
            post_agent_messages_to_provider(agent_id, files_as_dicts, provider)
    except (ImportError, OSError, ValueError, KeyError) as e:
        logger.warning("Provider comments: %s", e)
