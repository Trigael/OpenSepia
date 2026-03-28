"""
AI Dev Team — Markdown Board Adapter.

Implements BoardAdapter by reading/writing local markdown files.
This is an extraction of the current direct file operations from
agents/context.py, agents/writer.py, and steps/agent_runner.py.
"""

import re
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from opensepia.cycle_state import _file_lock

from opensepia.board_adapter import BoardAdapter, AgentContext, STORY_BUG_ID_RE
from opensepia.agents.parser import ParsedFile
from opensepia.agents.workspace import get_workspace_tree
from opensepia.blockers import extract_blockers, format_blockers_for_context, update_blocker_registry
from opensepia.review_gate import check_review_evidence, get_reviewer_for_story
from opensepia.config import MAX_STANDUP_CHARS, MAX_INBOX_CHARS

logger = logging.getLogger(__name__)

MAX_BACKLOG_CHARS = 4000
MAX_PROJECT_CHARS = 2000
MAX_COMMENT_CONTEXT_CHARS = 6000


class MarkdownBoardAdapter(BoardAdapter):
    """Board adapter backed by local markdown files.

    Extracts and preserves the exact behavior of the current direct
    file operations. This is the reference implementation — any new
    adapter must produce the same AgentContext structure.
    """

    def __init__(
        self,
        board_dir: Path,
        workspace_dir: Path,
        project_dir: Path,
    ):
        self.board_dir = board_dir
        self.workspace_dir = workspace_dir
        self.project_dir = project_dir

    SNAPSHOT_FILES = ["sprint.md", "backlog.md", "project.md", "architecture.md", "decisions.md"]

    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except OSError as e:
            return f"[READ ERROR: {e}]"

    # ----- Agent context -----

    def get_agent_context(self, agent_id: str, agents_config: dict, project_config: dict) -> AgentContext:
        sprint_cfg = project_config.get("sprint", {})

        # Project description
        project_md = self._read(self.board_dir / "project.md")
        if len(project_md) > MAX_PROJECT_CHARS:
            project_md = project_md[:MAX_PROJECT_CHARS]

        # Sprint (complete)
        sprint_md = self._read(self.board_dir / "sprint.md")

        # Backlog (truncated)
        backlog_md = self._read(self.board_dir / "backlog.md")
        if len(backlog_md) > MAX_BACKLOG_CHARS:
            backlog_md = backlog_md[:MAX_BACKLOG_CHARS]

        # Standup (current cycle only — strip nested <details>)
        standup = self._read(self.board_dir / "standup.md")
        details_pos = standup.find("<details>")
        if details_pos >= 0:
            standup = standup[:details_pos].strip()
        if len(standup) > MAX_STANDUP_CHARS:
            standup = standup[:MAX_STANDUP_CHARS] + "\n_(truncated)_"

        # Inbox
        inbox = self._read(self.board_dir / "inbox" / f"{agent_id}.md")

        # Workspace tree
        workspace_tree = get_workspace_tree(self.workspace_dir)

        # Blockers
        cycle_num = sprint_cfg.get("current_cycle", 0)
        blockers = extract_blockers(sprint_md)
        update_blocker_registry(self.board_dir, blockers, cycle_num)
        blockers_context = format_blockers_for_context(blockers, cycle_num)

        # Provider comments (optional)
        provider_comments = self._fetch_provider_comments()

        # Evolution data (if evolution directory exists)
        agent_memory, relevant_skills, lineage_context = self._load_evolution(
            agent_id, sprint_md, inbox,
        )

        return AgentContext(
            blockers_md=blockers_context,
            project_description=project_md,
            sprint_md=sprint_md,
            backlog_md=backlog_md,
            standup=standup,
            inbox=inbox,
            workspace_tree=workspace_tree,
            provider_comments=provider_comments,
            sprint_num=sprint_cfg.get("current_sprint", 1),
            cycle_num=sprint_cfg.get("current_cycle", 0),
            agent_memory=agent_memory,
            relevant_skills=relevant_skills,
            lineage_context=lineage_context,
        )

    def _fetch_provider_comments(self) -> str:
        """Fetch provider comments for active stories (optional)."""
        try:
            from opensepia.integrations.providers import detect_provider
            from opensepia.board.comments import get_active_story_ids, fetch_comments_for_context

            provider = detect_provider()
            if provider and provider.enabled and provider.name != "markdown":
                active_ids = get_active_story_ids(
                    self.board_dir / "sprint.md",
                    self.board_dir / "backlog.md",
                )
                comments_md = fetch_comments_for_context(
                    active_ids, provider, max_chars=MAX_COMMENT_CONTEXT_CHARS,
                )
                if comments_md:
                    return f"\n## Issue Discussions (from {provider.name})\n{comments_md}"
        except (ImportError, OSError, ValueError, KeyError) as e:
            logger.debug("Provider comments unavailable: %s", e)
        return ""

    def _load_evolution(
        self, agent_id: str, sprint_md: str, inbox: str,
    ) -> tuple[str, str, str]:
        """Load evolution data if the evolution directory exists.

        Returns (agent_memory, relevant_skills, lineage_context).
        """
        evo_dir = self.board_dir / "evolution"
        if not evo_dir.exists():
            return "", "", ""

        agent_memory = ""
        relevant_skills = ""
        lineage_context = ""

        try:
            from opensepia.evolution.memory import AgentMemory
            mem = AgentMemory(self.board_dir)
            agent_memory = mem.get_context_snippet(agent_id)
        except (ImportError, OSError) as e:
            logger.debug("Evolution memory unavailable: %s", e)

        try:
            from opensepia.evolution.skills import SkillStore, extract_keywords
            store = SkillStore(self.board_dir)
            keywords = extract_keywords(sprint_md + " " + inbox)
            relevant_skills = store.load_relevant_skills(agent_id, keywords)
        except (ImportError, OSError) as e:
            logger.debug("Evolution skills unavailable: %s", e)

        try:
            lineage_path = evo_dir / "lineage" / "lineage.yaml"
            if lineage_path.exists():
                import yaml
                lineage = yaml.safe_load(lineage_path.read_text(encoding="utf-8")) or {}
                agent_info = lineage.get("agents", {}).get(agent_id, {})
                if agent_info.get("type") == "spawned":
                    parent = agent_info.get("parent", "unknown")
                    lineage_context = (
                        f"You were spawned from {parent}. "
                        f"Ancestors: {agent_info.get('lineage', [parent])}"
                    )
        except (ImportError, OSError) as e:
            logger.debug("Evolution lineage unavailable: %s", e)

        return agent_memory, relevant_skills, lineage_context

    # ----- Agent output -----

    def apply_agent_output(self, agent_id: str, files: list[ParsedFile], agents_config: dict) -> int:
        """Write parsed files to disk with security checks."""
        written = 0
        resolved_base = self.project_dir.resolve()

        for pf in files:
            if not pf.path or not pf.content:
                continue

            # Evolution file routing with guardrails
            if "board/evolution/" in pf.path:
                if self._apply_evolution_output(agent_id, pf):
                    written += 1
                continue

            # Security: resolve path and check it's under project_dir
            full_path = (self.project_dir / pf.path).resolve()
            if not str(full_path).startswith(str(resolved_base)):
                logger.warning("SECURITY: %s path traversal blocked: %s", agent_id, pf.path)
                continue

            # Review gate: check REVIEW→DONE transitions in sprint.md
            if pf.path.rstrip("/").endswith("sprint.md"):
                old_content = self._read(full_path)
                pf = self._enforce_review_gate(pf, old_content, agent_id)

            if pf.action == "append":
                existing = self._read(full_path)
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(existing + "\n" + pf.content, encoding="utf-8")
            else:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(pf.content, encoding="utf-8")

            written += 1

        return written

    def _apply_evolution_output(self, agent_id: str, pf: ParsedFile) -> bool:
        """Route evolution file writes through guardrails. Returns True if written."""
        try:
            from opensepia.evolution.guardrails import validate_file_path, validate_memory_entry, validate_skill

            # Validate path
            path_result = validate_file_path(agent_id, pf.path)
            if not path_result.valid:
                logger.warning("EVOLUTION: %s blocked: %s", agent_id, path_result.errors)
                return False

            # Memory writes
            if "/memory/" in pf.path:
                from opensepia.evolution.memory import AgentMemory
                mem = AgentMemory(self.board_dir)
                existing_size = len(mem.load(agent_id))
                val = validate_memory_entry(agent_id, pf.content, existing_size)
                if not val.valid:
                    logger.warning("EVOLUTION: %s memory blocked: %s", agent_id, val.errors)
                    return False
                # Write directly (append)
                mem.ensure_dir()
                path = mem.memory_dir / f"{agent_id}.md"
                existing = mem.load(agent_id)
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                path.write_text(existing + pf.content + "\n", encoding="utf-8")
                logger.info("EVOLUTION: %s memory updated (%d chars)", agent_id, len(pf.content))
                return True

            # Skill writes
            if "/skills/" in pf.path:
                val = validate_skill(pf.content)
                if not val.valid:
                    logger.warning("EVOLUTION: %s skill blocked: %s", agent_id, val.errors)
                    return False
                full_path = (self.project_dir / pf.path).resolve()
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(pf.content, encoding="utf-8")
                logger.info("EVOLUTION: %s saved skill to %s", agent_id, pf.path)
                return True

            # Proposal writes (force to pending/)
            if "/proposals/" in pf.path:
                proposals_dir = self.board_dir / "evolution" / "proposals" / "pending"
                proposals_dir.mkdir(parents=True, exist_ok=True)
                filename = Path(pf.path).name
                target = proposals_dir / filename
                target.write_text(pf.content, encoding="utf-8")
                logger.info("EVOLUTION: %s created proposal %s", agent_id, filename)
                return True

            # Default: write to disk (other evolution files)
            full_path = (self.project_dir / pf.path).resolve()
            resolved_base = self.project_dir.resolve()
            if not str(full_path).startswith(str(resolved_base)):
                return False
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(pf.content, encoding="utf-8")
            return True

        except (ImportError, OSError) as e:
            logger.warning("EVOLUTION: %s write error: %s", agent_id, e)
            return False
    # ----- Review gate helpers -----

    @staticmethod
    def _parse_stories_by_section(content: str) -> dict[str, set[str]]:
        """Parse sprint.md into {section_lower: {STORY-001, ...}}."""
        result: dict[str, set[str]] = {}
        current_section: str | None = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                current_section = stripped[3:].strip().lower()
                result.setdefault(current_section, set())
            elif current_section:
                for sid in STORY_BUG_ID_RE.findall(line):
                    result[current_section].add(sid.upper())
        return result

    @staticmethod
    def _find_assignee(content: str, story_id: str) -> str:
        """Extract the assignee from a sprint line like '- [ ] STORY-001: Title (dev1)'."""
        for line in content.split("\n"):
            if story_id.upper() in line.upper():
                m = re.search(r"\((\w+)\)\s*$", line.strip())
                if m:
                    return m.group(1)
        return "dev1"

    def _enforce_review_gate(self, pf: ParsedFile, old_content: str, agent_id: str) -> ParsedFile:
        """Block REVIEW→DONE transitions that lack review evidence."""
        if not old_content.strip():
            return pf

        old_sections = self._parse_stories_by_section(old_content)
        new_sections = self._parse_stories_by_section(pf.content)

        old_review = old_sections.get("review", set())
        new_done = new_sections.get("done", set())
        old_done = old_sections.get("done", set())

        # Stories that moved from REVIEW to DONE in this update
        promoted = old_review & (new_done - old_done)
        if not promoted:
            return pf

        blocked: list[str] = []
        for story_id in promoted:
            has_review, reason = check_review_evidence(story_id, self.board_dir)
            if not has_review:
                logger.warning(
                    "REVIEW GATE: blocked %s REVIEW→DONE (%s), agent=%s",
                    story_id, reason, agent_id,
                )
                blocked.append(story_id)

                # Notify the appropriate reviewer
                assignee = self._find_assignee(old_content, story_id)
                reviewer = get_reviewer_for_story(story_id, assignee)
                self.send_inbox_message(
                    reviewer,
                    "review-gate",
                    f"Please review **{story_id}** (assigned to {assignee}). "
                    f"It cannot move to DONE without peer review approval.",
                )

        if not blocked:
            return pf

        # Rewrite new content: move blocked stories back to REVIEW
        patched = self._move_stories_to_section(pf.content, blocked, "REVIEW")
        return ParsedFile(path=pf.path, content=patched, action=pf.action)

    @staticmethod
    def _move_stories_to_section(content: str, story_ids: list[str], target_section: str) -> str:
        """Remove stories from their current section and place them in target_section."""
        ids_upper = {s.upper() for s in story_ids}
        lines = content.split("\n")
        removed_lines: list[str] = []
        result_lines: list[str] = []

        for line in lines:
            found = STORY_BUG_ID_RE.findall(line)
            if found and any(s.upper() in ids_upper for s in found):
                removed_lines.append(line)
            else:
                result_lines.append(line)

        # Find target section and insert removed lines
        output: list[str] = []
        inserted = False
        for line in result_lines:
            output.append(line)
            if not inserted and line.strip().lower() == f"## {target_section.lower()}":
                for rl in removed_lines:
                    output.append(rl)
                inserted = True

        # If target section not found, append it
        if not inserted:
            output.append(f"\n## {target_section}")
            output.extend(removed_lines)

        return "\n".join(output)

    # ----- Inbox -----

    def get_inbox(self, agent_id: str) -> str:
        return self._read(self.board_dir / "inbox" / f"{agent_id}.md")

    def archive_inbox(self, agent_id: str) -> None:
        inbox_path = self.board_dir / "inbox" / f"{agent_id}.md"
        lock_path = inbox_path.with_suffix(".lock")
        with _file_lock(lock_path):
            content = self._read(inbox_path)
            if not content.strip():
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_dir = self.board_dir / "archive" / agent_id
            archive_dir.mkdir(parents=True, exist_ok=True)
            (archive_dir / f"{timestamp}.md").write_text(content, encoding="utf-8")
            inbox_path.write_text("", encoding="utf-8")

    # ----- Standup -----

    def init_standup(self, sprint_num: int, cycle_num: int) -> None:
        standup_file = self.board_dir / "standup.md"
        old_content = self._read(standup_file)

        if old_content.strip():
            # Archive old standup
            archive_dir = self.board_dir / "archive" / "standup"
            archive_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            (archive_dir / f"s{sprint_num}_c{cycle_num - 1}_{timestamp}.md").write_text(
                old_content, encoding="utf-8",
            )

            # Keep previous cycle as context (strip nested <details>)
            details_pos = old_content.find("<details>")
            if details_pos >= 0:
                clean = old_content[:details_pos].strip()
            else:
                clean = old_content.strip()

            _TRUNCATION_MARKER = "\n_(truncated)_"
            if len(clean) > MAX_INBOX_CHARS:
                clean = clean[:MAX_INBOX_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER

            prev = f"\n\n<details><summary>Previous cycle</summary>\n\n{clean}\n</details>\n"
        else:
            prev = ""

        header = f"# Standup — Sprint {sprint_num}, Cycle {cycle_num}\n"
        standup_file.parent.mkdir(parents=True, exist_ok=True)
        standup_file.write_text(header + prev + "\n", encoding="utf-8")

    # ----- Board readiness -----

    _DEFAULT_AGENTS = [
        "po", "pm", "dev1", "dev2", "devops", "tester",
        "sec_analyst", "sec_engineer", "sec_pentester",
    ]

    def ensure_board_ready(self, agents_config: dict | None = None) -> None:
        self.board_dir.mkdir(parents=True, exist_ok=True)
        inbox_dir = self.board_dir / "inbox"
        inbox_dir.mkdir(exist_ok=True)
        (self.board_dir / "archive").mkdir(exist_ok=True)

        # Derive agent list from config when available, fall back to defaults
        if agents_config and "agents" in agents_config:
            known_agents = list(agents_config["agents"].keys())
        else:
            known_agents = self._DEFAULT_AGENTS
        for agent in known_agents:
            inbox_file = inbox_dir / f"{agent}.md"
            if not inbox_file.exists():
                inbox_file.touch()

    # ----- New adapter methods -----

    def get_sprint_text(self) -> str:
        return self._read(self.board_dir / "sprint.md")

    def get_backlog_text(self) -> str:
        return self._read(self.board_dir / "backlog.md")

    def get_standup_text(self) -> str:
        return self._read(self.board_dir / "standup.md")

    def get_sprint_number(self) -> int:
        content = self._read(self.board_dir / "sprint.md")
        m = re.search(r"Sprint\s+(\d+)", content)
        return int(m.group(1)) if m else 1

    def get_active_story_ids(self) -> list[str]:
        """Parse sprint.md for stories in TODO/IN_PROGRESS/REVIEW/TESTING sections."""
        content = self._read(self.board_dir / "sprint.md")
        if not content:
            return []

        active_statuses = {"todo", "in progress", "in_progress", "review", "testing"}
        current_status = None
        ids: list[str] = []

        for line in content.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("## "):
                section = stripped[3:].strip()
                current_status = section if section in active_statuses else None
            elif current_status:
                refs = STORY_BUG_ID_RE.findall(line)
                ids.extend(refs)

        return ids

    def get_board_summary(self) -> dict[str, int]:
        """Count stories by status from sprint.md checkboxes."""
        content = self._read(self.board_dir / "sprint.md")
        if not content:
            return {}

        summary: dict[str, int] = {}
        current_section: str | None = None

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                current_section = stripped[3:].strip().lower().replace(" ", "_")
                if current_section not in summary:
                    summary[current_section] = 0
            elif current_section and stripped.startswith("- ["):
                summary[current_section] = summary.get(current_section, 0) + 1

        return summary

    def check_board_health(self) -> dict[str, bool]:
        """Check sprint.md and backlog.md exist and are non-empty."""
        results: dict[str, bool] = {}
        for fname in ("sprint.md", "backlog.md"):
            fpath = self.board_dir / fname
            results[fname] = fpath.exists() and fpath.stat().st_size > 0
        return results

    def create_snapshot(self) -> int:
        """Copy board files to .snapshot/ directory."""
        snapshot_dir = self.board_dir / ".snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for fname in self.SNAPSHOT_FILES:
            src = self.board_dir / fname
            if src.exists():
                shutil.copy2(src, snapshot_dir / f"{fname}.bak")
                count += 1
        return count

    def send_inbox_message(self, to_agent: str, from_name: str, message: str) -> None:
        """Append a message to an agent's inbox file."""
        inbox_path = self.board_dir / "inbox" / f"{to_agent}.md"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        entry = f"\n## Message from {from_name}\n{message}\n"
        with open(inbox_path, "a", encoding="utf-8") as f:
            f.write(entry)
