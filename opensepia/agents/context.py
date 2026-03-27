"""
AI Dev Team — Agent context builder.

Assembles the full prompt context for an agent from board state,
workspace tree, inbox, provider comments, and communication rules.
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def build_agent_context_from_adapter(
    agent_id: str,
    agents_config: dict[str, Any],
    agent_context: "AgentContext",
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

    context = f"""{system_prompt}

---
# CURRENT STATE

Time: {now} | Sprint: {ac.sprint_num} | Cycle: {ac.cycle_num}

## Project
{ac.project_description if ac.project_description else "(empty)"}

## Sprint (COMPLETE)
{ac.sprint_md if ac.sprint_md else "(none)"}

## Backlog (truncated)
{ac.backlog_md if ac.backlog_md else "(empty)"}

## Standup (current cycle)
{ac.standup if ac.standup.strip() else "(empty so far)"}

## Your Inbox ({agent_id})
{ac.inbox if ac.inbox else "(no messages)"}
{ac.provider_comments}

## Workspace
```
{ac.workspace_tree}
```

---
# INSTRUCTIONS

{agents_config.get("global", {}).get("standup_instruction", "")}

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
- Inbox files: {', '.join(f'{aid}.md' for aid in agents_config['agents'].keys())}
- NEVER use dev.md, qa.md, security.md — these files do not exist!
"""

    return context
