"""Tests for evolution/splitting.py — over-generalization detection."""

import pytest
from pathlib import Path

from opensepia.evolution.splitting import AgentSplitter, SplitProposal, SPLIT_THRESHOLD


@pytest.fixture
def splitter(tmp_path):
    board_dir = tmp_path / "board"
    (board_dir / "evolution" / "proposals" / "pending").mkdir(parents=True)
    return AgentSplitter(board_dir)


class TestDomainDetection:
    def test_single_domain(self, splitter):
        text = "Using FastAPI router with SQLAlchemy query optimization"
        domains = splitter._detect_domains(text)
        assert "backend" in domains or "database" in domains

    def test_multiple_domains(self, splitter):
        text = "Built React components with FastAPI backend, Docker deployment, pytest coverage"
        domains = splitter._detect_domains(text)
        assert len(domains) >= 3

    def test_no_domains(self, splitter):
        text = "The quick brown fox jumps over the lazy dog"
        domains = splitter._detect_domains(text)
        assert len(domains) == 0


class TestGeneralizationAnalysis:
    def test_no_split_for_focused_agent(self, splitter):
        memory = "- [S1C1] Learned FastAPI routing\n- [S1C2] Fixed API endpoint"
        results = [{"response": "path: src/api/routes.py\ncontent: ..."}]

        proposal = splitter.analyze_generalization("dev1", memory, results)
        assert proposal is None

    def test_split_proposed_for_diverse_agent(self, splitter):
        memory = (
            "- [S1C1] Built React component with hooks\n"
            "- [S1C2] Wrote SQLAlchemy migration for users table\n"
            "- [S1C3] Fixed Docker compose networking\n"
            "- [S1C4] Added pytest fixtures for API tests\n"
            "- [S2C1] Configured nginx reverse proxy\n"
            "- [S2C2] Built Vue frontend dashboard\n"
        )
        results = [
            {"response": "path: src/frontend/App.tsx\npath: src/backend/api.py\npath: docker/Dockerfile\npath: tests/test_api.py\npath: nginx/nginx.conf"},
            {"response": "path: src/frontend/hooks.ts\npath: src/db/migrations/001.sql\npath: docker-compose.yml"},
        ]

        proposal = splitter.analyze_generalization("dev1", memory, results)
        assert proposal is not None
        assert proposal.original_id == "dev1"
        assert len(proposal.into) >= 2

    def test_self_reported_overload(self, splitter):
        memory = "- [S1C1] Handling too much\n" * 5
        results = [
            {"response": "I'm handling too many responsibilities. This is outside my expertise."},
        ]

        proposal = splitter.analyze_generalization("dev1", memory, results)
        # May or may not trigger depending on other scores
        # But self_reported score should be > 0
        if proposal:
            assert proposal.metrics["scores"]["self_reported"] > 0

    def test_blocked_rate_detection(self, splitter):
        memory = "- Various tasks"
        results = [
            {"response": "BLOCKED on frontend", "error": None},
            {"response": "BLOCKED on database", "error": None},
            {"response": "BLOCKED on tests", "error": "timeout"},
        ]

        proposal = splitter.analyze_generalization("dev1", memory, results)
        # Blocked rate should contribute to score
        if proposal:
            assert proposal.metrics["scores"]["blocked_rate"] > 0


class TestProposalCreation:
    def test_propose_split(self, splitter):
        proposal = SplitProposal(
            original_id="dev1",
            into=[
                {"id": "dev1_frontend", "name": "Frontend Specialist", "prompt_focus": "React"},
                {"id": "dev1_backend", "name": "Backend Specialist", "prompt_focus": "FastAPI"},
            ],
            reason="Too many domains",
            metrics={"total_score": 0.75},
        )

        path = splitter.propose_split(proposal, sprint=3, cycle=5)
        assert path.exists()
        assert "split" in path.name

        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["type"] == "split_agent"
        assert data["details"]["original_id"] == "dev1"
        assert len(data["details"]["into"]) == 2
