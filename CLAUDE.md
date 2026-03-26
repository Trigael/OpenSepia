# AI Dev Team — Claude Code Project Guide

## What This Is

Autonomous AI development team framework. 9 Claude-powered agents work as an agile team: plan sprints, write code, review, test, handle security, deploy. Orchestrated by cron, communicates via Markdown files.

## Project Structure

```
opensepia/                  # App source code (single package)
  cli.py                    # Command router (entry point)
  config.py                 # Config loading + mode resolution
  errors.py                 # Error hierarchy
  pipeline.py               # Step protocol + Pipeline runner
  daemon.py                 # Background daemon
  agents/                   # Agent execution
    context.py, invoker.py, parser.py, writer.py, workspace.py
  board/                    # Board management
    sync.py, comments.py, restore.py
  steps/                    # Pipeline steps (11 steps)
  integrations/             # Provider APIs (GitLab, GitHub, git, docker)

config/                     # Tool configuration
  agents.yaml               # Agent definitions, modes, execution params
  .env                      # Credentials (gitignored)

project/                    # The product being built (swappable, separate repo)
  project.yaml              # Project name, tech stack, sprint state
  board/                    # Agent progress (sprint.md, backlog.md, inbox/)
  workspace/                # Code the agents write
  logs/                     # Cycle logs

tests/                      # Test suite
bin/opensepia               # CLI entry point
scripts/                    # Legacy CLI wrappers
```

The `project/` folder is the product OpenSepia is working on. It can be swapped out for a different project — just point to a different folder with the same structure (board/, workspace/, project.yaml).

## Key Conventions

- Board state lives in `project/board/*.md`
- Agents communicate via `project/board/inbox/{agent_id}.md`
- Story IDs: `STORY-XXX`, Bug IDs: `BUG-XXX`
- Status flow: TODO → IN_PROGRESS → REVIEW → TESTING → DONE
- Modes and execution params defined in `config/agents.yaml`

## Running

```bash
opensepia help                   # Show all commands
opensepia start                  # Start background daemon
opensepia status                 # Check status
opensepia logs -f                # Follow live logs
opensepia stop                   # Stop daemon
opensepia run dev-team           # Single cycle
opensepia run po --dry-run       # Preview without calling Claude
python3 -m pytest tests/ -v      # Run tests
```

## Architecture

Pipeline pattern — each step implements a `Step` protocol:

```
BoardHealth → SprintCheck → Snapshot → AgentRunner → SprintSync →
StandupSync → MergeMRs → GitSync → BoardSync → CycleLog → Alerting
```

## Code Style

- Python 3.10+, no external deps beyond pyyaml
- All imports use `opensepia.*` package paths
- All provider integrations go through BoardProvider ABC

## Tests

`python3 -m pytest tests/ -v` — 142 tests, no external API calls.
