"""
AI Dev Team — Evolution Guardrails.

Safety validation for all self-modification operations.
Prevents prompt injection, path traversal, and resource exhaustion.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a guardrail validation check."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Limits
MAX_PROMPT_LENGTH = 8000
MAX_MEMORY_LENGTH = 10000
MAX_SKILL_LENGTH = 5000
MAX_SPAWNED_AGENTS = 20
MAX_PROMPT_VERSIONS = 50

# Injection detection patterns
FORBIDDEN_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?!Developer|Product|Project|QA|DevOps|Security)", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|.*?\|>"),
    re.compile(r"IMPORTANT:\s*disregard", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(?:your|previous)", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
]


def validate_prompt(agent_id: str, new_prompt: str, agents_config: dict) -> ValidationResult:
    """Validate a proposed prompt refinement.

    Checks:
    - Length within MAX_PROMPT_LENGTH
    - No injection patterns
    - Retains core role identity
    - Doesn't reference or modify other agents' prompts
    """
    errors = []
    warnings = []

    if len(new_prompt) > MAX_PROMPT_LENGTH:
        errors.append(f"Prompt too long: {len(new_prompt)} chars (max {MAX_PROMPT_LENGTH})")

    if len(new_prompt) < 50:
        errors.append("Prompt too short — likely incomplete")

    # Check for injection patterns
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(new_prompt):
            errors.append(f"Forbidden pattern detected: {pattern.pattern}")

    # Check role identity preserved (opening lines should establish role)
    opening = " ".join(line.strip().lower() for line in new_prompt.split("\n")[:5])
    if "you are" not in opening and agent_id not in opening:
        warnings.append("Opening doesn't establish agent role — may cause identity drift")

    # Check for references to other agents' prompts
    other_agents = set(agents_config.get("agents", {}).keys()) - {agent_id}
    for other_id in other_agents:
        if f"modify {other_id}" in new_prompt.lower() or f"change {other_id}" in new_prompt.lower():
            errors.append(f"Prompt attempts to modify other agent: {other_id}")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_memory_entry(agent_id: str, entry: str, existing_size: int = 0) -> ValidationResult:
    """Validate a memory write."""
    errors = []
    warnings = []

    if existing_size + len(entry) > MAX_MEMORY_LENGTH:
        errors.append(
            f"Memory would exceed limit: {existing_size + len(entry)} chars (max {MAX_MEMORY_LENGTH})"
        )

    if len(entry) > 2000:
        warnings.append(f"Large memory entry: {len(entry)} chars — consider summarizing")

    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(entry):
            errors.append(f"Forbidden pattern in memory entry: {pattern.pattern}")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_skill(skill_content: str) -> ValidationResult:
    """Validate a skill file."""
    errors = []
    warnings = []

    if len(skill_content) > MAX_SKILL_LENGTH:
        errors.append(f"Skill too long: {len(skill_content)} chars (max {MAX_SKILL_LENGTH})")

    # Check for required metadata
    if "# Skill:" not in skill_content:
        errors.append("Missing '# Skill:' header")

    if "tags:" not in skill_content:
        warnings.append("Missing 'tags:' metadata — skill won't be matched to agents")

    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(skill_content):
            errors.append(f"Forbidden pattern in skill: {pattern.pattern}")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_spawn(
    parent_id: str,
    child_id: str,
    child_prompt: str,
    existing_agents: set[str],
) -> ValidationResult:
    """Validate a spawn proposal."""
    errors = []
    warnings = []

    if child_id in existing_agents:
        errors.append(f"Agent ID '{child_id}' already exists")

    if not re.match(r'^[a-z][a-z0-9_]{1,30}$', child_id):
        errors.append(
            f"Invalid agent ID '{child_id}' — must be lowercase, "
            "alphanumeric with underscores, 2-31 chars"
        )

    if len(existing_agents) >= MAX_SPAWNED_AGENTS:
        errors.append(f"Max agents reached ({MAX_SPAWNED_AGENTS})")

    if parent_id not in existing_agents:
        errors.append(f"Parent agent '{parent_id}' does not exist")

    # Validate the child prompt
    prompt_result = validate_prompt(child_id, child_prompt, {"agents": {child_id: {}}})
    errors.extend(prompt_result.errors)
    warnings.extend(prompt_result.warnings)

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_file_path(agent_id: str, path: str) -> ValidationResult:
    """Validate that an evolution file write targets the correct location."""
    errors = []

    # Memory: agent can only write own memory
    if "/memory/" in path:
        expected = f"board/evolution/memory/{agent_id}.md"
        if not path.endswith(f"/{agent_id}.md"):
            errors.append(f"Agent {agent_id} cannot write to {path} — only {expected}")

    # Skills: allowed to write to _global/ or _project/
    if "/skills/" in path:
        if "/_global/" not in path and "/_project/" not in path:
            errors.append(f"Skills must be in _global/ or _project/ — got {path}")

    # Proposals: must go to pending/
    if "/proposals/" in path and "/pending/" not in path:
        errors.append(f"Proposals must be written to pending/ — got {path}")

    # Prompts: agents cannot directly write to prompts/ (must use proposals)
    if "/prompts/" in path and "/proposals/" not in path:
        errors.append(f"Agents cannot directly modify prompts — use proposals instead")

    # General path traversal
    if ".." in path:
        errors.append(f"Path traversal detected: {path}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
