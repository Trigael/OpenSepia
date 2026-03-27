"""
AI Dev Team — Agent output parsing.

Parses the ---FILES--- and ---OUTPUT--- sections from agent responses,
extracting file paths, actions, and content.
"""

from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


@dataclass
class ParsedFile:
    """A single file extracted from agent output."""
    path: str
    content: str
    action: str = "overwrite"  # "overwrite" | "append"


def parse_files_section(response: str) -> list[ParsedFile]:
    """Parse ---FILES--- section from agent response.

    Format:
        ---FILES---
        path: board/sprint.md
        action: overwrite
        content:
        (file content)
        ---
        path: board/inbox/dev1.md
        action: append
        content:
        (message text)
        ---END---

    Args:
        response: Full agent response text.

    Returns:
        List of ParsedFile objects. Empty list if no FILES section found.
    """
    if "---FILES---" not in response:
        if "---OUTPUT---" in response:
            return parse_output_yaml(response)
        return []

    start = response.find("---FILES---")
    end = response.find("---END---", start)
    if end == -1:
        end = len(response)

    section = response[start + len("---FILES---"):end]

    files: list[ParsedFile] = []
    current_path = ""
    current_action = "overwrite"
    current_content: list[str] = []
    in_content = False

    for line in section.split("\n"):
        stripped = line.strip()

        if stripped.startswith("path:"):
            # Save previous file
            if current_path:
                content = "\n".join(current_content).strip()
                if content:
                    files.append(ParsedFile(
                        path=current_path,
                        content=content,
                        action=current_action,
                    ))

            # Start new file
            current_path = stripped[5:].strip()
            current_action = "overwrite"
            current_content = []
            in_content = False

        elif stripped.startswith("action:") and current_path:
            current_action = stripped[7:].strip()

        elif stripped.startswith("content:"):
            in_content = True
            rest = stripped[8:].strip()
            if rest:
                current_content.append(rest)

        elif stripped == "---" and current_path:
            # End of current file
            content = "\n".join(current_content).strip()
            if content:
                files.append(ParsedFile(
                    path=current_path,
                    content=content,
                    action=current_action,
                ))
            current_path = ""
            current_action = "overwrite"
            current_content = []
            in_content = False

        elif in_content and current_path:
            current_content.append(line)

    # Handle last file (no trailing ---)
    if current_path:
        content = "\n".join(current_content).strip()
        if content:
            files.append(ParsedFile(
                path=current_path,
                content=content,
                action=current_action,
            ))

    return files


def parse_output_yaml(response: str) -> list[ParsedFile]:
    """Fallback parser for ---OUTPUT--- YAML format.

    Args:
        response: Full agent response text.

    Returns:
        List of ParsedFile objects. Empty list if parsing fails.
    """
    if "---OUTPUT---" not in response or yaml is None:
        return []

    try:
        section = response.split("---OUTPUT---", 1)[1]
        if "---END---" in section:
            section = section.split("---END---", 1)[0]

        data = yaml.safe_load(section)
        if data and "files_to_write" in data:
            return [
                ParsedFile(
                    path=f.get("path", ""),
                    content=f.get("content", ""),
                    action=f.get("action", "overwrite"),
                )
                for f in data["files_to_write"]
                if f.get("path") and f.get("content")
            ]
    except (yaml.YAMLError, ValueError, KeyError, TypeError) as e:
        import logging
        logging.getLogger(__name__).debug("Failed to parse OUTPUT YAML: %s", e)

    return []


def parse_standup_from_response(response: str, agent_id: str,
                                 agent_name: str, agent_color: str) -> str:
    """Extract ---STANDUP--- section from agent response as fallback.

    Used when the agent doesn't include standup in its ---FILES--- output.

    Args:
        response: Full agent response text.
        agent_id: Agent identifier.
        agent_name: Human-readable agent name.
        agent_color: Emoji for the agent.

    Returns:
        Formatted standup text, or empty string if not found.
    """
    if "---STANDUP---" not in response:
        return ""

    start = response.find("---STANDUP---") + len("---STANDUP---")
    end = response.find("---", start)
    if end == -1:
        end = min(start + 500, len(response))

    raw = response[start:end].strip()
    if not raw:
        return ""

    if len(raw) > 500:
        raw = raw[:497] + "..."

    return f"## {agent_color} {agent_name}\n{raw}\n"
