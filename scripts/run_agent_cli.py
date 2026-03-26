#!/usr/bin/env python3
"""
AI Dev Team — Agent Runner (Claude Code CLI version)
Uses 'claude' CLI instead of API. Works with Pro/Max subscription.

Usage:
  python run_agent_cli.py --agent dev --verbose
  python run_agent_cli.py --all
"""

import os
import re
import sys
import json
import yaml
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

# Uses module-level logger, configured by caller
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.logging_config import load_env
load_env()

from agent.context import build_agent_context
from agent.invoker import invoke_agent, DEFAULT_MAX_RETRIES, DEFAULT_RETRY_DELAY
from agent.writer import apply_output, read_file_safe, write_file, archive_inbox
from agent.parser import parse_files_section

# =============================================================================
# Constants
# =============================================================================
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
BOARD_DIR = BASE_DIR / "board"
WORKSPACE_DIR = BASE_DIR / "workspace"
LOGS_DIR = BASE_DIR / "logs" / "runs"
STANDUP_FILE = BOARD_DIR / "standup.md"

MAX_STANDUP_CHARS = 2000
MAX_INBOX_CHARS = 1500


# =============================================================================
# Helper functions
# =============================================================================
def load_config() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load agent and project configuration."""
    with open(CONFIG_DIR / "agents.yaml", "r") as f:
        agents_config = yaml.safe_load(f)
    with open(CONFIG_DIR / "project.yaml", "r") as f:
        project_config = yaml.safe_load(f)
    return agents_config, project_config


def initialize_standup_file(sprint_num: int, cycle: int) -> None:
    """
    Initialize standup file for a new cycle.
    Archive old standup, keep last cycle as context.
    FIX: Removes nested <details> blocks to prevent accumulation.
    """
    old_content = read_file_safe(STANDUP_FILE)

    if old_content.strip():
        # Archive COMPLETE old standup
        archive_dir = BOARD_DIR / "archive" / "standup"
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        write_file(archive_dir / f"s{sprint_num}_c{cycle - 1}_{timestamp}.md", old_content)

        # Keep last cycle as context — WITHOUT nested <details>!
        details_pos = old_content.find("<details>")
        if details_pos > 0:
            clean_content = old_content[:details_pos].strip()
        else:
            clean_content = old_content.strip()

        if len(clean_content) > MAX_INBOX_CHARS:
            clean_content = clean_content[:MAX_INBOX_CHARS] + "\n_(truncated)_"

        prev_section = f"\n\n<details><summary>Previous cycle</summary>\n\n{clean_content}\n</details>\n"
    else:
        prev_section = ""

    header = f"# Standup — Sprint {sprint_num}, Cycle {cycle}\n"
    write_file(STANDUP_FILE, header + prev_section + "\n")


# =============================================================================
# Logging
# =============================================================================
def log_run(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Log run results."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    log_entry = {
        "timestamp": timestamp,
        "method": "claude-code-cli",
        "agents": [
            {
                "agent": r["agent_name"],
                "context_chars": r.get("context_size", 0),
                "response_chars": r.get("response_size", 0),
                **({"error": r["error"]} if r.get("error") else {}),
            }
            for r in results
        ],
    }

    # Write log
    log_path = LOGS_DIR / f"{timestamp}.json"
    with open(log_path, "w") as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)

    # Symlink to latest
    latest = LOGS_DIR / "latest.json"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(log_path.name)

    return log_entry


# =============================================================================
# Sprint sync
# =============================================================================
def sync_sprint_from_board(project_config: dict[str, Any]) -> None:
    """
    Synchronize sprint number from board/sprint.md to project.yaml.
    Agents can advance the sprint earlier than cycle 10 —
    this function ensures project.yaml is always up to date.
    """
    sprint_md = read_file_safe(BOARD_DIR / "sprint.md")
    if not sprint_md:
        return

    all_sprints = re.findall(r"#\s*Sprint\s+(\d+)", sprint_md)
    if not all_sprints:
        return

    board_sprint = max(int(s) for s in all_sprints)
    sprint_cfg = project_config.get("sprint", {})
    yaml_sprint = sprint_cfg.get("current_sprint", 1)

    if board_sprint != yaml_sprint:
        sprint_cfg["current_sprint"] = board_sprint
        if board_sprint > yaml_sprint:
            sprint_cfg["current_cycle"] = 1
            print(f"   \U0001f504 Sprint sync: {yaml_sprint} -> {board_sprint} (cycle reset to 1)")
        else:
            print(f"   \U0001f504 Sprint sync: {yaml_sprint} -> {board_sprint}")
        project_config["sprint"] = sprint_cfg
        with open(CONFIG_DIR / "project.yaml", "w") as f:
            yaml.dump(project_config, f, default_flow_style=False, allow_unicode=True)


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="AI Dev Team — Agent Runner (Claude Code CLI)")
    parser.add_argument("--agent", "-a", type=str, default=None,
                        help="Run a specific agent (po, pm, dev1, dev2, devops, tester, sec_analyst, sec_engineer, sec_pentester)")
    parser.add_argument("--all", action="store_true",
                        help="Run all agents (9) in order")
    parser.add_argument("--minimal", action="store_true",
                        help="Minimal mode: only PO, Dev1, Tester (3 agents)")
    parser.add_argument("--dev-team", action="store_true",
                        help="Dev team: PO, PM, Dev1, Dev2, DevOps, Tester (6 agents)")
    parser.add_argument("--security", action="store_true",
                        help="Security team only: Analyst, Engineer, Pentester (3 agents)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only display context, do not call Claude")
    parser.add_argument("--no-increment", action="store_true",
                        help="Do not increment cycle number (for retrospective)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    # Load configuration
    agents_config, project_config = load_config()

    # Determine agents to run
    if args.agent:
        agent_ids = [args.agent]
    elif args.minimal:
        agent_ids = agents_config["global"].get("minimal_order", ["po", "dev1", "tester"])
    elif args.dev_team:
        agent_ids = agents_config["global"].get("dev_team_order", ["po", "pm", "dev1", "dev2", "devops", "tester"])
    elif args.security:
        agent_ids = agents_config["global"].get("security_order", ["sec_analyst", "sec_engineer", "sec_pentester"])
    elif args.all:
        agent_ids = agents_config["global"]["execution_order"]
    else:
        parser.print_help()
        print("\n\U0001f4a1 Modes:")
        print("   --minimal    3 agents (PO, Dev1, Tester)")
        print("   --dev-team   6 agents (core dev team)")
        print("   --security   3 agents (security team)")
        print("   --all        9 agents (all)")
        sys.exit(1)

    # Validation
    for aid in agent_ids:
        if aid not in agents_config["agents"]:
            print(f"ERROR: Unknown agent '{aid}'")
            sys.exit(1)

    # Increment cycle (unless --no-increment or --dry-run)
    sprint_cfg = project_config.get("sprint", {})
    if args.no_increment or args.dry_run:
        cycle = sprint_cfg.get("current_cycle", 0)
    else:
        cycle = sprint_cfg.get("current_cycle", 0) + 1
        sprint_cfg["current_cycle"] = cycle
        with open(CONFIG_DIR / "project.yaml", "w") as f:
            yaml.dump(project_config, f, default_flow_style=False, allow_unicode=True)

    sprint_num = sprint_cfg.get("current_sprint", 1)

    # Initialize standup file for new cycle (not during dry-run!)
    if not args.dry_run:
        initialize_standup_file(sprint_num, cycle)

    print(f"\n\U0001f916 AI Dev Team — Cycle {cycle}")
    print(f"   Method: Claude Code CLI")
    print(f"   Agents: {', '.join(agent_ids)}")
    print(f"{'─'*50}")

    # Dry run?
    if args.dry_run:
        for aid in agent_ids:
            ctx = build_agent_context(aid, agents_config, project_config,
                                       BOARD_DIR, WORKSPACE_DIR, BASE_DIR)
            print(f"\n--- {aid} ({len(ctx)} chars) ---")
            print(ctx[:1500] + "..." if len(ctx) > 1500 else ctx)
        return

    # Run agents
    results: list[dict[str, Any]] = []
    MAX_RETRIES = DEFAULT_MAX_RETRIES
    RETRY_DELAY = DEFAULT_RETRY_DELAY

    for i, aid in enumerate(agent_ids):
        agent_name = agents_config["agents"][aid]["name"]
        agent_color = agents_config["agents"][aid]["color"]

        print(f"\n{agent_color} [{i+1}/{len(agent_ids)}] {agent_name}...")

        success = False
        last_error = None

        for attempt in range(1 + MAX_RETRIES):
            try:
                # Build context
                context = build_agent_context(aid, agents_config, project_config,
                                               BOARD_DIR, WORKSPACE_DIR, BASE_DIR)
                # Invoke agent
                agent_result = invoke_agent(
                    agent_id=aid,
                    context=context,
                    base_dir=BASE_DIR,
                    agent_name=f"{agent_color} {agent_name}",
                    verbose=args.verbose,
                )

                # Convert AgentResult to dict for backward compatibility
                result_dict = {
                    "agent_id": agent_result.agent_id,
                    "agent_name": agent_result.agent_name,
                    "response": agent_result.response,
                    "timestamp": agent_result.timestamp,
                    "context_size": agent_result.context_size,
                    "response_size": agent_result.response_size,
                }

                if agent_result.error or "ERROR" in agent_result.response:
                    last_error = (agent_result.error or agent_result.response[:100])
                    if attempt < MAX_RETRIES:
                        print(f"   \u26a0\ufe0f  {last_error} — retrying in {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                        continue
                    else:
                        print(f"   \u274c {last_error} (after {attempt + 1} attempts)")
                        result_dict["error"] = last_error
                        results.append(result_dict)
                        # Archive inbox even on agent error
                        inbox_path = BOARD_DIR / "inbox" / f"{aid}.md"
                        inbox_content = read_file_safe(inbox_path)
                        if inbox_content.strip():
                            archive_inbox(aid, inbox_content, BOARD_DIR)
                            write_file(inbox_path, "")
                else:
                    if attempt > 0:
                        print(f"   \U0001f504 Retry successful (attempt {attempt + 1})")
                    files_written = apply_output(
                        aid, result_dict, agents_config,
                        BASE_DIR, BOARD_DIR, STANDUP_FILE,
                        verbose=args.verbose,
                    )
                    results.append(result_dict)
                    print(f"   \u2705 Done — {files_written} files")
                    success = True

                break  # Success or final error — end retry

            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES:
                    print(f"   \u26a0\ufe0f  Error: {e} — retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    print(f"   \u274c Error: {e} (after {attempt + 1} attempts)")
                    logger.exception(f"Error for {aid}")
                    results.append({
                        "agent_id": aid,
                        "agent_name": agent_name,
                        "response": "",
                        "timestamp": datetime.now().isoformat(),
                        "context_size": 0,
                        "response_size": 0,
                        "error": last_error,
                    })
                    # Archive inbox even on error
                    inbox_path = BOARD_DIR / "inbox" / f"{aid}.md"
                    inbox_content = read_file_safe(inbox_path)
                    if inbox_content.strip():
                        archive_inbox(aid, inbox_content, BOARD_DIR)
                        write_file(inbox_path, "")

    # Sync sprint number from board/sprint.md -> project.yaml
    sync_sprint_from_board(project_config)

    # Logging
    if results:
        log = log_run(results)
        ok_count = sum(1 for r in results if not r.get("error"))
        err_count = sum(1 for r in results if r.get("error"))
        print(f"\n{'─'*50}")
        print(f"\u2705 Cycle {cycle} completed")
        print(f"   Successful agents: {ok_count}/{len(agent_ids)}")
        if err_count:
            failed = [r["agent_name"] for r in results if r.get("error")]
            print(f"   \u274c Failed (after retry): {', '.join(failed)}")


if __name__ == "__main__":
    main()
