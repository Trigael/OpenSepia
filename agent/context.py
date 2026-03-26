"""
AI Dev Team — Agent context builder.

Assembles the full prompt context for an agent from board state,
workspace tree, inbox, provider comments, and communication rules.
"""

import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.workspace import get_workspace_tree
from agent.writer import read_file_safe

logger = logging.getLogger(__name__)

MAX_STANDUP_CHARS = 2000
MAX_INBOX_CHARS = 1500
MAX_COMMENT_CONTEXT_CHARS = 6000


def build_agent_context(
    agent_id: str,
    agents_config: dict[str, Any],
    project_config: dict[str, Any],
    board_dir: Path,
    workspace_dir: Path,
    base_dir: Path,
) -> str:
    """Build complete context for an agent.

    Token-efficient version — truncates large sections to stay within
    reasonable prompt sizes for Claude Pro/Max plans.

    Args:
        agent_id: Agent identifier (e.g., "dev1", "po").
        agents_config: Full agents.yaml config.
        project_config: Full project.yaml config.
        board_dir: Path to board/ directory.
        workspace_dir: Path to workspace/ directory.
        base_dir: Project root directory.

    Returns:
        Complete prompt string ready to send to Claude CLI.
    """
    agent = agents_config["agents"][agent_id]
    sprint_cfg = project_config.get("sprint", {})

    # Load board files
    project_md = read_file_safe(board_dir / "project.md")
    sprint_md = read_file_safe(board_dir / "sprint.md")
    backlog_md = read_file_safe(board_dir / "backlog.md")

    # Load standup (current cycle only — cut off nested <details>)
    standup_file = board_dir / "standup.md"
    standup_content = read_file_safe(standup_file)
    details_pos = standup_content.find("<details>")
    if details_pos > 0:
        standup_content = standup_content[:details_pos].strip()
    if len(standup_content) > MAX_STANDUP_CHARS:
        standup_content = standup_content[:MAX_STANDUP_CHARS] + "\n_(truncated)_"

    # Load this agent's inbox
    inbox_path = board_dir / "inbox" / f"{agent_id}.md"
    inbox_content = read_file_safe(inbox_path)

    # Workspace tree (truncated)
    workspace_tree = get_workspace_tree(workspace_dir)

    # Metadata
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cycle = sprint_cfg.get("current_cycle", 0)
    sprint_num = sprint_cfg.get("current_sprint", 1)

    # System prompt
    system_prompt = agent["system_prompt"]

    # Provider comments (READ path)
    provider_section = _fetch_provider_comments(board_dir, base_dir)

    # Communication rules
    comm_rules = agents_config["global"].get("communication_rules", "")

    context = f"""{system_prompt}

---
# CURRENT STATE

Time: {now} | Sprint: {sprint_num} | Cycle: {cycle}

## Project
{project_md[:2000] if project_md else "(empty)"}

## Sprint (COMPLETE)
{sprint_md if sprint_md else "(none)"}

## Backlog (truncated)
{backlog_md[:4000] if backlog_md else "(empty)"}

## Standup (current cycle)
{standup_content if standup_content.strip() else "(empty so far)"}

## Your Inbox ({agent_id})
{inbox_content if inbox_content else "(no messages)"}
{provider_section}

## Workspace
```
{workspace_tree}
```

---
# INSTRUCTIONS

{agents_config["global"].get("standup_instruction", "")}

{comm_rules}

Do your work. At the end you MUST return:

```
---FILES---
path: board/sprint.md
content:
(file content)
---
path: board/inbox/dev1.md
action: append
content:
## Message from {agent['name']}
(message text)
---END---
```

Rules:
- Each file starts with "path:" and "content:"
- To append to the end use "action: append"
- Only write relevant files
- Inbox files: po.md, pm.md, dev1.md, dev2.md, devops.md, tester.md, sec_analyst.md, sec_engineer.md, sec_pentester.md
- NEVER use dev.md, qa.md, security.md — these files do not exist!
"""

    return context


def _fetch_provider_comments(board_dir: Path, base_dir: Path) -> str:
    """Fetch recent provider comments for active stories.

    Returns formatted Markdown section or empty string on failure.
    """
    try:
        sys.path.insert(0, str(base_dir))
        from integrations.providers import detect_provider
        from scripts.sync_comments import get_active_story_ids, fetch_comments_for_context

        provider = detect_provider()
        if provider and provider.enabled:
            active_ids = get_active_story_ids(
                board_dir / "sprint.md",
                board_dir / "backlog.md",
            )
            comments_md = fetch_comments_for_context(
                active_ids, provider, max_chars=MAX_COMMENT_CONTEXT_CHARS,
            )
            if comments_md:
                return f"\n## Issue Discussions (from {provider.name})\n{comments_md}"
    except Exception as e:
        logger.debug("Provider comments unavailable: %s", e)

    return ""
