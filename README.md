# OpenSepia

**Autonomous software development team powered by Claude AI agents.**

9 specialized AI agents collaborate as a real agile team — they plan sprints, write code, do code reviews, test, handle security audits, and manage deployments. Runs as a background daemon, controllable via CLI.

> No API key needed — runs on Claude Code CLI with a Pro or Max subscription.

---

## How It Works

```
You: opensepia init "My API" "REST API with FastAPI"
     opensepia start

OpenSepia (running in background):
  Every 60 seconds, runs a cycle:

  1. PO reads the board, defines priorities and stories
  2. PM coordinates the sprint, assigns work to developers
  3. Dev1 + Dev2 implement features, write tests, review each other's code
  4. DevOps handles infrastructure and deployment config
  5. Tester runs functional reviews, verifies acceptance criteria
  6. Git sync → feature branch → push → MR/PR → auto-merge
  7. Board sync → issues updated on GitLab/GitHub

You: opensepia status    (check progress anytime)
     opensepia logs -f   (watch live)
     opensepia stop      (when done)
```

Agents communicate via **Markdown inbox files** — messages they send to each other. Each cycle, they read their inbox, do their work, and write to other agents' inboxes.

---

## The Team

### Core Team (default: `dev-team` mode)

| Agent | Role | What they do |
|-------|------|-------------|
| 🟣 **Product Owner** | Strategist | Defines vision, writes user stories, prioritizes backlog |
| 🔵 **Project Manager** | Coordinator | Manages sprint, assigns work, resolves blockers |
| 🟢 **Developer 1** | Full-stack dev | Implements features, writes tests, reviews Dev 2's code |
| 🟩 **Developer 2** | Full-stack dev | Implements features, writes tests, reviews Dev 1's code |
| 🟠 **DevOps Engineer** | Infrastructure | Docker, deployment config, monitoring |
| 🔴 **QA Engineer** | Quality | Functional review, testing, bug reports |

### Security Team (separate mode: `security`)

| Agent | Role | What they do |
|-------|------|-------------|
| 🛡️ **Security Analyst** | Reviewer | OWASP Top 10 review, vulnerability analysis |
| 🔐 **Security Engineer** | Implementer | Security fixes, hardening, CSP/CORS |
| 💀 **Penetration Tester** | Red teamer | Attack simulation, PoC exploits |

---

## Quick Start

### Prerequisites

- **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code` then `claude login`
- **Python 3.10+** with `pyyaml` — `pip install pyyaml`
- **Claude Pro or Max subscription** — Pro ($20/mo) for minimal team, Max ($100/mo) for full team

### Setup

```bash
git clone https://github.com/Trigael/OpenSepia.git
cd OpenSepia
pip install -r requirements.txt

# (Optional) Add to PATH
# Linux/macOS:
sudo ln -s $(pwd)/bin/opensepia /usr/local/bin/opensepia
# Windows: add the bin/ directory to your PATH
```

### Run

```bash
# Initialize a project
opensepia init "My API" "REST API with FastAPI and PostgreSQL"

# Start the daemon (runs cycles in background)
opensepia start

# Check status
opensepia status

# Watch live logs
opensepia logs -f

# Stop when done
opensepia stop
```

---

## CLI Reference

```
opensepia help                   Show all commands

Project:
  opensepia init <name> [desc]   Initialize a new project
  opensepia reset                Reset project state

Daemon:
  opensepia start                Start background daemon
  opensepia start --mode all     Start with all 9 agents
  opensepia start --pause 120    2 minutes between cycles
  opensepia stop                 Graceful shutdown
  opensepia status               Show daemon & project status
  opensepia pause                Pause after current cycle
  opensepia resume               Resume cycling

Run:
  opensepia run dev-team         Run a single cycle
  opensepia run po --dry-run     Preview PO's context without calling Claude

Observe:
  opensepia logs -f              Follow daemon logs
  opensepia monitor              Cycle statistics (last 7 days)
  opensepia monitor --last       Last cycle details

Configure:
  opensepia config               Show all editable settings
  opensepia config project       Project settings
  opensepia config agents        Agent modes and execution params
  opensepia config env           Provider integration status
```

### Run Modes

| Mode | Agents | Use case |
|------|--------|----------|
| `dev-team` | 6 (PO, PM, Dev1, Dev2, DevOps, Tester) | Regular development (default) |
| `minimal` | 3 (PO, Dev1, Tester) | Save rate limits |
| `all` | 9 (everyone) | Full team with security |
| `security` | 3 (Sec Analyst, Engineer, Pentester) | Security audit |
| `po`, `dev1`, etc. | 1 | Run a single agent |

---

## Configuration

Three files control everything. Run `opensepia config` to see current values.

### `project/project.yaml` — What's being built

```yaml
project:
  name: My API
  description: "REST API with FastAPI and PostgreSQL"
  tech_stack:
    language: python
    framework: fastapi
    database: postgresql
    deployment: docker

sprint:
  current_sprint: 1
  current_cycle: 0
  cycles_per_sprint: 10    # 10 cycles = 1 sprint
```

### `config/agents.yaml` — How agents work

```yaml
# Which agents run in each mode
modes:
  dev-team:
    agents: [po, pm, dev1, dev2, devops, tester]
    aliases: [dev]
    default: true
  minimal:
    agents: [po, dev1, tester]
  # Add your own modes here

# Runtime behavior
execution:
  timeout: 900              # 15 min per agent
  max_retries: 1            # Retry once on failure
  retry_delay: 30           # Wait 30s before retry
  pause_between_agents: 5   # 5s between agents
  overrides:                # Per-agent tweaks
    devops:
      timeout: 1200         # DevOps gets 20 min

# Agent definitions (name, emoji, system prompt)
agents:
  po:
    name: "Product Owner"
    color: "🟣"
    system_prompt: |
      You are the Product Owner...
```

### `config/.env` — Provider integration (optional)

```bash
# GitLab
GITLAB_URL=https://gitlab.example.com
GITLAB_TOKEN=glpat-xxxxx
GITLAB_PROJECT_ID=group/project

# OR GitHub
GITHUB_TOKEN=ghp_xxxxx
GITHUB_OWNER=your-org
GITHUB_REPO=your-repo

# Git (for auto-push + MR creation)
GIT_REPO_URL=https://gitlab.example.com/group/project.git
GIT_TOKEN=glpat-xxxxx
```

---

## Project Structure

```
OpenSepia/
├── opensepia/              # Application source code
│   ├── cli.py              # Command router
│   ├── config.py           # Configuration loading
│   ├── pipeline.py         # Pipeline runner (11 steps)
│   ├── daemon.py           # Background daemon
│   ├── agents/             # Agent execution (context, invoker, parser, writer)
│   ├── board/              # Board management (sync, comments, restore, merge)
│   ├── steps/              # Pipeline steps
│   └── integrations/       # Provider APIs (GitLab, GitHub, git, docker)
│
├── config/                 # Tool configuration
│   ├── agents.yaml         # Agent definitions + modes + execution params
│   └── .env                # Provider credentials (gitignored)
│
├── project/                # The product being built (swappable)
│   ├── project.yaml        # Project name, tech stack, sprint state
│   ├── board/              # Agent progress (sprint.md, backlog.md, inbox/)
│   ├── workspace/          # Code the agents write
│   └── logs/               # Cycle logs
│
├── tests/                  # 142 tests
└── bin/opensepia           # CLI entry point
```

The `project/` folder is the product OpenSepia works on. It can be swapped out for a different project with the same structure.

---

## Integrations

OpenSepia works standalone with just Markdown files. When you connect a provider, it adds:

- **Issues** — stories sync to GitLab/GitHub issues with status labels
- **Merge requests** — code auto-pushed to feature branches with MR/PR creation
- **Auto-merge** — approved MRs are merged, stale ones closed
- **Comments** — agent messages posted as issue comments
- **Board restore** — if board files are lost, reconstructed from provider

### Story Workflow

```
TODO → IN_PROGRESS → REVIEW → TESTING → DONE
```

Each status maps to a label on the provider (`status::todo`, `status::in-progress`, etc.).

---

## Human Intervention

Write to an agent's inbox file — they'll read it next cycle:

```bash
echo "## Message from Human
STORY-003 priority is now CRITICAL." >> project/board/inbox/pm.md
```

Or comment on a GitLab/GitHub issue — all agents see provider comments in their context.

---

## Rate Limits

| Plan | Messages/5h | Recommended | Agents per cycle |
|------|-------------|-------------|-----------------|
| **Pro** ($20/mo) | ~45 | 3-4 cycles/day | 3 (minimal) |
| **Max** ($100/mo) | ~225 | 15-20 cycles/day | 6-9 (full team) |

---

## License

MIT
