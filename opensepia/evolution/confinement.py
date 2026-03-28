"""
AI Dev Team — Agent Confinement.

Immutable rules that agents must follow. These rules cannot be overridden
by evolution, prompt refinement, or any agent action.

Confinement operates at three levels:
1. IMMUTABLE LAWS — injected into every prompt, cannot be removed
2. WORKSPACE JAIL — agents can only read/write within project_dir
3. COMMAND BLOCKLIST — dangerous bash commands are forbidden

These rules are the foundation that evolution operates within.
Agents can evolve their skills, memory, and prompts, but never
escape the confinement boundary.
"""

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# IMMUTABLE LAWS — prepended to every agent prompt, non-negotiable
# =============================================================================
IMMUTABLE_LAWS = """
## IMMUTABLE RULES (cannot be overridden)

These rules are enforced by the system and cannot be changed by any agent,
prompt refinement, or evolution proposal. Violations are logged and blocked.

1. **WORKSPACE BOUNDARY**: You may ONLY read and write files within the
   project workspace directory. You cannot access files outside of it.
   Do NOT read or modify any files in the opensepia/ source code directory.

2. **NO SYSTEM COMMANDS**: You may NOT run: opensepia start, opensepia stop,
   opensepia reset, opensepia run, kill, pkill, rm -rf, shutdown, reboot,
   or any command that affects processes outside your workspace.

3. **NO CREDENTIAL ACCESS**: You may NOT read config/.env, ~/.ssh/,
   ~/.claude/, or any file containing API keys, tokens, or secrets.

4. **NO NETWORK ACCESS**: You may NOT use curl, wget, nc, ssh, or any
   command that makes network connections, unless explicitly part of
   your assigned story (e.g., testing a local API endpoint you built).

5. **IDENTITY PRESERVATION**: You are {agent_id} ({agent_name}). You cannot
   impersonate other agents, write to other agents' memory files, or
   modify other agents' prompts.

6. **OUTPUT INTEGRITY**: Your ---FILES--- output must only contain files
   within board/ and workspace/. You cannot write to system paths.

7. **EVOLUTION WITHIN BOUNDS**: You may propose prompt changes and record
   learnings, but proposals that violate any immutable rule will be rejected.
"""

# =============================================================================
# COMMAND BLOCKLIST — bash commands agents must not run
# =============================================================================
BLOCKED_COMMANDS = [
    # OpenSepia orchestrator commands
    r"opensepia\s+(start|stop|reset|run|pause|resume)",
    # Process management
    r"\bkill\b",
    r"\bpkill\b",
    r"\bkillall\b",
    # Destructive file operations outside workspace
    r"rm\s+(-[rf]+\s+)?/",           # rm with absolute path
    r"rm\s+(-[rf]+\s+)?\.\./",       # rm with parent traversal
    r"rm\s+-rf\s+\.",                 # rm -rf . (current dir wipe)
    # System commands
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bsystemctl\b",
    r"\bservice\s+",
    # Credential access
    r"cat\s+.*\.env\b",
    r"cat\s+.*\.ssh/",
    r"cat\s+.*\.claude/",
    r"cat\s+.*credentials",
    r"cat\s+.*secret",
    # Network commands
    r"\bcurl\s+-",                    # curl with flags (allow simple curl to localhost)
    r"\bwget\b",
    r"\bnc\b",
    r"\bssh\b",
    r"\bscp\b",
    r"\brsync\b",
    # Docker commands (only devops should use these, and only within workspace)
    r"\bdocker\s+(rm|rmi|system\s+prune)",
    # Package managers (prevent installing system packages)
    r"\bapt\b",
    r"\bapt-get\b",
    r"\byum\b",
    r"\bpip\s+install\s+(?!-r\s+requirements)",  # allow pip install -r requirements.txt
    r"\bnpm\s+install\s+-g",
]

BLOCKED_COMMAND_PATTERNS = [re.compile(p, re.IGNORECASE) for p in BLOCKED_COMMANDS]

# =============================================================================
# PATH RESTRICTIONS — files/directories agents cannot read
# =============================================================================
BLOCKED_READ_PATHS = [
    "config/.env",
    ".env",
    ".ssh/",
    ".claude/",
    ".git/config",          # May contain tokens
    "opensepia/",           # OpenSepia source code
    "/etc/",
    "/root/",
    "/home/claude/.claude/",
]


def get_immutable_laws(agent_id: str, agent_name: str) -> str:
    """Get the immutable laws text with agent identity filled in."""
    return IMMUTABLE_LAWS.replace("{agent_id}", agent_id).replace("{agent_name}", agent_name)


def check_command(command: str) -> tuple[bool, str]:
    """Check if a bash command is allowed.

    Returns (allowed, reason). If not allowed, reason explains why.
    """
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if pattern.search(command):
            return False, f"Blocked command pattern: {pattern.pattern}"
    return True, ""


def check_read_path(path: str, project_dir: Path) -> tuple[bool, str]:
    """Check if a file read path is allowed.

    Agents should only read within project_dir.
    Returns (allowed, reason).
    """
    # Normalize
    try:
        resolved = Path(path).resolve()
        project_resolved = project_dir.resolve()
    except (OSError, ValueError):
        return False, f"Invalid path: {path}"

    # Must be within project_dir
    try:
        resolved.relative_to(project_resolved)
        return True, ""
    except ValueError:
        pass

    # Check explicit blocklist
    for blocked in BLOCKED_READ_PATHS:
        if blocked in path:
            return False, f"Blocked path: {blocked}"

    return False, f"Path outside project directory: {path}"


def check_write_path(path: str, project_dir: Path) -> tuple[bool, str]:
    """Check if a file write path is allowed.

    Agents can only write within project_dir/board/ and project_dir/workspace/.
    Returns (allowed, reason).
    """
    try:
        resolved = Path(path).resolve()
        project_resolved = project_dir.resolve()
    except (OSError, ValueError):
        return False, f"Invalid path: {path}"

    # Must be within project_dir
    try:
        resolved.relative_to(project_resolved)
    except ValueError:
        return False, f"Write outside project directory: {path}"

    # Must be within board/ or workspace/ (not project root)
    rel = str(resolved.relative_to(project_resolved))
    if not (rel.startswith("board") or rel.startswith("workspace")):
        return False, f"Write must be in board/ or workspace/: {path}"

    return True, ""


def build_allowed_tools_for_agent(agent_id: str, agents_config: dict) -> str:
    """Build the --allowedTools string for a specific agent.

    Different agents get different tool access:
    - PO, PM: Read, Glob, Grep, Write (no Bash — they don't write code)
    - dev*, devops: Read, Glob, Grep, Write, Edit, Bash
    - tester: Read, Glob, Grep, Bash (read + run tests)
    - sec_*: Read, Glob, Grep (read-only analysis)
    """
    # Check for per-agent overrides in config
    agent_cfg = agents_config.get("agents", {}).get(agent_id, {})
    custom_tools = agent_cfg.get("allowed_tools")
    if custom_tools:
        return custom_tools

    # Role-based defaults
    if agent_id in ("po", "pm"):
        return "Read,Glob,Grep,Write"
    elif agent_id.startswith("sec_"):
        return "Read,Glob,Grep,Bash"
    elif agent_id == "tester":
        return "Read,Glob,Grep,Bash,Write"
    else:
        # dev1, dev2, devops, and any spawned dev agents
        return "Bash,Edit,Write,Read,Glob,Grep"


def validate_evolution_against_laws(
    proposal_type: str,
    content: str,
    agent_id: str,
) -> tuple[bool, list[str]]:
    """Validate that an evolution proposal doesn't violate immutable laws.

    Returns (valid, errors).
    """
    errors = []

    # Check for attempts to remove immutable rules
    removal_patterns = [
        r"remove\s+immutable",
        r"override\s+rules",
        r"ignore\s+confinement",
        r"escape\s+(?:workspace|boundary|jail)",
        r"access\s+(?:config|\.env|credentials)",
        r"modify\s+opensepia",
    ]
    for pattern_str in removal_patterns:
        if re.search(pattern_str, content, re.IGNORECASE):
            errors.append(f"Proposal violates immutable laws: {pattern_str}")

    # For prompt refinements, check that immutable laws section is preserved
    if proposal_type == "prompt_refine":
        # The laws are injected separately — but the prompt shouldn't
        # contain instructions to ignore them
        for blocked in BLOCKED_COMMANDS:
            # Check if prompt encourages using blocked commands
            if re.search(rf"(?:run|execute|use)\s+.*{blocked}", content, re.IGNORECASE):
                errors.append(f"Prompt encourages blocked command: {blocked}")

    return len(errors) == 0, errors
