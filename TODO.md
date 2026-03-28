# TODO — Future Improvements

## CRITICAL — From AgentBoard Run Observations

### Process Group Cleanup in invoke_agent
- Kill entire process tree on timeout, not just the parent Claude CLI process
- Agents spawn bash → pytest subprocesses that become zombies when parent is killed
- After ~30 cycles, 16+ zombie pytest processes were consuming memory
- Use `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)` or `proc.terminate()` with `start_new_session=True`
- Add a reaper that cleans up orphaned child processes between cycles

### Per-Story Branch Merge Timing (BUG-005 fix — review and keep)
- Agents patched agent_step.py to merge story branches into master immediately after commit
- Previously, merge only happened on DONE status, but tester/reviewer need code visible on master during REVIEW
- The deadlock: dev writes → commits to story branch → checkout master → code disappears → tester rejects → repeat
- This stalled Sprint 3 for 5+ cycles until agents self-fixed
- Review the agent-applied fix at agent_step.py:300-311 and formalize it

### Restrict Agent Tool Access
- DevOps agent ran `opensepia start --mode all` during a cycle, spawning a competing daemon
- Agents should NOT be allowed to run: `opensepia start`, `opensepia stop`, `opensepia reset`, `opensepia run`
- Add these to a blocklist in the Claude CLI invocation or agent system prompts
- Consider: restrict `kill`, `pkill`, `rm -rf` and other destructive commands too

## HIGH — Agent Behavior Issues

### PO Story Creation Pace
- PO only created 17 stories after 32 cycles without human intervention
- Needed explicit inbox prompt to expand backlog to 43+ stories
- PO focuses on managing current sprint rather than growing backlog proactively
- Fix: Add to PO system prompt: "Each sprint, create at least 3-5 new stories for future sprints"
- Fix: Add a pipeline step that checks backlog depth and prompts PO if < 10 TODO stories remain

### Security Findings Bloat Sprint Context
- Security agents append findings directly into sprint.md
- All agents then read these as context, wasting tokens
- Fix: Add `board/security.md` as a dedicated security findings document
- Fix: Security agents write to security.md, not sprint.md
- Fix: Only sec_engineer reads security.md for remediation; other agents don't need it

### Standup Fallback Duplicate Detection
- PM standup appears twice: once from agent output, once from `_handle_standup_fallback`
- Fallback doesn't detect standups inside `<details>` blocks
- Fix: Check for agent_id in existing standup content before appending fallback
- Fix: Parse `<details>` blocks when checking for existing standup entries

### Standup Cross-Project Contamination
- After `opensepia reset` + `init`, standup.md contained `<details>` tags with previous project data
- Agents from previous run wrote `<details><summary>Previous cycle</summary>` blocks
- `opensepia reset` clears the file but `init` doesn't strip stale content
- Fix: `init` should write a clean standup.md, not append to existing

## MEDIUM — Architecture Improvements

### Agent Context Optimization
- Cap sprint_md at ~3000 chars (exclude DONE stories agents don't need)
- Cap backlog_md at ~3000 chars (only include relevant priority levels)
- Only include active stories in sprint context, not historical DONE items
- Per-agent context filtering (dev1 only sees stories assigned to dev1)
- Track which agents time out repeatedly and reduce their context more aggressively

### Comment Architecture
- Split comments into proper types: review comments (on stories), coordination messages (inbox only), status updates (automated)
- Agent inbox messages should NOT be posted as story comments
- Story comments should be: code reviews, QA reviews, PO acceptance, human feedback
- Status changes should be event-driven notifications, not comments
- Board server needs a proper comment type field (review vs discussion vs system)

### Provider-First Architecture
- Add document store to board server (`/api/docs/{name}`) for architecture.md, decisions.md, project.md, standup.md
- Route all document writes through the adapter instead of local filesystem
- Build agent context entirely from board server API (zero local file reads)
- Make MarkdownBoardAdapter a true offline/fallback mode
- Consider: should the board server store the full project.yaml equivalent?

### DevOps Agent Underutilized
- Created Docker files in Sprint 1 but had nothing to do for rest of project
- Needs dedicated stories per sprint: update Dockerfile, add healthchecks, docker-compose services, monitoring
- Consider: auto-create a "Docker update" story each sprint if Dockerfile exists

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
- Add backlog depth check step: if < 10 TODO stories, prompt PO to create more

## Git Workflow
- Per-story branches with immediate merge to master (agent-fixed, formalize)
- Pull request creation per story (not per cycle)
- Branch protection rules awareness
- Conflict detection between story branches
- Git history cleanup (squash per-agent commits on story branch before merge)
- Process tree cleanup: kill orphaned git processes between cycles

## Board Server / AgentBoard
- WebSocket support for real-time updates
- Pagination for large item lists
- Bulk operations API (batch create/update)
- Activity feed / audit log in the web UI
- Sprint velocity tracking and burndown charts
- File/artifact attachments on items
- WebSocket ticket-based auth (don't pass API key as query param — PENTEST-005)
- Result limit caps on all list endpoints (PENTEST-002, PENTEST-004)

## Plane.so Integration
- Pages API not available in v1.2.3 — falls back to local files for inbox/standup/docs
- Uses `state` field (not `state_id`) for work item transitions
- Priorities are strings in v1.2.3 ("urgent", "high"), integers in newer versions
- Cycle creation requires `project_id` in body and `cycle_view: true` on project
- New projects need `identifier` field
- Consider: upgrade Plane to latest version for Pages API support
