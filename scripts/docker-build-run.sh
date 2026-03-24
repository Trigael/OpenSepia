#!/bin/bash
# Build and run the orchestrator container

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE=${1:-dev-team}
PAUSE=${2:-60}

echo "============================================"
echo "  AI Dev Team — Build and Run"
echo "  Mode: $MODE | Pause: ${PAUSE}s"
echo "============================================"

echo ""
echo "Building image..."
docker build -f "$PROJECT_DIR/Dockerfile.orchestrator" -t opensepia "$PROJECT_DIR"

echo ""
echo "Stopping old container..."
docker stop opensepia 2>/dev/null && docker rm opensepia 2>/dev/null || true

echo ""
echo "Starting container..."
docker run -d \
  --name opensepia \
  --restart unless-stopped \
  -v "$PROJECT_DIR/board:/app/board" \
  -v "$PROJECT_DIR/workspace:/app/workspace" \
  -v "$PROJECT_DIR/logs:/app/logs" \
  -v "$PROJECT_DIR/config:/app/config" \
  -v "$PROJECT_DIR/repo:/app/repo" \
  -v "$HOME/.claude-auth:/root/.claude" \
  -v "$HOME/.claude.json.host:/root/.claude.json" \
  opensepia ./scripts/run_loop.sh "$MODE" "$PAUSE"

echo ""
echo "Done! Follow logs with:"
echo "  docker logs -f opensepia"
