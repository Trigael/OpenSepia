#!/bin/bash
# Run cycles continuously until 60 stories are reached
# Usage: ./run_until_done.sh

TARGET_STORIES=60
SPRINT_NUM=0

cd /home/claude/opensepia

while true; do
    SPRINT_NUM=$((SPRINT_NUM + 1))
    STORIES=$(grep -c '^### ' project/board/backlog.md 2>/dev/null || echo 0)
    LINES=$(find project/workspace -type f -name '*.py' -not -path '*/__pycache__/*' -exec cat {} + 2>/dev/null | wc -l)
    COMMITS=$(cd project/workspace && git log --oneline 2>/dev/null | wc -l)
    CYCLE_INFO=$(python3 -c "import json; d=json.load(open('project/logs/cycle_state.json')); print(f's{d[\"sprint\"]}c{d[\"cycle\"]}')" 2>/dev/null || echo "?")

    echo ""
    echo "================================================================"
    echo "BATCH $SPRINT_NUM — $(date) — $CYCLE_INFO"
    echo "Stories: $STORIES/$TARGET_STORIES | Lines: $LINES | Commits: $COMMITS"
    echo "================================================================"

    if [ "$STORIES" -ge "$TARGET_STORIES" ]; then
        echo "TARGET REACHED: $STORIES stories (target: $TARGET_STORIES)"
        break
    fi

    # Run 8 dev-team cycles
    echo "--- Running 8 dev-team cycles ---"
    ./run_sprint.sh 8 dev-team 2>&1 | grep -E 'Cycle|Completed|FAILED|Sprint'

    # Run 2 security cycles
    echo "--- Running 2 security cycles ---"
    ./run_sprint.sh 2 security 2>&1 | grep -E 'Cycle|Completed|FAILED|Sprint'

    # Commit workspace changes
    cd project/workspace
    git add -A 2>/dev/null
    git commit -m "Sprint checkpoint — batch $SPRINT_NUM" 2>/dev/null
    cd /home/claude/opensepia

    # Check story count after batch
    STORIES=$(grep -c '^### ' project/board/backlog.md 2>/dev/null || echo 0)
    echo ""
    echo "After batch $SPRINT_NUM: $STORIES stories"

    if [ "$STORIES" -ge "$TARGET_STORIES" ]; then
        echo "TARGET REACHED: $STORIES stories (target: $TARGET_STORIES)"
        break
    fi

    # Safety: stop after 20 batches (200 cycles)
    if [ "$SPRINT_NUM" -ge 20 ]; then
        echo "SAFETY STOP: 20 batches completed"
        break
    fi
done

echo ""
echo "================================================================"
echo "FINAL STATUS"
echo "================================================================"
echo "Stories: $(grep -c '^### ' project/board/backlog.md)"
echo "Python lines: $(find project/workspace -type f -name '*.py' -not -path '*/__pycache__/*' -exec cat {} + | wc -l)"
echo "Git commits: $(cd project/workspace && git log --oneline | wc -l)"
echo ""
echo "Sprint board:"
cat project/board/sprint.md | head -40
echo ""
echo "All stories:"
grep "^### " project/board/backlog.md
