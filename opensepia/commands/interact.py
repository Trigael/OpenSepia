"""Interaction commands: board, message, config."""

import os
import re
import argparse
import yaml
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

    log.header("Sprint Board")
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            log.info(stripped)
        elif stripped.startswith("## "):
            print()
            log.info(stripped)
        elif stripped.startswith("- ["):
            done = "[x]" in stripped or "[X]" in stripped
            marker = "+" if done else "-"
            text = stripped[5:].strip() if len(stripped) > 5 else stripped
            log.info(f"  {marker} {text}")
        elif stripped.startswith("**") and ":" in stripped:
            log.detail(f"    {stripped}")

    backlog_path = board_dir / "backlog.md"
    if backlog_path.exists():
        backlog = backlog_path.read_text(encoding="utf-8")
        story_count = len(re.findall(r"###\s+(STORY|BUG)-\d+", backlog))
        print()
        log.info(f"Backlog: {story_count} stories/bugs")

    print()


def cmd_message(argv: list[str]) -> None:
    """Send a message to an agent's inbox."""
    parser = argparse.ArgumentParser(prog="opensepia message", description="Send a message to an agent")
    parser.add_argument("agent", help="Agent ID (po, pm, dev1, dev2, devops, tester, ...)")
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


def cmd_config(argv: list[str]) -> None:
    """Show or set configuration."""
    if argv and argv[0] == "set":
        _config_set(argv[1:])
        return

    _config_show(argv)


# =============================================================================
# config set
# =============================================================================

# Settable keys and where they live
_SETTABLE = {
    # project.yaml keys
    "project.name": ("project", ["project", "name"]),
    "project.description": ("project", ["project", "description"]),
    "project.tech_stack.language": ("project", ["project", "tech_stack", "language"]),
    "project.tech_stack.framework": ("project", ["project", "tech_stack", "framework"]),
    "project.tech_stack.database": ("project", ["project", "tech_stack", "database"]),
    "project.tech_stack.deployment": ("project", ["project", "tech_stack", "deployment"]),
    "sprint.cycles_per_sprint": ("project", ["sprint", "cycles_per_sprint"]),
    # agents.yaml keys
    "execution.timeout": ("agents", ["execution", "timeout"]),
    "execution.max_retries": ("agents", ["execution", "max_retries"]),
    "execution.retry_delay": ("agents", ["execution", "retry_delay"]),
    "execution.pause_between_agents": ("agents", ["execution", "pause_between_agents"]),
}

# Keys that should be stored as integers
_INT_KEYS = {
    "sprint.cycles_per_sprint", "execution.timeout", "execution.max_retries",
    "execution.retry_delay", "execution.pause_between_agents",
}


def _config_set(argv: list[str]) -> None:
    """Set a config value: opensepia config set <key> <value>"""
    if len(argv) < 2:
        log.error("Usage: opensepia config set <key> <value>")
        print()
        log.info("Settable keys:")
        for key in sorted(_SETTABLE):
            log.info(f"  {key}")
        return

    key = argv[0]
    value = " ".join(argv[1:])

    if key not in _SETTABLE:
        log.error(f"Unknown config key: {key}")
        log.info("Valid keys:")
        for k in sorted(_SETTABLE):
            log.info(f"  {k}")
        return

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        log.error(str(e))
        return

    file_type, path = _SETTABLE[key]

    if key in _INT_KEYS:
        try:
            value = int(value)
        except ValueError:
            log.error(f"'{key}' must be an integer, got: {value}")
            return

    if file_type == "project":
        data = config.project
        file_path = config.project_dir / "project.yaml"
    else:
        data = config.agents
        file_path = config.tool_dir / "config" / "agents.yaml"

    # Navigate to find old value
    node = data
    for k in path[:-1]:
        if k not in node:
            node[k] = {}
        node = node[k]
    old_value = node.get(path[-1])

    if file_type == "agents":
        # For agents.yaml: use regex replacement to preserve formatting
        # (yaml.dump destroys multi-line system_prompt strings)
        leaf_key = path[-1]
        content = file_path.read_text(encoding="utf-8")
        # Match "  key: value" — only lines not starting with #
        pattern = rf"^((?!.*#.*{re.escape(leaf_key)})[ ]*{re.escape(leaf_key)}:\s*)(\S.*)$"
        replacement = rf"\g<1>{value}"
        new_content, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE)
        if count == 0:
            log.error(f"Could not find '{leaf_key}' in agents.yaml")
            return
        file_path.write_text(new_content, encoding="utf-8")
    else:
        # For project.yaml: safe to use yaml.dump (no multi-line strings)
        node[path[-1]] = value
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    log.success(f"{key}: {old_value} -> {value}")


# =============================================================================
# config show
# =============================================================================

def _config_show(argv: list[str]) -> None:
    """Show current configuration."""
    section = argv[0] if argv else "all"

    try:
        config = OrchestratorConfig.load()
    except ConfigError as e:
        log.error(str(e))
        return

    tool_dir = config.tool_dir
    project_dir = config.project_dir

    if section in ("all", "project"):
        proj = config.project.get("project", {})
        sprint = config.project.get("sprint", {})

        log.header("Project Settings")
        log.info(f"Name:         {proj.get('name', '(not set)')}")
        log.info(f"Description:  {proj.get('description', '(not set)')}")

        tech = proj.get("tech_stack", {})
        if tech:
            log.info(f"Tech stack:   {tech.get('language', '-')} / {tech.get('framework', '-')}")
            log.detail(f"              {tech.get('database', '-')} / {tech.get('deployment', '-')}")

        log.info(f"Sprint:       {sprint.get('current_sprint', 1)}")
        log.info(f"Cycle:        {sprint.get('current_cycle', 0)}")
        log.info(f"Cycles/sprint:{sprint.get('cycles_per_sprint', 10)}")

    if section in ("all", "agents"):
        modes = config.agents.get("modes", {})
        exec_cfg = config.agents.get("execution", {})

        log.header("Agent Modes")
        for name, defn in modes.items():
            agents = defn.get("agents", [])
            aliases = defn.get("aliases", [])
            default = " (default)" if defn.get("default") else ""
            alias_str = f" (alias: {', '.join(aliases)})" if aliases else ""
            log.info(f"{name:<14} {len(agents)} agents{default}{alias_str}")
            log.detail(f"               {', '.join(agents)}")

        log.header("Execution Parameters")
        log.info(f"Timeout:         {exec_cfg.get('timeout', 900)}s per agent")
        log.info(f"Max retries:     {exec_cfg.get('max_retries', 1)}")
        log.info(f"Retry delay:     {exec_cfg.get('retry_delay', 30)}s")
        log.info(f"Pause between:   {exec_cfg.get('pause_between_agents', 0)}s")

        overrides = exec_cfg.get("overrides", {})
        if overrides and isinstance(overrides, dict) and any(overrides.values()):
            log.info("Per-agent overrides:")
            for aid, ov in overrides.items():
                if isinstance(ov, dict) and ov:
                    log.info(f"  {aid}: {ov}")

    if section in ("all", "pipeline"):
        pipeline = config.agents.get("pipeline", [])
        log.header("Pipeline Steps")
        if pipeline:
            for i, step_name in enumerate(pipeline, 1):
                log.info(f"  {i:>2}. {step_name}")
        else:
            log.info("  (using defaults — add 'pipeline:' to agents.yaml to customize)")

    if section in ("all", "env"):
        log.header("Provider Integration")

        gl_url = os.environ.get("GITLAB_URL", "")
        gl_token = os.environ.get("GITLAB_TOKEN", "")
        gl_project = os.environ.get("GITLAB_PROJECT_ID", "")
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        gh_owner = os.environ.get("GITHUB_OWNER", "")
        gh_repo = os.environ.get("GITHUB_REPO", "")
        git_url = os.environ.get("GIT_REPO_URL", "")

        if gl_url and gl_token:
            log.info(f"GitLab:       {gl_url}")
            log.info(f"Project:      {gl_project}")
        elif gh_token and gh_repo:
            log.info(f"GitHub:       {gh_owner}/{gh_repo}")
        else:
            log.info("Provider:     (not configured)")

        if git_url:
            log.info(f"Git repo:     {git_url}")
        else:
            log.info("Git repo:     (not configured)")

    if section not in ("all", "project", "agents", "pipeline", "env"):
        log.error(f"Unknown section: {section}")
        log.info("Valid: project, agents, pipeline, env (or omit for all)")
        return

    print()
    log.info("Set values:  opensepia config set <key> <value>")
    log.info("Show keys:   opensepia config set")
    print()
