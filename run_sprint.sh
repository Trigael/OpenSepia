#!/bin/bash
# Run multiple cycles for a sprint
# Usage: ./run_sprint.sh <num_cycles> <mode>

CYCLES=${1:-10}
MODE=${2:-dev-team}

echo "=== Running $CYCLES cycles in $MODE mode ==="

for i in $(seq 1 $CYCLES); do
    echo ""
    echo "--- Cycle $i/$CYCLES ($(date)) ---"
    python3 -m opensepia run "$MODE" 2>&1 | tail -5

    # Check if it failed
    status=$(python3 -c "import json; d=json.load(open('project/logs/cycle_state.json')); print(d['status'])" 2>/dev/null)
    if [ "$status" = "failed" ]; then
        echo "CYCLE FAILED — stopping"
        break
    fi

    # Short pause between cycles
    sleep 5
done

echo ""
echo "=== Sprint run complete ==="
echo "Stories in backlog: $(grep -c '^### ' project/board/backlog.md)"
echo "Sprint board:"
cat project/board/sprint.md | head -30
