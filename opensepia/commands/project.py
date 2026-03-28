"""Project commands: init, reset, setup."""

import sys
import argparse
from datetime import datetime
from pathlib import Path

from opensepia import log
from opensepia.config import OrchestratorConfig, CLI_CHECK_TIMEOUT
from opensepia.errors import ConfigError
from opensepia.commands.run import check_claude_cli


def cmd_init(argv: list[str]) -> None:
    """Initialize a new project."""
    import yaml as _yaml

    parser = argparse.ArgumentParser(prog="opensepia init", description="Initialize a new project")
    parser.add_argument("name", help="Project name")
    parser.add_argument("description", nargs="?", default="New project", help="Project description")
    args = parser.parse_args(argv)

    tool_dir = Path(__file__).parent.parent.parent
    project_dir = tool_dir / "project"
    board_dir = project_dir / "board"
    workspace_dir = project_dir / "workspace"

    log.info(f"Initializing project: {args.name}")

    # Create directories
    for d in ["inbox", "archive", ".snapshot"]:
        (board_dir / d).mkdir(parents=True, exist_ok=True)
    # Evolution directories
    for d in [
        "evolution/memory", "evolution/skills/_global", "evolution/skills/_project",
        "evolution/prompts", "evolution/lineage",
        "evolution/proposals/pending", "evolution/proposals/approved",
        "evolution/proposals/rejected",
    ]:
        (board_dir / d).mkdir(parents=True, exist_ok=True)
    for d in ["src", "tests", "docs", "config"]:
        (workspace_dir / d).mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    (board_dir / "project.md").write_text(
        f"# {args.name}\n\n## Description\n{args.description}\n\n"
        f"## Status\n- **Created**: {now}\n- **Phase**: Initialization\n- **Sprint**: 1\n\n"
        f"## Goals\n- [ ] Define product vision and MVP\n- [ ] Create initial architecture\n"
        f"- [ ] Set up development environment\n- [ ] Implement first feature\n",
        encoding="utf-8",
    )

    (board_dir / "backlog.md").write_text(
        f"# Product Backlog — {args.name}\n\n"
        f"## CRITICAL\n\n## HIGH\n"
        f"### STORY-001: Define MVP scope\n"
        f"**Priority**: HIGH\n**Status**: TODO\n\n"
        f"## MEDIUM\n"
        f"### STORY-002: Set up development environment\n"
        f"**Priority**: MEDIUM\n**Status**: TODO\n\n"
        f"## LOW\n\n## DONE\n",
        encoding="utf-8",
    )

    (board_dir / "sprint.md").write_text(
        f"# Sprint 1 — Initialization\n\n"
        f"**Goal**: Define the project, create a foundation\n"
        f"**Start**: {now}\n\n"
        f"## TODO\n- [ ] STORY-001: Define MVP scope (PO)\n"
        f"- [ ] STORY-002: Set up development environment (DevOps + Dev)\n\n"
        f"## IN PROGRESS\n\n## DONE\n\n## BLOCKED\n",
        encoding="utf-8",
    )

    (board_dir / "architecture.md").write_text(
        f"# Architecture — {args.name}\n\n## Overview\n(To be defined after MVP)\n\n"
        f"## Tech Stack\n(To be decided)\n",
        encoding="utf-8",
    )

    (board_dir / "decisions.md").write_text(
        f"# Decisions (Decision Log)\n\n"
        f"### DEC-001: Project initialization ({datetime.now().strftime('%Y-%m-%d')})\n"
        f"- **Context**: New project {args.name}\n"
        f"- **Decision**: Starting Sprint 1\n- **Who**: System (init)\n",
        encoding="utf-8",
    )

    # Create agent inboxes
    try:
        config = OrchestratorConfig.load()
        agent_ids = config.get_all_agent_ids()
    except ConfigError:
        agent_ids = ["po", "pm", "dev1", "dev2", "devops", "tester",
                     "sec_analyst", "sec_engineer", "sec_pentester"]

    for aid in agent_ids:
        inbox = board_dir / "inbox" / f"{aid}.md"
        if not inbox.exists():
            inbox.write_text("", encoding="utf-8")

    # Initialize evolution lineage for all agents
    try:
        from opensepia.evolution.spawning import AgentSpawner
        spawner = AgentSpawner(board_dir)
        spawner.initialize_lineage(agent_ids)
    except Exception as exc:
        log.warn(f"Could not initialize lineage: {exc}")

    # Seed PO inbox
    (board_dir / "inbox" / "po.md").write_text(
        f"## System message — Initialization\n\n"
        f"Project **{args.name}** has just been created.\n\n"
        f"**Description**: {args.description}\n\n"
        f"### Your first task:\n"
        f"1. Define the product vision\n"
        f"2. Break down the MVP into user stories\n"
        f"3. Prioritize the backlog\n"
        f"4. Send PM instructions for Sprint 1\n",
        encoding="utf-8",
    )

    # Update project.yaml
    project_file = project_dir / "project.yaml"
    if project_file.exists():
        with open(project_file, "r", encoding="utf-8") as f:
            project_cfg = _yaml.safe_load(f) or {}
    else:
        project_cfg = {"project": {}, "sprint": {}, "limits": {}}

    project_cfg.setdefault("project", {})["name"] = args.name
    project_cfg["project"]["description"] = args.description
    project_cfg.setdefault("sprint", {})["current_sprint"] = 1
    project_cfg["sprint"]["current_cycle"] = 0

    with open(project_file, "w", encoding="utf-8") as f:
        _yaml.dump(project_cfg, f, default_flow_style=False, allow_unicode=True)

    # Create a .gitignore in workspace for common build artifacts
    ws_gitignore = workspace_dir / ".gitignore"
    if not ws_gitignore.exists():
        ws_gitignore.write_text(
            "__pycache__/\n*.pyc\nnode_modules/\n.venv/\nvenv/\n"
            ".env\n.coverage\n*.egg-info/\ndist/\nbuild/\n",
            encoding="utf-8",
        )

    # Plane.so integration — auto-create workspace and project
    _setup_plane(args.name, args.description, tool_dir, agent_ids)

    log.success("Project initialized!")
    log.info(f"Board:     {board_dir}")
    log.info(f"Workspace: {workspace_dir}")
    log.info("")
    log.info("Next steps:")
    log.info("1. opensepia start                 # start running cycles")
    log.info("")
    log.info("Optional — enable git sync:")
    log.info(f"cd {workspace_dir}")
    log.info("git init")
    log.info("git remote add origin <your-repo-url>")
    log.info("# Then set GIT_REPO_URL and GIT_TOKEN in config/.env")


def _setup_plane(
    project_name: str,
    description: str,
    tool_dir: Path,
    agent_ids: list[str],
) -> None:
    """Auto-create Plane.so workspace, project, and board infrastructure.

    Skips silently if PLANE_API_KEY is not set.
    Creates workspace and project if they don't exist, stores the project ID
    in config/.env, then runs ensure_board_ready() for states/labels/pages.
    """
    import os
    import re

    plane_key = os.environ.get("PLANE_API_KEY", "").strip()
    plane_base = os.environ.get("PLANE_BASE_URL", "http://localhost:3000").strip()
    if not plane_key:
        return

    log.info("")
    log.header("Plane.so integration")

    from opensepia.integrations.providers.plane_client import PlaneClient, PlaneConfig
    from opensepia.integrations.providers.plane import PlaneProvider

    # Derive a slug from the project name (lowercase, hyphens, no special chars)
    slug = re.sub(r'[^a-z0-9]+', '-', project_name.lower()).strip('-')[:48]
    if not slug:
        slug = "opensepia"

    workspace_slug = os.environ.get("PLANE_WORKSPACE_SLUG", "").strip()
    project_id = os.environ.get("PLANE_PROJECT_ID", "").strip()

    # Create a temporary config for workspace-level operations
    config = PlaneConfig(
        api_key=plane_key,
        workspace_slug=workspace_slug or slug,
        project_id=project_id,
        base_url=plane_base,
    )
    provider = PlaneProvider(config)

    # Step 1: Find or create workspace
    if not workspace_slug:
        ws = provider.find_workspace(slug)
        if ws:
            workspace_slug = ws["slug"]
            log.info(f"  Found workspace: {workspace_slug}")
        else:
            result = provider.create_workspace(project_name, slug)
            if isinstance(result, dict) and "error" not in result:
                workspace_slug = result.get("slug", slug)
                log.success(f"  Created workspace: {workspace_slug}")
            else:
                # Workspace creation may require admin — try using the slug directly
                log.warn(f"  Could not create workspace: {result.get('message', result)}")
                log.info(f"  Trying slug '{slug}' — create it manually if needed")
                workspace_slug = slug

        # Update config with the real workspace slug
        config.workspace_slug = workspace_slug
        os.environ["PLANE_WORKSPACE_SLUG"] = workspace_slug
        provider = PlaneProvider(config)

    # Step 2: Find or create project
    if not project_id:
        proj = provider.find_project(project_name)
        if proj:
            project_id = proj["id"]
            log.info(f"  Found project: {project_name} ({project_id[:8]}...)")
        else:
            result = provider.create_project(project_name, description)
            if isinstance(result, dict) and "error" not in result and "id" in result:
                project_id = result["id"]
                log.success(f"  Created project: {project_name} ({project_id[:8]}...)")
            else:
                log.warn(f"  Could not create project: {result.get('message', result)}")
                log.info("  Set PLANE_PROJECT_ID in config/.env manually")
                return

        # Update config with the real project ID
        config.project_id = project_id
        os.environ["PLANE_PROJECT_ID"] = project_id
        provider = PlaneProvider(config)

    # Step 3: Save env vars to config/.env
    env_file = tool_dir / "config" / ".env"
    _update_env_file(env_file, {
        "PLANE_API_KEY": plane_key,
        "PLANE_BASE_URL": plane_base,
        "PLANE_WORKSPACE_SLUG": workspace_slug,
        "PLANE_PROJECT_ID": project_id,
    })
    log.info(f"  Saved Plane config to {env_file}")

    # Step 4: Set up board infrastructure (states, labels, pages, cycle)
    from opensepia.board_adapter_plane import PlaneBoardAdapter
    adapter = PlaneBoardAdapter(
        tool_dir / "project" / "workspace",
        tool_dir / "project",
        config,
    )

    agents_config = {"agents": {aid: {} for aid in agent_ids}}
    adapter.ensure_board_ready(agents_config)

    # Create first cycle (Sprint 1)
    cycle_id = provider.get_or_create_cycle(1)
    if cycle_id:
        log.info("  Created Sprint 1 cycle")

    # Seed initial work items in Plane
    for story_id, title, priority in [
        ("STORY-001", "Define MVP scope", "high"),
        ("STORY-002", "Set up development environment", "medium"),
    ]:
        existing = provider.find_issue_by_id(story_id)
        if not existing:
            result = provider.create_work_item(story_id, title, priority=priority)
            if isinstance(result, dict) and "id" in result and cycle_id:
                provider.assign_to_cycle(result["id"], cycle_id)

    # Seed project description page
    provider.update_page("project-description",
                         f"# {project_name}\n\n{description}")

    log.success("  Plane.so setup complete!")
    log.info(f"  Workspace: {workspace_slug}")
    log.info(f"  Project:   {project_name}")
    log.info(f"  URL:       {plane_base}")


def _update_env_file(env_file: Path, values: dict[str, str]) -> None:
    """Update or add key=value pairs in a .env file."""
    existing_lines: list[str] = []
    if env_file.exists():
        existing_lines = env_file.read_text(encoding="utf-8").splitlines()

    keys_written: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                new_lines.append(f"{key}={values[key]}")
                keys_written.add(key)
                continue
        new_lines.append(line)

    # Append any values not already in the file
    for key, value in values.items():
        if key not in keys_written:
            new_lines.append(f"{key}={value}")

    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def cmd_reset(argv: list[str]) -> None:
    """Reset project — clears board, workspace, and logs. Run 'opensepia init' after."""
    import shutil as _shutil

    parser = argparse.ArgumentParser(prog="opensepia reset", description="Reset project")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    args = parser.parse_args(argv)

    tool_dir = Path(__file__).parent.parent.parent
    project_dir = tool_dir / "project"

    if not args.yes:
        log.warn("This will delete ALL project data:")
        log.info(f"  - {project_dir / 'board'}/     (sprint, backlog, inbox, decisions)")
        log.info(f"  - {project_dir / 'workspace'}/  (all agent-written code)")
        log.info(f"  - {project_dir / 'logs'}/       (cycle logs, daemon logs)")
        log.info(f"  - project.yaml sprint/cycle counters")
        log.info("")
        confirm = input("  Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            log.info("Aborted.")
            return

    # Stop daemon if running
    try:
        from opensepia.daemon import stop_daemon, get_daemon_status
        state = get_daemon_status()
        if state.is_process_alive():
            log.info("Stopping daemon...")
            stop_daemon()
    except (ImportError, RuntimeError, OSError) as e:
        log.warn(f"Could not stop daemon: {e}")

    # Clean up lockfiles and daemon state
    for name in ["daemon.lock", "daemon_state.json", "cycle_state.json",
                  "dev-team.lock", "minimal.lock", "all.lock", "security.lock"]:
        p = project_dir / "logs" / name
        if p.exists():
            p.unlink(missing_ok=True)
        p2 = tool_dir / "logs" / name
        if p2.exists():
            p2.unlink(missing_ok=True)

    # Clear board
    board = project_dir / "board"
    if board.exists():
        _shutil.rmtree(board)
    board.mkdir(parents=True, exist_ok=True)
    log.success("Board cleared")

    # Clear entire workspace
    workspace = project_dir / "workspace"
    if workspace.exists():
        _shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    log.success("Workspace cleared")

    # Clear logs
    logs = project_dir / "logs"
    if logs.exists():
        _shutil.rmtree(logs)
    logs.mkdir(parents=True, exist_ok=True)
    log.success("Logs cleared")

    # Reset project.yaml counters (keep project section empty for init to fill)
    import yaml as _yaml
    project_file = project_dir / "project.yaml"
    if project_file.exists():
        try:
            with open(project_file, "r", encoding="utf-8") as f:
                cfg = _yaml.safe_load(f) or {}
            cfg["sprint"] = {"current_sprint": 1, "current_cycle": 0}
            cfg["project"] = {}
            with open(project_file, "w", encoding="utf-8") as f:
                _yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            log.success("project.yaml reset")
        except (_yaml.YAMLError, OSError) as e:
            log.warn(f"Could not reset project.yaml: {e}")

    log.info("")
    log.success("Reset complete. Run 'opensepia init <name> <description>' to start a new project.")


def cmd_setup(argv: list[str]) -> None:
    """Guided first-run setup wizard."""
    import shutil as _shutil
    import subprocess

    tool_dir = Path(__file__).parent.parent.parent

    log.banner(["OpenSepia — Setup Wizard"])
    log.info("")

    # Step 1: Check Claude CLI
    log.header("1. Claude Code CLI")
    if check_claude_cli():
        try:
            result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=CLI_CHECK_TIMEOUT)
            version = result.stdout.strip() or "installed"
            log.success(f"Claude CLI: {version}")
        except (subprocess.SubprocessError, OSError):
            log.success("Claude CLI: found")
    else:
        log.error("Claude Code CLI not found")
        log.info("Install: npm install -g @anthropic-ai/claude-code")
        log.info("Then: claude login")
        log.info("")
        confirm = input("  Continue without Claude CLI? (yes/no): ")
        if confirm.lower() != "yes":
            return

    # Step 2: Project init
    log.header("2. Project")
    project_dir = tool_dir / "project"
    board_exists = (project_dir / "board" / "sprint.md").exists()

    if board_exists:
        try:
            config = OrchestratorConfig.load()
            name = config.project.get("project", {}).get("name", "?")
            log.success(f"Project already initialized: {name}")
        except ConfigError:
            board_exists = False

    if not board_exists:
        name = input("  Project name: ").strip()
        if not name:
            name = "My Project"
        desc = input("  Description: ").strip()
        if not desc:
            desc = "New project"
        cmd_init([name, desc])

    # Step 3: Git (optional)
    log.header("3. Git (optional)")
    workspace = project_dir / "workspace"
    git_dir = workspace / ".git"

    if git_dir.exists():
        log.success("Workspace git: already initialized")
    else:
        confirm = input("  Set up git for the workspace? (yes/no): ").strip().lower()
        if confirm == "yes":
            workspace.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True)
            repo_url = input("  Remote repo URL (or Enter to skip): ").strip()
            if repo_url:
                subprocess.run(
                    ["git", "remote", "add", "origin", repo_url],
                    cwd=str(workspace), capture_output=True,
                )
                log.success(f"Git initialized with remote: {repo_url}")
            else:
                log.success("Git initialized (no remote — add later with git remote add origin <url>)")
        else:
            log.info("Skipped — agents will work without git sync")

    # Step 4: Provider (optional)
    log.header("4. Provider (optional)")
    env_file = tool_dir / "config" / ".env"

    if env_file.exists():
        import os
        # Quick check if tokens are set
        env_content = env_file.read_text(encoding="utf-8")
        has_gl = "GITLAB_TOKEN=" in env_content and "INSERT" not in env_content
        has_gh = "GITHUB_TOKEN=" in env_content and "INSERT" not in env_content
        if has_gl or has_gh:
            provider = "GitLab" if has_gl else "GitHub"
            log.success(f"Provider configured: {provider}")
        else:
            log.info(f"Edit config/.env with your GitLab/GitHub tokens")
            log.info(f"File: {env_file}")
    else:
        env_example = tool_dir / "config" / ".env.example"
        if env_example.exists():
            _shutil.copy2(env_example, env_file)
            log.info(f"Created config/.env from template")
            log.info(f"Edit it with your tokens: {env_file}")
        else:
            log.info("No config/.env found — create from config/.env.example")

    # Done
    log.banner(["Setup complete!"])
    log.info("")
    log.info("Next: opensepia start")
    log.info("")
