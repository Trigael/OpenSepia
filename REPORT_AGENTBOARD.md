# AgentBoard — Live Observation Log

System behavior journal for the AgentBoard build. Captures errors, agent misbehavior, architecture issues, and faulty patterns to inform test cases and architectural improvements.

---

## Sprint 1 — Foundation

### Pre-Sprint Setup
- **Date**: 2026-03-27
- **Mode**: dev-team (6 agents)
- **Cycles**: 10 per sprint (adjustable)
- **Seeded stories**: 5 high-level stories, PO to expand

### Cycle 1 (s1c0) — 16 min, all 6 agents completed
**Stories**: 3 DONE (001, 002, 004), 1 REVIEW (003 with BUG-001), 1 TODO (005). PO created 7 new stories (006-012). Total: 12 stories + 1 bug.

**Observations**:
1. **ISSUE: Standup has remnants from previous project** — The standup.md contains `<details>` tags with TaskFlow run data. The `opensepia reset` command cleared the file but `init` re-seeded it, and the agent appended new content. The old content appears inside a `<details>` block suggesting a previous agent wrote it that way. **Not a bug** — just confusing context for agents. Could strip prior-project standups on init.

2. **ISSUE: Duplicate PM standup entries** — PM's standup appears twice with identical content. This suggests PM wrote to standup.md AND the fallback standup logic also appended. **Likely bug in `_handle_standup_fallback`** — it doesn't detect when agent already wrote standup within a `<details>` block.

3. **GOOD: Tester found a real bug** — QA reviewed STORY-003 and filed BUG-001 (items router missing proper error handling). Moved STORY-003 back to REVIEW with note. This is the supervision loop working correctly.

4. **GOOD: Dev1 productivity** — In a single cycle, dev1 built the entire FastAPI scaffold + SQLite + migrations + inbox API + 7 tests. Impressively coherent output.

5. **NOTE: DevOps agent wrote Dockerfile** — Not visible in workspace files (may have been rejected or not written). Need to check if devops output was captured.

6. **RESOLVED: Docker files exist** — DevOps created Dockerfile, docker-compose.yml, .dockerignore. They weren't showing earlier because they were at workspace root, not under src/. Working correctly.

7. **NOTE: Sprint auto-advanced** — Sprint 1 completed all 5+1 stories in just 3 cycles (of planned 10). PO started Sprint 2 with STORY-007/008/009. cycles_per_sprint=10 means the sprint boundary triggered at cycle 10, but PO is already planning Sprint 2 work.

### Cycle 2 (s1c1) — completed
- STORY-003 bug fixed, moved to DONE
- STORY-006 (Pages API) started by dev1
- No anomalies

### Cycles 3-8 (s1c2 through s1c7) — running in batch
- Sprint auto-transitioned to Sprint 2 during this batch
- All Sprint 1 stories DONE (001-006)
- Sprint 2 started: STORY-007 (Sprint mgmt), STORY-008 (Comments), STORY-009 (Audit log)
- Git initialized in workspace after Sprint 1 completion
- 1,620 lines of Python across 18 files at time of git init

### Sprint 2 Start (auto-transitioned from Sprint 1)
- Sprint 1 completed all stories in ~5 cycles (well under the 10-cycle budget)
- Sprint 2 goal: "Build sprint/cycle management, story comments, and audit logging"
- PO created STORY-006 through STORY-012 (7 new stories, total 12 + 1 bug)

**Observation**: PO is not creating stories fast enough to hit 60-story target. 12 stories after 8 cycles. May need to prompt PO for more granular breakdown or feature expansion in future sprints.

### Sprint 2 Cycles 1-5 (s2c0 through s2c5)
- STORY-007 (Sprints API) DONE, STORY-008 (Comments) in REVIEW, STORY-009 (Audit log) in progress
- Agents using per-story git branches correctly (story/story-007, story/story-008, story/bug-001)
- 11 git commits, clean branch merges to master
- New routers: comments.py, sprints.py, board.py
- 2,256 lines of Python across 22 files

**ISSUE: DevOps created Docker files in Sprint 1 but no further Docker work visible** — Dockerfile and docker-compose.yml were created early but haven't been updated as new routers were added. DevOps may need a dedicated story.

**GOOD: Tester is effective** — Filed BUG-001, caused STORY-003 to go back to review, was eventually fixed. QA loop working as intended.

### Security Run (s2c6-c7) — 2 security cycles
**GOOD: Security team found real issues**:
- SEC-001 (CRITICAL): SQL injection via dynamic column names in PATCH endpoints. Noted that a claimed fix from cycle 6 wasn't actually in the codebase. RE-OPENED.
- SEC-002 (CRITICAL): No authentication on any endpoint.

**ISSUE: Security findings written into sprint.md** — The security agents appended a "Security Findings" section to sprint.md. This is visible to all agents which is good, but it bloats the sprint context. Consider a separate security findings document.

### Sprint 3 Start
- Sprint auto-transitioned
- BUG-002 filed: AgentCommitStep merge-on-DONE causes file disappearances
- STORY-013 created: Security hardening (fix all RE-OPENED findings)

**SIGNIFICANT: Agents fixing OpenSepia itself** — BUG-002 was about opensepia/steps/agent_step.py's git merge behavior. The agents modified the actual OpenSepia source code (agent_step.py) to fix a bug they encountered while building AgentBoard. The fix improves stash pop conflict resolution and adds master merge into story branches. This is emergent self-improvement behavior.

**Observation**: agent_step.py was modified by agents — need to review this change carefully and decide whether to keep it. It looks correct (resolves only conflicted files instead of --theirs on entire tree).

### Running Stats (after ~18 cycles)
- 14 items (12 stories + 2 bugs)
- 2,526 lines of Python across 22+ files
- 13 git commits with story branches
- Sprint 3, cycle 2 in progress

### Sprint 3 Cycles 1-3 (s3c0 through s3c2)
**CRITICAL PATTERN: Code vanishing from workspace** — PM flagged "devs submitting REVIEW without code in workspace (3rd occurrence)". Dev1 writes middleware.py, test_security.py, etc. but they don't appear in workspace on master. This is the per-story branch merge issue: dev writes on story branch, but merge back to master fails silently or code gets lost during branch switch. BUG-002 was filed for this but the fix isn't fully effective.

**Root cause hypothesis**: When agent writes files on story/story-013 branch, commits, then switches back to master — the files only exist on the story branch. Other agents (tester, dev2) read master and see nothing. The merge-on-DONE in AgentSyncStep only merges when status reaches DONE, but review happens earlier.

**Impact**: Sprint velocity stalled. Stories cycle through IN_PROGRESS → REVIEW → back to IN_PROGRESS repeatedly because tester can't verify code that only exists on unmerged story branches.

**BUG-003 filed and fixed**: Agents found another git issue — merge error handling at agent_step.py:277,301 now checks return codes and aborts on failure to prevent conflict markers from being staged.

**Story creation pace**: Still at 14 items after ~20 cycles. PO needs to create more stories to hit 60 target. The stalled velocity is partly causing this — PO can't mark stories DONE and create new sprint work.

## Sprint 3 — Full Results (s3c0 through s3c9)

### Completed stories: STORY-010 (Dashboard htmx), STORY-012 (MR proxy API), STORY-013 (Security hardening)
### In progress: STORY-011 (Supervision queue) — rejected twice for missing code
### Bugs found: BUG-004 (merge on REVIEW not just DONE), BUG-005 (agent files silently deleted)

**CRITICAL PATTERN CONFIRMED: File gate problem** — BUG-005 formally captures the file disappearance issue. Dev writes files, commits to story branch, but when branch is checked out/merged the files don't appear on master. This stalled STORY-011 for 5+ cycles.

**GOOD: Dashboard built** — STORY-010 delivered an htmx dashboard with board view, activity feed, WebSocket live updates. DevOps contributed to this.

**GOOD: Security hardening completed** — STORY-013 implemented API key middleware, parameterized queries, input validation, security headers. All RE-OPENED findings from Sprint 2 security run are now CLOSED.

## Sprint 4 — Supervision Queue (s4c0 through s4c3)

### Sprint Goal: "Deliver STORY-011 supervision queue — the last feature before production-ready"
### Status: STORY-011 in TESTING after being stuck for 8+ cycles

**BUG-005 fix allowed progress** — Once the file gate bug was fixed, dev2 could finally land supervision.py code. Tester found 4 bugs in it (BUG-006 through BUG-009) but core logic is correct.

**Security run findings**:
- PENTEST-001 (TOCTOU race in approve/reject): FIXED — atomic SQL UPDATE with rowcount check
- PENTEST-002 (no result limit on audit): FIXED — capped at 1000
- PENTEST-003 (no CSRF): Accepted risk for API-first service
- PENTEST-004 (no limit on supervision queue): NEW, same class as PENTEST-002
- PENTEST-005 (WebSocket API key in query param): NEW MEDIUM — recommends ticket-based auth

### Running Stats (after ~32 cycles, sprint 4 cycle 3)
- 17 items (13 stories + 5 bugs from BUG-002 through BUG-010, some gaps)
- 4,706 lines of Python across 18 source files
- 52 git commits with story branches
- Sprints completed: 1, 2, 3 (sprint 4 in progress)
- All original 5 seed stories DONE
- 7 additional stories created by PO (006-013)
- Story creation pace: 17 items total, need 43 more for 60 target

**Observation: PO creates stories slowly** — Most new stories come at sprint boundaries. PO should be prompted to break down remaining features more aggressively. Remaining features not yet storied: labels API, bulk operations, pagination, search, rollback, per-agent capabilities.

## Sprint 5-7 (continuous runner batch)

### Story explosion after PO inbox prompt
Seeded PO inbox with feature list requesting 20+ new stories. PO responded — story count jumped from 17 to 43+ by Sprint 7. Python grew from 4,706 to 11,238 lines.

### CRITICAL: Zombie process accumulation
**ISSUE**: Agents spawning `python3 -m pytest` subprocesses that never get cleaned up. Found 16+ zombie pytest processes from earlier cycles consuming memory. This is because Claude CLI spawns bash subprocesses for tool calls, and some pytest runs hang indefinitely (likely waiting on stuck SQLite connections or import loops).

**Impact**: Memory pressure on the VPS. Could cause OOM kills or slow agent execution.

**Root cause**: The `invoke_agent` function spawns Claude CLI which spawns bash+pytest. The 15-min timeout kills Claude CLI but orphans the child processes.

**Fix needed**: Add process group cleanup to `invoke_agent` — kill the entire process tree, not just the parent.

### ISSUE: Stray daemon started by agent
An agent ran `opensepia start --mode all` inside the workspace, starting a daemon that competed with the `run_until_done.sh` script for the lock file. Had to force-kill it.

**Root cause**: DevOps agent likely ran the daemon command as part of "deployment" testing.

**Fix needed**: Agents should not be allowed to run `opensepia start/stop` commands. Add to agent system prompts or restrict via allowed tools.

