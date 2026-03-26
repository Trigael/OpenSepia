"""
AI Dev Team — Workspace tree listing for agent context.
"""

from pathlib import Path

MAX_WORKSPACE_FILES_PER_DIR = 10
MAX_WORKSPACE_SUBDIRS = 5

SKIP_DIRS = {"node_modules", "__pycache__", ".git", "venv"}


def get_workspace_tree(workspace_dir: Path, max_depth: int = 2) -> str:
    """Return workspace file tree (truncated to save tokens).

    Args:
        workspace_dir: Path to the workspace directory.
        max_depth: Maximum directory depth to traverse.

    Returns:
        Formatted tree string, or "(workspace is empty)" if nothing found.
    """
    if not workspace_dir.exists():
        return "(workspace is empty)"

    result: list[str] = []

    def walk(path: Path, depth: int, prefix: str = "") -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        dirs = [e for e in entries if e.is_dir() and not e.name.startswith(".")]
        files = [e for e in entries if e.is_file() and not e.name.startswith(".")]

        for f in files[:MAX_WORKSPACE_FILES_PER_DIR]:
            result.append(f"{prefix}{f.name}")
        if len(files) > MAX_WORKSPACE_FILES_PER_DIR:
            result.append(f"{prefix}... and {len(files) - MAX_WORKSPACE_FILES_PER_DIR} more")
        for d in dirs[:MAX_WORKSPACE_SUBDIRS]:
            if d.name in SKIP_DIRS:
                continue
            result.append(f"{prefix}{d.name}/")
            walk(d, depth + 1, prefix + "  ")

    walk(workspace_dir, 0)
    return "\n".join(result) if result else "(workspace is empty)"
