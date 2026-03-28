"""End-to-end tests — exercise the full CLI and pipeline with --dry-run.

These tests run real CLI commands and verify the integrated behavior
of config loading, mode resolution, context building, and pipeline
execution without actually calling Claude (--dry-run skips the LLM call).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

TOOL_DIR = Path(__file__).parent.parent
OPENSEPIA = [sys.executable, "-m", "opensepia"]


def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run opensepia CLI command and return result."""
    # Clean env to prevent .env file leaking BOARD_SERVER_URL into tests
    env = {**os.environ, "PYTHONPATH": str(TOOL_DIR)}
    env.pop("BOARD_SERVER_URL", None)
    return subprocess.run(
        [*OPENSEPIA, *args],
        capture_output=True,
        text=True,
        cwd=cwd or str(TOOL_DIR),
        timeout=60,
        env=env,
    )


# =============================================================================
# CLI basics
# =============================================================================

class TestCLIBasics:
    """Test that basic CLI commands work."""

    def test_help(self):
        r = _run("help")
        assert r.returncode == 0
        assert "OpenSepia" in r.stdout
        assert "opensepia" in r.stdout

    def test_help_flag(self):
        r = _run("--help")
        assert r.returncode == 0
        assert "OpenSepia" in r.stdout

    def test_unknown_command(self):
        r = _run("nonexistent")
        assert r.returncode != 0
        assert "Unknown command" in r.stdout

    def test_status(self):
        r = _run("status")
        assert r.returncode == 0
        assert "Daemon:" in r.stdout
        assert "Project:" in r.stdout

    def test_status_shows_sprint(self):
        r = _run("status")
        assert "Sprint" in r.stdout


# =============================================================================
# Config command
# =============================================================================

class TestConfig:
    """Test opensepia config command."""

    def test_config_all(self):
        r = _run("config")
        assert r.returncode == 0
        assert "Project Settings" in r.stdout
        assert "Agent Modes" in r.stdout
        assert "Execution Parameters" in r.stdout
        assert "Provider Integration" in r.stdout

    def test_config_project(self):
        r = _run("config", "project")
        assert r.returncode == 0
        assert "Name:" in r.stdout
        assert "Sprint:" in r.stdout
        assert "Cycles/sprint:" in r.stdout

    def test_config_agents(self):
        r = _run("config", "agents")
        assert r.returncode == 0
        assert "dev-team" in r.stdout
        assert "minimal" in r.stdout
        assert "security" in r.stdout
        assert "Timeout:" in r.stdout

    def test_config_env(self):
        r = _run("config", "env")
        assert r.returncode == 0
        assert "Provider Integration" in r.stdout

    def test_config_shows_set_hint(self):
        r = _run("config")
        assert "config set" in r.stdout

    def test_config_unknown_section(self):
        r = _run("config", "nonexistent")
        assert r.returncode == 0
        output = r.stdout + r.stderr
        assert "Unknown" in output


# =============================================================================
# Init command
# =============================================================================

class TestInit:
    """Test opensepia init in a temporary project directory."""

    @pytest.fixture
    def temp_project(self, tmp_path):
        """Create a minimal tool dir with config for init testing."""
        tool = tmp_path / "tool"
        tool.mkdir()

        # Copy config
        shutil.copytree(TOOL_DIR / "config", tool / "config")
        # Copy opensepia package (needed for imports)
        shutil.copytree(TOOL_DIR / "opensepia", tool / "opensepia")

        # Create empty project dir
        project = tool / "project"
        project.mkdir()

        # Create a minimal project.yaml
        (project / "project.yaml").write_text(yaml.dump({
            "project": {"name": "", "description": ""},
            "sprint": {"current_sprint": 1, "current_cycle": 0, "cycles_per_sprint": 10},
        }), encoding="utf-8")

        return tool

    def test_init_creates_board_files(self, temp_project):
        r = subprocess.run(
            [sys.executable, "-m", "opensepia", "init", "Test Project", "A test"],
            capture_output=True, text=True,
            cwd=str(temp_project), timeout=10,
            env={**os.environ, "PYTHONPATH": str(temp_project)},
        )
        assert r.returncode == 0
        assert "Initializing project" in r.stdout

        board = temp_project / "project" / "board"
        assert (board / "sprint.md").exists()
        assert (board / "backlog.md").exists()
        assert (board / "project.md").exists()
        assert (board / "architecture.md").exists()
        assert (board / "decisions.md").exists()

    def test_init_creates_inbox_files(self, temp_project):
        subprocess.run(
            [sys.executable, "-m", "opensepia", "init", "Test", "Desc"],
            capture_output=True, text=True,
            cwd=str(temp_project), timeout=10,
            env={**os.environ, "PYTHONPATH": str(temp_project)},
        )
        inbox = temp_project / "project" / "board" / "inbox"
        assert inbox.exists()
        assert (inbox / "po.md").exists()
        assert (inbox / "dev1.md").exists()
        assert (inbox / "tester.md").exists()

    def test_init_seeds_po_inbox(self, temp_project):
        subprocess.run(
            [sys.executable, "-m", "opensepia", "init", "My App", "A web app"],
            capture_output=True, text=True,
            cwd=str(temp_project), timeout=10,
            env={**os.environ, "PYTHONPATH": str(temp_project)},
        )
        po_inbox = (temp_project / "project" / "board" / "inbox" / "po.md").read_text(encoding="utf-8")
        assert "My App" in po_inbox
        assert "first task" in po_inbox.lower() or "First task" in po_inbox

    def test_init_updates_project_yaml(self, temp_project):
        subprocess.run(
            [sys.executable, "-m", "opensepia", "init", "My App", "A web app"],
            capture_output=True, text=True,
            cwd=str(temp_project), timeout=10,
            env={**os.environ, "PYTHONPATH": str(temp_project)},
        )
        with open(temp_project / "project" / "project.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        assert cfg["project"]["name"] == "My App"
        assert cfg["sprint"]["current_sprint"] == 1
        assert cfg["sprint"]["current_cycle"] == 0


# =============================================================================
# Dry run — full pipeline without calling Claude
# =============================================================================

class TestDryRun:
    """Test dry-run mode which exercises the full pipeline minus the LLM call."""

    def test_dry_run_single_agent(self):
        r = _run("run", "po", "--dry-run")
        assert r.returncode == 0
        # Dry run should print the agent's context
        assert "po" in r.stdout.lower()

    def test_dry_run_shows_context(self):
        r = _run("run", "po", "--dry-run")
        assert r.returncode == 0
        # Context should include agent identity or board state sections
        output = r.stdout.lower()
        assert "sprint" in output or "product owner" in output or "po" in output

    def test_dry_run_minimal_mode(self):
        r = _run("run", "minimal", "--dry-run")
        assert r.returncode == 0
        # Should show context for PO, Dev1, Tester
        output = r.stdout.lower()
        assert "po" in output
        assert "dev1" in output
        assert "tester" in output

    def test_dry_run_does_not_modify_board(self):
        """Dry run should not change any board files."""
        board_dir = TOOL_DIR / "project" / "board"
        if not board_dir.exists():
            pytest.skip("No project/board directory")

        # Snapshot board state before
        files_before = {}
        for f in board_dir.glob("*.md"):
            files_before[f.name] = f.read_text(encoding="utf-8")

        _run("run", "po", "--dry-run")

        # Verify nothing changed
        for name, content in files_before.items():
            assert (board_dir / name).read_text(encoding="utf-8") == content

    def test_dry_run_does_not_increment_cycle(self):
        """Dry run should not change cycle counter."""
        project_yaml = TOOL_DIR / "project" / "project.yaml"
        with open(project_yaml, encoding="utf-8") as f:
            before = yaml.safe_load(f)
        cycle_before = before.get("sprint", {}).get("current_cycle", 0)

        _run("run", "po", "--dry-run")

        with open(project_yaml, encoding="utf-8") as f:
            after = yaml.safe_load(f)
        cycle_after = after.get("sprint", {}).get("current_cycle", 0)

        assert cycle_after == cycle_before

    def test_dry_run_alias_mode(self):
        """Alias 'dev' should work same as 'dev-team'."""
        r = _run("run", "dev", "--dry-run")
        assert r.returncode == 0

    def test_dry_run_unknown_mode_fails(self):
        r = _run("run", "nonexistent-mode", "--dry-run")
        assert r.returncode != 0


# =============================================================================
# Mode resolution e2e
# =============================================================================

class TestModeResolution:
    """Test that modes resolve correctly through the full stack."""

    def test_all_modes_resolve(self):
        for mode in ["all", "dev-team", "minimal", "security", "dev", "min", "sec"]:
            r = _run("run", mode, "--dry-run")
            assert r.returncode == 0, f"Mode '{mode}' failed: {r.stdout}{r.stderr}"

    def test_single_agents_resolve(self):
        for agent in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
            r = _run("run", agent, "--dry-run")
            assert r.returncode == 0, f"Agent '{agent}' failed: {r.stdout}{r.stderr}"

    def test_security_agents_resolve(self):
        for agent in ["sec_analyst", "sec_engineer", "sec_pentester"]:
            r = _run("run", agent, "--dry-run")
            assert r.returncode == 0, f"Agent '{agent}' failed: {r.stdout}{r.stderr}"

    def test_bare_mode_shortcut(self):
        """Running 'opensepia po --dry-run' (without 'run') should work."""
        r = subprocess.run(
            [*OPENSEPIA, "po", "--dry-run"],
            capture_output=True, text=True,
            cwd=str(TOOL_DIR), timeout=30,
            env={**os.environ, "PYTHONPATH": str(TOOL_DIR)},
        )
        assert r.returncode == 0


# =============================================================================
# Monitor command
# =============================================================================

class TestMonitor:
    """Test opensepia monitor command."""

    def test_monitor_no_logs(self):
        r = _run("monitor")
        # Either shows stats or says no logs — both are valid
        assert r.returncode == 0

    def test_monitor_last(self):
        r = _run("monitor", "--last")
        assert r.returncode == 0


# =============================================================================
# Daemon state
# =============================================================================

class TestDaemonState:
    """Test daemon status when not running."""

    def test_stop_when_not_running(self):
        r = _run("stop")
        assert r.returncode == 0
        assert "not running" in r.stdout.lower()

    def test_pause_when_not_running(self):
        r = _run("pause")
        assert r.returncode == 0
        assert "not running" in r.stdout.lower()

    def test_resume_when_not_running(self):
        r = _run("resume")
        assert r.returncode == 0
        assert "not running" in r.stdout.lower()
