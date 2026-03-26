# AI Dev Team — Claude Code Project Guide

## What This Is

Autonomous AI development team framework. 9 Claude-powered agents work as an agile team: plan sprints, write code, review, test, handle security, deploy. Orchestrated by cron, communicates via Markdown files.

## Project Structure

### Core Packages

- `orchestrator/` — Pipeline-based orchestrator (replaces bash script)
  - `cli.py` — argparse CLI, mode routing, entry point
  - `config.py` — Centralized config loading (agents.yaml, project.yaml, .env)
  - `errors.py` — Error hierarchy (ConfigError, AgentError, GitSyncError, etc.)
  - `lockfile.py` — PID-based process lock management
  - `pipeline.py` — Step protocol + Pipeline runner with error handling
  - `steps/` — Individual pipeline steps (board_health, sprint_check, agent_runner, standup_sync, merge_mrs, git_sync, board_sync, logging_step, alerting)

- `agent/` — Agent execution modules
  - `context.py` — Build agent prompt from board state, workspace, inbox
  - `invoker.py` — Call Claude Code CLI with retry logic
  - `parser.py` — Parse `---FILES---` output format
  - `writer.py` — Apply agent output to disk with security checks
  - `workspace.py` — Directory tree listing for context

### Scripts (thin wrappers / standalone tools)

- `scripts/orchestrator_cli.sh` — Shim that delegates to `python -m orchestrator`
- `scripts/run_agent_cli.py` — Agent runner CLI (imports from `agent/` package)
- `scripts/sync_board.py` — Syncs board/backlog.md + sprint.md → provider issues
- `scripts/sync_comments.py` — Syncs agent messages → issue comments
- `scripts/restore_board.py` — Board health check and restore from snapshot/provider
- `scripts/merge_approved_mrs.py` — Auto-merges approved MRs/PRs

### Integrations

- `integrations/base.py` — BoardProvider ABC (shared interface for GitLab/GitHub)
- `integrations/providers/gitlab.py` — GitLab API v4 implementation
- `integrations/providers/github.py` — GitHub REST API implementation
- `integrations/git_client.py` — Git operations (branch, commit, push)
- `integrations/docker_client.py` — Docker/docker-compose operations
- `integrations/logging_config.py` — Shared logging + env loader

### Configuration

- `config/agents.yaml` — Agent definitions and system prompts (9 agents)
- `config/project.yaml` — Sprint counter, project description, tech stack
- `config/.env` — Tokens and credentials (gitignored, see .env.example)

## Key Conventions

- Board state lives in `board/*.md` files (sprint.md, backlog.md, etc.)
- Agents communicate via `board/inbox/{agent_id}.md`
- Story IDs: `STORY-XXX`, Bug IDs: `BUG-XXX`
- Status flow: TODO → IN_PROGRESS → REVIEW → TESTING → DONE
- Labels on GitLab/GitHub: `status::todo`, `priority::high`, etc.
- Provider auto-detection: GitLab if GITLAB_URL+GITLAB_TOKEN set, GitHub if GITHUB_TOKEN+GITHUB_REPO set

## Running

```bash
# Initialize project
python3 scripts/init_project.py "Name" "Description"

# Run one cycle (all core agents) — preferred
python3 -m orchestrator dev-team

# Alternative (via shim, backward compatible)
./scripts/orchestrator_cli.sh dev-team

# Run single agent
python3 -m orchestrator po

# Dry run (show context without calling Claude)
python3 -m orchestrator dev-team --dry-run

# Run tests
python3 -m pytest tests/ -v
```

## Architecture

The orchestrator uses a pipeline pattern. Each step implements a `Step` protocol:

```
Pipeline: BoardHealth → SprintCheck → Snapshot → AgentRunner → SprintSync → StandupSync → MergeMRs → GitSync → BoardSync → CycleLog → Alerting
```

Non-critical steps log errors and continue. Critical steps (config, lock) abort the pipeline. All errors are collected in `PipelineContext.errors`.

## Code Style

- Python 3.10+ with modern type hints (list[str] not List[str])
- Shared logging via `integrations/logging_config.py` — use `setup_logging("name")`
- Shared env loading via `load_env()` from same module
- No external dependencies beyond pyyaml (API calls use urllib)
- All provider integrations go through BoardProvider ABC

## Tests

Tests in `tests/` — run with `python3 -m pytest tests/ -v`. No external API calls, all mocked.
