# TODO — Future Improvements

## Agent Context Optimization
- Cap sprint_md at ~3000 chars (exclude DONE stories agents don't need)
- Cap backlog_md at ~3000 chars (only include relevant priority levels)
- Only include active stories in sprint context, not historical DONE items
- Consider per-agent context filtering (dev1 only sees stories assigned to dev1)
- Track which agents time out repeatedly and reduce their context more aggressively

## Comment Architecture
- Split comments into proper types: review comments (on stories), coordination messages (inbox only), status updates (automated)
- Agent inbox messages should NOT be posted as story comments
- Story comments should be: code reviews, QA reviews, PO acceptance, human feedback
- Status changes should be event-driven notifications, not comments
- Board server needs a proper comment type field (review vs discussion vs system)

## Provider-First Architecture
- Add document store to board server (`/api/docs/{name}`) for architecture.md, decisions.md, project.md, standup.md
- Route all document writes through the adapter instead of local filesystem
- Build agent context entirely from board server API (zero local file reads)
- Make MarkdownBoardAdapter a true offline/fallback mode
- Consider: should the board server store the full project.yaml equivalent?

## Agent Improvements
- Detect when an agent produces empty/1-byte responses (rate limit) and retry immediately
- Track agent performance over time (average response time, error rate)
- Smart timeout: if an agent consistently takes 5 minutes, don't wait 15
- Agent self-evaluation: have agents rate their own output quality
- Consider: parallel agent execution for independent stories

## Pipeline Enhancements
- Implement `agent_group` YAML syntax with `parallel: true` for future multi-team support
- Add `barrier` step type for synchronization points between parallel groups
- Pipeline step hooks (before_step, after_step) for custom logic
- Conditional steps (only run if condition met, e.g., "only run tester if dev wrote code")

## Git Workflow
- Per-story branches with automatic merge on DONE (Phase C — in progress)
- Pull request creation per story (not per cycle)
- Branch protection rules awareness
- Conflict detection between story branches
- Git history cleanup (squash per-agent commits on story branch before merge)

## Board Server
- WebSocket support for real-time updates
- Pagination for large item lists
- Bulk operations API (batch create/update)
- Activity feed / audit log in the web UI
- Sprint velocity tracking and burndown charts
- File/artifact attachments on items
