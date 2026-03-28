"""Tests for evolution/spawning.py — agent spawning and lineage."""

import pytest
from pathlib import Path

from opensepia.evolution.spawning import AgentSpawner


@pytest.fixture
def spawner(tmp_path):
    board_dir = tmp_path / "board"
    (board_dir / "evolution" / "lineage").mkdir(parents=True)
    (board_dir / "evolution" / "memory").mkdir(parents=True)
    (board_dir / "inbox").mkdir(parents=True)
    return AgentSpawner(board_dir)


class TestLineage:
    def test_initialize_lineage(self, spawner):
        spawner.initialize_lineage(["po", "dev1", "dev2"])
        lineage = spawner.get_lineage("dev1")
        assert lineage["type"] == "original"
        assert lineage["children"] == []

    def test_initialize_idempotent(self, spawner):
        spawner.initialize_lineage(["po", "dev1"])
        spawner.initialize_lineage(["po", "dev1", "dev2"])
        # All three should exist
        assert spawner.get_lineage("po")["type"] == "original"
        assert spawner.get_lineage("dev2")["type"] == "original"

    def test_get_lineage_nonexistent(self, spawner):
        assert spawner.get_lineage("nonexistent") == {}

    def test_get_lineage_context_original(self, spawner):
        spawner.initialize_lineage(["dev1"])
        assert spawner.get_lineage_context("dev1") == ""

    def test_get_lineage_context_spawned(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are a frontend developer.", 1, 1,
        )
        context = spawner.get_lineage_context("frontend_dev")
        assert "dev1" in context
        assert "spawned from" in context.lower()


class TestSpawning:
    def test_spawn_creates_agent(self, spawner):
        spawner.initialize_lineage(["dev1"])
        agent = spawner.execute_spawn_from_details(
            parent_id="dev1",
            child_id="frontend_dev",
            child_name="Frontend Developer",
            child_prompt="You are a frontend specialist.",
            sprint=2, cycle=3,
        )
        assert agent.agent_id == "frontend_dev"
        assert agent.parent_id == "dev1"
        assert agent.lineage == ["dev1"]
        assert agent.status == "active"

    def test_spawn_creates_inbox(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )
        inbox = spawner.board_dir / "inbox" / "frontend_dev.md"
        assert inbox.exists()

    def test_spawn_inherits_parent_memory(self, spawner):
        spawner.initialize_lineage(["dev1"])
        # Create parent memory
        mem_dir = spawner.board_dir / "evolution" / "memory"
        (mem_dir / "dev1.md").write_text("- [S1C1] Parent learned X\n", encoding="utf-8")

        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )

        child_memory = (mem_dir / "frontend_dev.md").read_text(encoding="utf-8")
        assert "Inherited from dev1" in child_memory
        assert "Parent learned X" in child_memory

    def test_spawn_updates_lineage(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )

        # Parent should have child
        parent = spawner.get_lineage("dev1")
        assert "frontend_dev" in parent["children"]

        # Child should reference parent
        child = spawner.get_lineage("frontend_dev")
        assert child["type"] == "spawned"
        assert child["parent"] == "dev1"

    def test_spawn_chain_lineage(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )
        spawner.execute_spawn_from_details(
            "frontend_dev", "react_dev", "React Dev",
            "You specialize in React.", 2, 1,
        )

        react = spawner.get_lineage("react_dev")
        assert react["lineage"] == ["dev1", "frontend_dev"]
        assert react["parent"] == "frontend_dev"

    def test_get_spawned_agents(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )
        agents = spawner.get_spawned_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "frontend_dev"

    def test_get_active_agent_ids(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )
        ids = spawner.get_active_agent_ids()
        assert "frontend_dev" in ids

    def test_deactivate_agent(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )
        spawner.deactivate_agent("frontend_dev")
        ids = spawner.get_active_agent_ids()
        assert "frontend_dev" not in ids

    def test_registry_persists(self, spawner):
        spawner.initialize_lineage(["dev1"])
        spawner.execute_spawn_from_details(
            "dev1", "frontend_dev", "Frontend Dev",
            "You are frontend.", 1, 1,
        )
        # Create a new spawner instance (simulates restart)
        new_spawner = AgentSpawner(spawner.board_dir)
        agents = new_spawner.get_spawned_agents()
        assert len(agents) == 1
