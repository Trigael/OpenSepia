"""Interaction commands: board, message, config."""

import os
import argparse
from pathlib import Path

from opensepia import log
from opensepia.config import OrchestratorConfig
from opensepia.errors import ConfigError


def cmd_board(argv: list[str]) -> None:
    """Show current board state."""
    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        log.error(str(e))
        return

    board_dir = config.board_dir
    sprint_path = board_dir / "sprint.md"

    if not sprint_path.exists():
        log.info("No sprint board yet. Run: opensepia init <name>")
        return

    content = sprint_path.read_text(encoding="utf-8")

    # Parse into sections
    log.header("Sprint Board")
    current_section = ""
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            log.info(stripped)
        elif stripped.startswith("## "):
            current_section = stripped
            print()
            log.info(stripped)
        elif stripped.startswith("- ["):
            # Checkbox item
            done = "[x]" in stripped or "[X]" in stripped
            marker = "+" if done else "-"
            text = stripped[5:].strip() if len(stripped) > 5 else stripped
            log.info(f"  {marker} {text}")
        elif stripped.startswith("**") and ":" in stripped:
            log.detail(f"    {stripped}")

    # Show backlog count
    backlog_path = board_dir / "backlog.md"
    if backlog_path.exists():
        import re
        backlog = backlog_path.read_text(encoding="utf-8")
        story_count = len(re.findall(r"###\s+(STORY|BUG)-\d+", backlog))
        print()
        log.info(f"Backlog: {story_count} stories/bugs")

    print()


def cmd_message(argv: list[str]) -> None:
    """Send a message to an agent's inbox."""
    parser = argparse.ArgumentParser(prog="opensepia message", description="Send a message to an agent")
    parser.add_argument("agent", help="Agent ID (po, pm, dev1, dev2, devops, tester, sec_analyst, sec_engineer, sec_pentester)")
    parser.add_argument("text", nargs="+", help="Message text")
    args = parser.parse_args(argv)

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        log.error(str(e))
        return

    known = set(config.get_all_agent_ids())
    if args.agent not in known:
        log.error(f"Unknown agent: {args.agent}")
        log.info(f"Valid agents: {', '.join(sorted(known))}")
        return

    inbox_path = config.board_dir / "inbox" / f"{args.agent}.md"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)

    message = " ".join(args.text)
    entry = f"\n## Message from Human\n{message}\n"

    with open(inbox_path, "a", encoding="utf-8") as f:
        f.write(entry)

    agent_name = config.agents["agents"][args.agent].get("name", args.agent)
    log.success(f"Message sent to {agent_name} ({args.agent})")
    log.detail(f"  Inbox: {inbox_path}")


def cmd_config(argv: list[str]) -> None:
    """Show editable configuration."""
    section = argv[0] if argv else "all"

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return

    tool_dir = config.tool_dir
    project_dir = config.project_dir

    if section in ("all", "project"):
        proj = config.project.get("project", {})
        sprint = config.project.get("sprint", {})

        print()
        print("  Project Settings")
        print(f"  {'─' * 50}")
        print(f"  Name:         {proj.get('name', '(not set)')}")
        print(f"  Description:  {proj.get('description', '(not set)')}")

        tech = proj.get("tech_stack", {})
        if tech:
            print(f"  Tech stack:   {tech.get('language', '-')} / {tech.get('framework', '-')}")
            print(f"                {tech.get('database', '-')} / {tech.get('deployment', '-')}")

        print(f"  Sprint:       {sprint.get('current_sprint', 1)}")
        print(f"  Cycle:        {sprint.get('current_cycle', 0)}")
        print(f"  Cycles/sprint:{sprint.get('cycles_per_sprint', 10)}")
        print(f"  Edit:         {project_dir / 'project.yaml'}")

    if section in ("all", "agents"):
        modes = config.agents.get("modes", {})
        exec_cfg = config.agents.get("execution", {})

        print()
        print("  Agent Modes")
        print(f"  {'─' * 50}")
        for name, defn in modes.items():
            agents = defn.get("agents", [])
            aliases = defn.get("aliases", [])
            default = " (default)" if defn.get("default") else ""
            alias_str = f" (alias: {', '.join(aliases)})" if aliases else ""
            print(f"  {name:<14} {len(agents)} agents{default}{alias_str}")
            print(f"                 {', '.join(agents)}")

        print()
        print("  Execution Parameters")
        print(f"  {'─' * 50}")
        print(f"  Timeout:         {exec_cfg.get('timeout', 900)}s per agent")
        print(f"  Max retries:     {exec_cfg.get('max_retries', 1)}")
        print(f"  Retry delay:     {exec_cfg.get('retry_delay', 30)}s")
        print(f"  Pause between:   {exec_cfg.get('pause_between_agents', 0)}s")

        overrides = exec_cfg.get("overrides", {})
        if overrides and isinstance(overrides, dict) and any(overrides.values()):
            print(f"  Per-agent:")
            for aid, ov in overrides.items():
                if isinstance(ov, dict) and ov:
                    print(f"    {aid}: {ov}")

        print(f"  Edit:            {tool_dir / 'config' / 'agents.yaml'}")

    if section in ("all", "env"):
        print()
        print("  Provider Integration")
        print(f"  {'─' * 50}")

        gl_url = os.environ.get("GITLAB_URL", "")
        gl_token = os.environ.get("GITLAB_TOKEN", "")
        gl_project = os.environ.get("GITLAB_PROJECT_ID", "")
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        gh_owner = os.environ.get("GITHUB_OWNER", "")
        gh_repo = os.environ.get("GITHUB_REPO", "")
        git_url = os.environ.get("GIT_REPO_URL", "")

        if gl_url and gl_token:
            print(f"  GitLab:       {gl_url}")
            print(f"  Project:      {gl_project}")
            print(f"  Token:        {'*' * 8}...{gl_token[-4:]}" if len(gl_token) > 4 else "  Token:        (set)")
        elif gh_token and gh_repo:
            print(f"  GitHub:       {gh_owner}/{gh_repo}")
            print(f"  Token:        {'*' * 8}...{gh_token[-4:]}" if len(gh_token) > 4 else "  Token:        (set)")
        else:
            print(f"  Provider:     (not configured)")
            print(f"  Set GitLab or GitHub credentials in config/.env")

        if git_url:
            print(f"  Git repo:     {git_url}")
        else:
            print(f"  Git repo:     (not configured)")

        print(f"  Edit:         {tool_dir / 'config' / '.env'}")

    if section not in ("all", "project", "agents", "env"):
        print(f"Unknown config section: {section}")
        print(f"Valid: project, agents, env (or no argument for all)")
        return

    print()
    print(f"  Editable files:")
    print(f"    {str(project_dir / 'project.yaml'):<50} Project name, tech stack, sprint")
    print(f"    {str(tool_dir / 'config' / 'agents.yaml'):<50} Modes, execution params, agent prompts")
    print(f"    {str(tool_dir / 'config' / '.env'):<50} Provider tokens (GitLab/GitHub)")
    print()
