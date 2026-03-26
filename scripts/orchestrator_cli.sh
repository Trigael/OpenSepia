#!/bin/bash
# =============================================================================
# AI Dev Team — Orchestrator (shim)
# Delegates to python -m orchestrator. Kept for backward compatibility
# with cron jobs and run_loop.sh.
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR" || exit 1

exec python3 -m orchestrator "$@"
