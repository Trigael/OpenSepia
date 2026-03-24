#!/bin/bash
# Clears all AI-generated content while preserving config, keys, and tooling

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "============================================"
echo "  AI Dev Team — Project Reset"
echo "============================================"
echo ""
echo "This will delete:"
echo "  - board/ (sprint, backlog, inbox, standup)"
echo "  - workspace/src/"
echo "  - repo/ (local git clone)"
echo "  - logs/runs/"
echo ""
echo "This will KEEP:"
echo "  - config/.env, agents.yaml, project.yaml"
echo "  - scripts/, Docker setup, Claude auth"
echo ""
read -p "Are you sure? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Stopping Docker container..."
docker stop opensepia 2>/dev/null && echo "  ✅ Container stopped" || echo "  ⏭️  Container not running"

echo ""
echo "Clearing board..."
rm -rf "$PROJECT_DIR/board"
mkdir -p "$PROJECT_DIR/board/inbox" "$PROJECT_DIR/board/archive" "$PROJECT_DIR/board/.snapshot"
echo "  ✅ Done"

echo "Clearing workspace/src..."
rm -rf "$PROJECT_DIR/workspace/src"
mkdir -p "$PROJECT_DIR/workspace/src"
touch "$PROJECT_DIR/workspace/src/.gitkeep"
echo "  ✅ Done"

echo "Clearing repo..."
rm -rf "$PROJECT_DIR/repo"
mkdir -p "$PROJECT_DIR/repo"
echo "  ✅ Done"

echo "Clearing logs..."
rm -rf "$PROJECT_DIR/logs/runs"
mkdir -p "$PROJECT_DIR/logs/runs"
> "$PROJECT_DIR/logs/cron.log" 2>/dev/null || true
echo "  ✅ Done"

echo ""
read -p "Initialize a new project now? (yes/no): " init_confirm
if [ "$init_confirm" == "yes" ]; then
    read -p "Project name: " project_name
    read -p "Project description: " project_desc
    cd "$PROJECT_DIR"
    python3 scripts/init_project.py "$project_name" "$project_desc"
    python3 scripts/init_integrations.py

    read -p "Start the container? (yes/no): " start_confirm
    if [ "$start_confirm" == "yes" ]; then
        docker start opensepia 2>/dev/null || echo "  ⚠️  Container not found — run docker-build-run.sh first"
    fi
fi

echo ""
echo "  Reset complete!"
