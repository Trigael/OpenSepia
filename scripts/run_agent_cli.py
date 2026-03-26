#!/usr/bin/env python3
"""
AI Dev Team — Agent Runner (Legacy CLI)

Thin wrapper around the orchestrator for backward compatibility.
Prefer using: opensepia run [mode] or python -m orchestrator [mode]
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Dev Team — Agent Runner (legacy, use 'opensepia run' instead)"
    )
    parser.add_argument("--agent", "-a", type=str, default=None,
                        help="Run a specific agent")
    parser.add_argument("--all", action="store_true",
                        help="Run all agents (9)")
    parser.add_argument("--minimal", action="store_true",
                        help="Minimal mode (3 agents)")
    parser.add_argument("--dev-team", action="store_true",
                        help="Dev team (6 agents)")
    parser.add_argument("--security", action="store_true",
                        help="Security team (3 agents)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show context without calling Claude")
    parser.add_argument("--no-increment", action="store_true",
                        help="Don't increment cycle number")

    args = parser.parse_args()

    # Map legacy flags to mode name
    if args.agent:
        mode = args.agent
    elif args.all:
        mode = "all"
    elif args.minimal:
        mode = "minimal"
    elif args.dev_team:
        mode = "dev-team"
    elif args.security:
        mode = "security"
    else:
        parser.print_help()
        print("\nPrefer: opensepia run [mode]")
        sys.exit(1)

    # Delegate to orchestrator CLI
    from orchestrator.cli import cmd_run
    argv = [mode]
    if args.verbose:
        argv.append("--verbose")
    if args.dry_run:
        argv.append("--dry-run")
    if args.no_increment:
        argv.append("--no-increment")
    cmd_run(argv)


if __name__ == "__main__":
    main()
