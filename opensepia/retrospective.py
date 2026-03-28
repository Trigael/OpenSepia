"""
AI Dev Team — Structured sprint retrospective.

Builds retro prompts, parses agent responses, and writes archive files.
"""

import re
from pathlib import Path

RETRO_TEMPLATE = """## Sprint {sprint_num} Retrospective

### Sprint Goal Assessment
**Goal**: {sprint_goal}
**Achieved**: (assess goal completion)

### What Went Well
- (list 3-5 things that worked)

### What To Improve
- (list 3-5 things to change, with root cause)

### Action Items
- [ ] ACTION-{n}: (specific, measurable action) — Owner: {agent}
"""


def build_retro_context(
    sprint_num: int,
    sprint_text: str,
    standup_text: str,
    velocity_data: dict | None = None,
) -> str:
    """Build the retrospective prompt context with structured template.

    Combines the retro template with sprint board content, standup notes,
    and optional velocity metrics so the agent has everything it needs.
    """
    goal_match = re.search(r"(?i)goal\s*:\s*(.+)", sprint_text)
    sprint_goal = goal_match.group(1).strip() if goal_match else "(not specified)"

    template = RETRO_TEMPLATE.format(
        sprint_num=sprint_num,
        sprint_goal=sprint_goal,
        n="XXX",
        agent="(assign)",
    )

    sections = [
        f"# Retrospective Context for Sprint {sprint_num}",
        "",
        "## Template (fill this in)",
        template,
        "## Sprint Board State",
        sprint_text.strip() if sprint_text else "(empty)",
        "",
        "## Standup Notes",
        standup_text.strip() if standup_text else "(none)",
    ]

    if velocity_data:
        lines = ["", "## Velocity Data"]
        for key, value in velocity_data.items():
            lines.append(f"- **{key}**: {value}")
        sections.extend(lines)

    return "\n".join(sections) + "\n"


def parse_retro_response(response: str) -> dict:
    """Parse agent retro response into structured data.

    Returns dict with keys:
        went_well: list[str]
        to_improve: list[str]
        action_items: list[str]
        goal_assessment: str
    """
    result: dict = {
        "went_well": [],
        "to_improve": [],
        "action_items": [],
        "goal_assessment": "",
    }

    achieved_match = re.search(
        r"\*\*Achieved\*\*\s*:\s*(.+)", response,
    )
    if achieved_match:
        result["goal_assessment"] = achieved_match.group(1).strip()

    def _extract_section(heading_pattern: str) -> list[str]:
        match = re.search(heading_pattern, response, re.IGNORECASE)
        if not match:
            return []
        start = match.end()
        # Find next heading (### or ##)
        next_heading = re.search(r"\n#{2,3}\s", response[start:])
        block = response[start : start + next_heading.start()] if next_heading else response[start:]
        items = re.findall(r"^\s*[-*]\s+(.+)", block, re.MULTILINE)
        return [item.strip() for item in items if item.strip()]

    result["went_well"] = _extract_section(r"###?\s*What\s+Went\s+Well")
    result["to_improve"] = _extract_section(r"###?\s*What\s+To\s+Improve")
    result["action_items"] = _extract_section(
        r"###?\s*Action\s+Items",
    )

    return result


def write_retro_file(board_dir: str | Path, sprint_num: int, retro_data: dict) -> Path:
    """Write board/archive/retro_sprint_N.md and return the path."""
    board_dir = Path(board_dir)
    archive_dir = board_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    lines = [f"## Sprint {sprint_num} Retrospective", ""]

    if retro_data.get("goal_assessment"):
        lines.append(f"**Goal Assessment**: {retro_data['goal_assessment']}")
        lines.append("")

    for heading, key in [
        ("What Went Well", "went_well"),
        ("What To Improve", "to_improve"),
        ("Action Items", "action_items"),
    ]:
        items = retro_data.get(key, [])
        lines.append(f"### {heading}")
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("- (none)")
        lines.append("")

    path = archive_dir / f"retro_sprint_{sprint_num}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
