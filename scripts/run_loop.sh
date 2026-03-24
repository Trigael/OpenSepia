#!/bin/bash

MODE=${1:-dev-team}
PAUSE=${2:-60}  # seconds between cycles

echo "Initializing integrations..."
python3 "$(dirname "$0")/init_integrations.py" 2>&1

echo "Running initial board sync..."
python3 "$(dirname "$0")/../scripts/sync_board.py" 2>&1
echo "Initial sync done."

echo "Starting continuous loop — mode: $MODE, pause between cycles: ${PAUSE}s"

while true; do
    echo ""
    echo "=========================================="
    echo "  Starting new cycle at $(date)"
    echo "=========================================="

    bash "$(dirname "$0")/orchestrator_cli.sh" "$MODE" 2>&1 | tee -a "/app/logs/cron.log"
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo "⚠️  Cycle exited with code $EXIT_CODE at $(date)"
        echo "   Waiting ${PAUSE}s before retrying..."
    else
        echo "✅ Cycle completed at $(date)"
        echo "   Waiting ${PAUSE}s before next cycle..."
    fi

    sleep "$PAUSE"
done
