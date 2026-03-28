"""Tests for evolution/skills.py — skill acquisition and matching."""

import pytest
from pathlib import Path

from opensepia.evolution.skills import SkillStore, SkillFile, extract_keywords


@pytest.fixture
def store(tmp_path):
    board_dir = tmp_path / "board"
    board_dir.mkdir()
    return SkillStore(board_dir)


class TestSkillStore:
    def test_ensure_dir(self, store):
        store.ensure_dir()
        assert (store.skills_dir / "_global").exists()
        assert (store.skills_dir / "_project").exists()

    def test_save_and_list(self, store):
        skill = SkillFile(
            name="FastAPI Patterns",
            scope="global",
            tags=["python", "fastapi", "api"],
            content="Use APIRouter for modular routes.",
            learned_by="dev1",
        )
        store.save_skill(skill)
        skills = store.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "FastAPI Patterns"
        assert "fastapi" in skills[0].tags

    def test_list_by_scope(self, store):
        store.save_skill(SkillFile(name="Global Skill", scope="global", tags=["python"]))
        store.save_skill(SkillFile(name="Project Skill", scope="project", tags=["react"]))
        assert len(store.list_skills(scope="global")) == 1
        assert len(store.list_skills(scope="project")) == 1
        assert len(store.list_skills()) == 2

    def test_load_relevant_skills_by_tags(self, store):
        store.save_skill(SkillFile(
            name="Docker Patterns", scope="global",
            tags=["docker", "deployment"],
            content="Multi-stage builds for smaller images.",
        ))
        store.save_skill(SkillFile(
            name="React Hooks", scope="project",
            tags=["react", "javascript"],
            content="Use useEffect for side effects.",
        ))

        # Docker keywords should match docker skill
        result = store.load_relevant_skills("devops", ["docker", "nginx"])
        assert "Docker Patterns" in result
        assert "React Hooks" not in result

        # React keywords should match react skill
        result = store.load_relevant_skills("dev1", ["react", "typescript"])
        assert "React Hooks" in result
        assert "Docker Patterns" not in result

    def test_load_relevant_skills_empty(self, store):
        assert store.load_relevant_skills("dev1", ["python"]) == ""

    def test_load_relevant_skills_respects_max_chars(self, store):
        for i in range(20):
            store.save_skill(SkillFile(
                name=f"Skill {i}", scope="global",
                tags=["python"], content="x" * 200,
            ))
        result = store.load_relevant_skills("dev1", ["python"], max_chars=500)
        assert len(result) <= 600  # Allow some margin

    def test_learned_by_boost(self, store):
        store.save_skill(SkillFile(
            name="Dev1 Skill", scope="global",
            tags=["python"], content="Dev1's pattern.",
            learned_by="dev1",
        ))
        store.save_skill(SkillFile(
            name="Dev2 Skill", scope="global",
            tags=["python"], content="Dev2's pattern.",
            learned_by="dev2",
        ))
        # dev1 should see their own skill ranked higher
        result = store.load_relevant_skills("dev1", ["python"], max_chars=300)
        assert "Dev1 Skill" in result

    def test_parse_skill_from_text(self, store):
        text = """# Skill: SQLAlchemy Async
scope: project
tags: [python, sqlalchemy, database]
learned_by: dev1

Use async sessions with `async with AsyncSession() as session`.
Always call `await session.commit()` explicitly.
"""
        skill = store.parse_skill_from_agent_output(text)
        assert skill is not None
        assert skill.name == "SQLAlchemy Async"
        assert skill.scope == "project"
        assert "sqlalchemy" in skill.tags
        assert "async sessions" in skill.content

    def test_parse_skill_no_name(self, store):
        skill = store.parse_skill_from_agent_output("Just some text without metadata")
        assert skill is None


class TestExtractKeywords:
    def test_extracts_tech_words(self):
        text = "We're building a FastAPI app with PostgreSQL and Docker"
        keywords = extract_keywords(text)
        assert "fastapi" in keywords
        assert "docker" in keywords

    def test_empty_text(self):
        assert extract_keywords("") == []

    def test_no_tech_words(self):
        assert extract_keywords("The quick brown fox jumps") == []

    def test_case_insensitive(self):
        keywords = extract_keywords("Using PYTHON and React for this project")
        assert "python" in keywords
        assert "react" in keywords
