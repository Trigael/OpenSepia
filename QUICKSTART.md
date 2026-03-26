# Quick Start

## Prerequisites

- **Python 3.10+** with `pyyaml`
- **Claude Code CLI** with Pro or Max subscription
- **Any OS** — Linux, macOS, or Windows

## 1. Install

```bash
# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code
claude login

# Clone OpenSepia
git clone https://github.com/Trigael/OpenSepia.git
cd OpenSepia
pip install -r requirements.txt
```

### Add to PATH

```bash
# Linux/macOS
sudo ln -s $(pwd)/bin/opensepia /usr/local/bin/opensepia

# Windows — add the bin/ directory to your system PATH
```

## 2. Initialize a project

```bash
opensepia init "My API" "REST API with FastAPI and PostgreSQL"
```

This creates `project/` with seed board files and two starter stories.

## 3. (Optional) Configure provider

```bash
cp config/.env.example config/.env
# Edit config/.env with your GitLab or GitHub tokens
```

## 4. Run

```bash
# Start the daemon — runs cycles in background
opensepia start

# Check what's happening
opensepia status

# Watch live
opensepia logs -f

# Stop
opensepia stop
```

Or run a single cycle:

```bash
opensepia run dev-team
```

## 5. Check results

```
project/board/sprint.md     Sprint progress
project/board/backlog.md    All stories
project/workspace/src/      Code the agents wrote
```

## What happens next

Every cycle (~60s by default), 6 agents run in sequence:
1. PO creates/prioritizes stories
2. PM assigns work
3. Dev1 + Dev2 write code
4. DevOps sets up infrastructure
5. Tester verifies

After 10 cycles (1 sprint), PO and PM run a retrospective and the sprint advances.

## Useful commands

```bash
opensepia help          # All commands
opensepia config        # Show editable settings
opensepia monitor       # Cycle statistics
opensepia run po        # Run just one agent
```
