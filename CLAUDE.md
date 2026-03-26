# AI Dev Team — Claude Code Project Guide

## What This Is

Autonomous AI development team framework. 9 Claude-powered agents work as an agile team: plan sprints, write code, review, test, handle security, deploy. Orchestrated by cron, communicates via Markdown files.

## Project Structure

```
opensepia/                  # Main application package
  cli.py                    # Command router (opensepia entry point)
  config.py                 # Config loading + mode resolution
  errors.py                 # Error hierarchy
  lockfile.py               # PID-based process locks
  pipeline.py               # Step protocol + Pipeline runner
  daemon.py                 # Background daemon
  daemon_state.py           # Persistent daemon state (JSON)
  agents/                   # Agent execution
    context.py              # Build agent prompt from board state
    invoker.py              # Call Claude Code CLI with retry
    parser.py               # Parse ---FILES--- output format
    writer.py               # Apply output to disk with security checks
    workspace.py            # Directory tree listing
  board/                    # Board management
    sync.py                 # Sync board state to provider issues
    comments.py             # Sync comments to/from provider
    restore.py              # Board health check and recovery
  steps/                    # Pipeline steps
    board_health.py, sprint_check.py, agent_runner.py,
    standup_sync.py, merge_mrs.py, git_sync.py,
    board_sync.py, logging_step.py, alerting.py
  integrations/             # Provider APIs
    base.py                 # BoardProvider ABC
    providers/gitlab.py     # GitLab API v4
    providers/github.py     # GitHub REST API
    git_client.py           # Git operations
    docker_client.py        # Docker operations
    logging_config.py       # Shared logging + env loader

config/                     # YAML configuration
  agents.yaml               # Agent definitions, modes, execution params
  project.yaml              # Sprint counter, project metadata
  .env                      # Credentials (gitignored)

board/                      # Runtime board state
  sprint.md, backlog.md     # Sprint and backlog
  inbox/                    # Agent communication
  archive/, .snapshot/      # History and recovery

workspace/                  # Where agents write code
tests/                      # Test suite
scripts/                    # Legacy CLI wrappers
bin/opensepia               # CLI entry point
```

## Key Conventions

- Board state lives in `board/*.md` files (sprint.md, backlog.md, etc.)
- Agents communicate via `board/inbox/{agent_id}.md`
- Story IDs: `STORY-XXX`, Bug IDs: `BUG-XXX`
- Status flow: TODO → IN_PROGRESS → REVIEW → TESTING → DONE
- Provider auto-detection: GitLab if GITLAB_URL+GITLAB_TOKEN set, GitHub if GITHUB_TOKEN+GITHUB_REPO set
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

Non-critical steps log errors and continue. Critical steps abort.

## Code Style

- Python 3.10+ with modern type hints
- No external dependencies beyond pyyaml
- All provider integrations go through BoardProvider ABC
- All imports use `opensepia.*` package paths

## Tests

`python3 -m pytest tests/ -v` — 142 tests, no external API calls.
