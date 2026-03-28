"""Centralized directory resolution for OpenSepia.

Single source of truth for determining the tool root directory.
All modules should use get_tool_dir() instead of Path(__file__).parent.parent.
"""

import os
from pathlib import Path

_tool_dir: Path | None = None


def get_tool_dir() -> Path:
    """Return the OpenSepia tool root directory.

    Resolution order:
    1. Explicitly set via set_tool_dir() (used by daemon after fork)
    2. OPENSEPIA_ROOT environment variable
    3. Current working directory (if it contains config/agents.yaml)
    4. Fallback: Path(__file__).parent.parent (package location)
    """
    if _tool_dir is not None:
        return _tool_dir

    env = os.environ.get("OPENSEPIA_ROOT")
    if env:
        return Path(env).resolve()

    cwd = Path.cwd()
    if (cwd / "config" / "agents.yaml").exists():
        return cwd

    return Path(__file__).parent.parent


def set_tool_dir(path: Path) -> None:
    """Pin tool_dir explicitly. Used by daemon after fork."""
    global _tool_dir
    _tool_dir = path.resolve()
