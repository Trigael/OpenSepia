"""
AI Dev Team — Skill Acquisition.

Agents learn skills by writing skill files that persist across cycles.
Skills are matched by tags and injected into relevant agents' context.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_SKILL_CHARS = 5000
MAX_SKILLS_CONTEXT = 3000


@dataclass
class SkillFile:
    """A learned skill that can be shared across agents."""
    name: str
    scope: str  # "global" or "project"
    tags: list[str] = field(default_factory=list)
    content: str = ""
    learned_by: str = ""
    version: int = 1


class SkillStore:
    """Manages skill files that persist and are shared across agents."""

    def __init__(self, board_dir: Path):
        self.skills_dir = board_dir / "evolution" / "skills"

    def ensure_dir(self) -> None:
        (self.skills_dir / "_global").mkdir(parents=True, exist_ok=True)
        (self.skills_dir / "_project").mkdir(parents=True, exist_ok=True)

    def load_relevant_skills(
        self,
        agent_id: str,
        context_keywords: list[str],
        max_chars: int = MAX_SKILLS_CONTEXT,
    ) -> str:
        """Load skills relevant to this agent and current work context.

        Matches by tags against context_keywords. Returns formatted markdown.
        """
        all_skills = self.list_skills()
        if not all_skills:
            return ""

        keywords_lower = {k.lower() for k in context_keywords}

        # Score skills by relevance
        scored: list[tuple[float, SkillFile]] = []
        for skill in all_skills:
            score = 0.0
            # Tag match
            for tag in skill.tags:
                if tag.lower() in keywords_lower:
                    score += 1.0
            # Learned by this agent gets a boost
            if skill.learned_by == agent_id:
                score += 0.5
            if score > 0:
                scored.append((score, skill))

        # Sort by relevance (highest first)
        scored.sort(key=lambda x: x[0], reverse=True)

        # Format as markdown, respecting max_chars
        lines = []
        total = 0
        for _score, skill in scored:
            header = f"### {skill.name} (tags: {', '.join(skill.tags)})\n"
            content = skill.content.strip()
            entry = f"{header}{content}\n"
            if total + len(entry) > max_chars:
                break
            lines.append(entry)
            total += len(entry)

        return "\n".join(lines)

    def save_skill(self, skill: SkillFile) -> Path:
        """Write a skill file to the appropriate scope directory."""
        self.ensure_dir()
        scope_dir = self.skills_dir / f"_{skill.scope}"
        # Sanitize name for filename
        safe_name = re.sub(r'[^a-z0-9_-]', '_', skill.name.lower())[:50]
        path = scope_dir / f"{safe_name}.md"

        content = f"# Skill: {skill.name}\n"
        content += f"scope: {skill.scope}\n"
        content += f"tags: [{', '.join(skill.tags)}]\n"
        content += f"learned_by: {skill.learned_by}\n"
        content += f"version: {skill.version}\n\n"
        content += skill.content

        path.write_text(content, encoding="utf-8")
        logger.info("Saved skill '%s' to %s", skill.name, path)
        return path

    def list_skills(self, scope: str | None = None) -> list[SkillFile]:
        """List all available skills, optionally filtered by scope."""
        skills = []
        dirs = []
        if scope is None or scope == "global":
            dirs.append(self.skills_dir / "_global")
        if scope is None or scope == "project":
            dirs.append(self.skills_dir / "_project")

        for skill_dir in dirs:
            if not skill_dir.exists():
                continue
            for path in skill_dir.glob("*.md"):
                skill = self._parse_skill_file(path)
                if skill:
                    skills.append(skill)

        return skills

    def _parse_skill_file(self, path: Path) -> SkillFile | None:
        """Parse a skill file from disk."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        name = path.stem.replace("_", " ").title()
        scope = "project" if "_project" in str(path.parent) else "global"
        tags: list[str] = []
        learned_by = ""
        content_lines = []
        in_content = False

        for line in text.split("\n"):
            if line.startswith("# Skill:"):
                name = line.replace("# Skill:", "").strip()
            elif line.startswith("scope:"):
                scope = line.split(":", 1)[1].strip()
            elif line.startswith("tags:"):
                tag_str = line.split(":", 1)[1].strip().strip("[]")
                tags = [t.strip() for t in tag_str.split(",") if t.strip()]
            elif line.startswith("learned_by:"):
                learned_by = line.split(":", 1)[1].strip()
            elif line.startswith("version:"):
                pass  # Skip version line
            else:
                if line.strip() or in_content:
                    in_content = True
                    content_lines.append(line)

        return SkillFile(
            name=name,
            scope=scope,
            tags=tags,
            content="\n".join(content_lines).strip(),
            learned_by=learned_by,
        )

    def parse_skill_from_agent_output(self, content: str) -> SkillFile | None:
        """Parse a skill definition from agent-written file content."""
        return self._parse_skill_file_from_text(content)

    def _parse_skill_file_from_text(self, text: str) -> SkillFile | None:
        """Parse skill metadata from raw text content."""
        name = ""
        scope = "project"
        tags: list[str] = []
        learned_by = ""
        content_lines = []

        for line in text.split("\n"):
            if line.startswith("# Skill:"):
                name = line.replace("# Skill:", "").strip()
            elif line.startswith("scope:"):
                scope = line.split(":", 1)[1].strip()
            elif line.startswith("tags:"):
                tag_str = line.split(":", 1)[1].strip().strip("[]")
                tags = [t.strip() for t in tag_str.split(",") if t.strip()]
            elif line.startswith("learned_by:"):
                learned_by = line.split(":", 1)[1].strip()
            elif line.startswith("version:"):
                pass
            elif line.strip():
                content_lines.append(line)

        if not name:
            return None

        return SkillFile(
            name=name,
            scope=scope,
            tags=tags,
            content="\n".join(content_lines).strip(),
            learned_by=learned_by,
        )


def extract_keywords(text: str) -> list[str]:
    """Extract technology/domain keywords from text for skill matching."""
    # Common tech keywords to look for
    tech_words = {
        "python", "fastapi", "flask", "django", "sqlalchemy", "sqlite", "postgresql",
        "javascript", "typescript", "react", "vue", "angular", "node", "express",
        "docker", "kubernetes", "nginx", "redis", "celery", "websocket",
        "html", "css", "htmx", "tailwind", "api", "rest", "graphql",
        "pytest", "unittest", "testing", "ci", "cd", "git", "github", "gitlab",
        "authentication", "authorization", "jwt", "oauth", "security",
        "database", "migration", "model", "schema", "orm",
    }

    words = set(re.findall(r'\b[a-z]+\b', text.lower()))
    return list(words & tech_words)
