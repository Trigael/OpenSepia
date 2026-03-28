"""
AI Dev Team — Agent context builder.

Assembles the full prompt context for an agent from board state,
workspace tree, inbox, provider comments, and communication rules.
"""

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Max characters for sprint and backlog sections to prevent blowing token limits.
# DONE stories are stripped first; if still over limit, text is truncated.
MAX_SPRINT_CHARS = 3000
MAX_BACKLOG_CHARS = 3000


def _strip_done_stories(text: str) -> str:
    """Remove DONE section content from sprint text to save context space."""
    lines = text.split("\n")
    result = []
    in_done = False
    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("## "):
            in_done = "done" in stripped
            result.append(line)
            if in_done:
                result.append("(completed stories omitted)")
            continue
        if not in_done:
            result.append(line)
    return "\n".join(result)


def _cap_text(text: str, max_chars: int, label: str) -> str:
    """Truncate text to max_chars, logging a warning if capped."""
    if len(text) <= max_chars:
        return text
    logger.info("Capping %s from %d to %d chars", label, len(text), max_chars)
    return text[:max_chars] + f"\n... ({label} truncated at {max_chars} chars)"


def build_agent_context_from_adapter(
    agent_id: str,
    agents_config: dict[str, Any],
    agent_context: Any,
) -> str:
    """Build the prompt string from a pre-loaded AgentContext.

    Uses the same template as build_agent_context() but gets data from
    the adapter's AgentContext dataclass instead of reading files directly.
    """
    from opensepia.board_adapter import AgentContext as _AC  # noqa: avoid circular

    agent = agents_config["agents"][agent_id]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    system_prompt = agent["system_prompt"]
    comm_rules = agents_config.get("global", {}).get("communication_rules", "")

    ac = agent_context

    # Use refined prompt if evolution is active
    if ac.agent_memory or ac.relevant_skills or ac.lineage_context:
        try:
            from opensepia.evolution.prompts import PromptManager
            # board_dir is project_dir / "board" — infer from context
            # The adapter already loaded evolution data, so we know the path exists
            import os
            board_dir_env = os.environ.get("OPENSEPIA_BOARD_DIR", "")
            if board_dir_env:
                from pathlib import Path
                pm = PromptManager(Path(board_dir_env))
                refined = pm.get_active_prompt(agent_id)
                if refined:
                    system_prompt = refined
        except (ImportError, OSError):
            pass  # Evolution not available or no refined prompt

    # Cap sprint and backlog to prevent blowing agent token limits
    sprint_md = _strip_done_stories(ac.sprint_md) if ac.sprint_md else ""
    sprint_md = _cap_text(sprint_md, MAX_SPRINT_CHARS, "sprint_md")
    backlog_md = _cap_text(ac.backlog_md, MAX_BACKLOG_CHARS, "backlog_md") if ac.backlog_md else ""

    # Build evolution sections
    evolution_section = ""
    if ac.agent_memory:
        evolution_section += f"""
## Your Memory (persistent learnings)
{ac.agent_memory}
"""
    if ac.relevant_skills:
        evolution_section += f"""
## Available Skills
{ac.relevant_skills}
"""
    if ac.lineage_context:
        evolution_section += f"""
## Your Lineage
{ac.lineage_context}
"""

    # Evolution instructions (only if evolution is active)
    evolution_instructions = ""
    if ac.agent_memory or ac.relevant_skills or ac.lineage_context:
        evolution_instructions = f"""
## Self-Evolution (optional)
You can record learnings and propose improvements:
- `board/evolution/memory/{agent_id}.md` (action: append) — record what you learned this cycle
- `board/evolution/skills/_project/{{name}}.md` — document a reusable skill/pattern
- `board/evolution/proposals/pending/{{name}}.yaml` — propose prompt/agent changes

Memory entry format: `- [S{{sprint}}C{{cycle}}] Category: What you learned`
"""

    context = f"""{system_prompt}

---
# CURRENT STATE

Time: {now} | Sprint: {ac.sprint_num} | Cycle: {ac.cycle_num}

## Project
{ac.project_description if ac.project_description else "(empty)"}

## Sprint (active stories)
{sprint_md if sprint_md else "(none)"}

## Backlog (truncated)
{backlog_md if backlog_md else "(empty)"}

## Standup (current cycle)
{ac.standup if ac.standup.strip() else "(empty so far)"}

## Your Inbox ({agent_id})
{ac.inbox if ac.inbox else "(no messages)"}
{ac.provider_comments}
{evolution_section}
## Workspace
```
{ac.workspace_tree}
```

---
# INSTRUCTIONS

{agents_config.get("global", {}).get("standup_instruction", "")}

{comm_rules}
{evolution_instructions}
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
- Inbox files: {', '.join(f'{aid}.md' for aid in agents_config['agents'].keys())}
- NEVER use dev.md, qa.md, security.md — these files do not exist!
"""

    return context
