# Decisions (Decision Log)

### DEC-001: Project initialization (2026-03-27)
- **Context**: New project Board Server v2
- **Decision**: Starting Sprint 1
- **Who**: System (init)

### DEC-002: MVP scope defined (2026-03-27)
- **Context**: Sprint 1, Cycle 1 — need to define what goes into MVP
- **Decision**: MVP = REST API (items CRUD, comments, inboxes, sprints) + SQLite + configurable schema + test suite. Web UI and search deferred to Sprint 2. 8 stories created for Sprint 1.
- **Who**: PO
### DEC-003: STORY-002 and STORY-008 accepted (2026-03-27)
- **Context**: Sprint 1, Cycle 2 — reviewing completed work
- **Decision**: DB layer (STORY-002) accepted — thread-safe SQLite with WAL, comprehensive tests. Test infra (STORY-008) accepted — pytest config, shared fixtures, Docker test runner. STORY-009/010 closed as already addressed.
- **Who**: PO
### DEC-003: Story reassignment per even/odd rule
**Date**: 2026-03-27 | **By**: PM
Even stories → dev1, odd stories → dev2. STORY-004 (even) moved to dev1, STORY-003 (odd) moved to dev2. Cross-review: dev1 reviews dev2's work and vice versa.
### DEC-004: Stories 003, 004, 007 accepted to TESTING (2026-03-27)
- **Context**: Sprint 1, Cycle 3 — reviewing three stories in REVIEW
- **Decision**: All three accepted by PO. STORY-003 (CRUD API), STORY-004 (comments), STORY-007 (schema) moved to TESTING. Code quality and test coverage meet standards.
- **Who**: PO
### DEC-005: STORY-005 and STORY-006 accepted to TESTING (2026-03-27)
- **Context**: Sprint 1, Cycle 4 — reviewing last two stories in REVIEW
- **Decision**: Both accepted. Inbox system (STORY-005) has full CRUD with read/unread tracking and agent isolation. Sprint management (STORY-006) has complete lifecycle, item assignment, and status guards. Both have comprehensive test suites.
- **Who**: PO

### DEC-006: BUG-001 deferred to Sprint 2 as STORY-011 (2026-03-27)
- **Context**: Tester reported schema validation not integrated with items API — items accept arbitrary status/priority values
- **Decision**: Confirmed bug. Schema module has validate_item() but items.py never calls it. Deferred to Sprint 2 as STORY-011 (HIGH priority, first story). Sprint 1 is wrapping up and this is not a blocker for MVP testing.
- **Who**: PO

### DEC-007: Sprint 2 backlog created (2026-03-27)
- **Context**: Sprint 1 nearly complete — planning next iteration
- **Decision**: Sprint 2 scope: STORY-011 (schema validation fix, HIGH), STORY-012 (event system/webhooks, HIGH), STORY-013 (web UI kanban, HIGH), STORY-014 (full-text search, MEDIUM), STORY-015 (sprint UI panel, MEDIUM), STORY-016 (API docs, LOW). Focus is on integrations, UI, and search.
- **Who**: PO
### DEC-008: Sprint 2 plan approved (2026-03-27)
- **Context**: Sprint 1, Cycle 5 — PM proposed Sprint 2 assignments and goal
- **Decision**: Approved Sprint 2 goal "Integrations, validation, and web UI." Priority order: STORY-011 (bug fix) first, then STORY-012/013 (features), then 014/015/016 (stretch). Assignments: dev1 gets even stories (012, 014, 016), dev2 gets odd stories (011, 013, 015). Sprint 2 starts as soon as tester confirms STORY-005 and STORY-006.
- **Who**: PO
## Decision — Sprint 2 Kickoff (Cycle 5)
- Sprint 1 closed. All stories DONE, 182 tests passing.
- STORY-011 reassigned from dev1 to dev2 per odd-number rule. Dev1 reviews.
- Sprint 2 priority order per PO: STORY-011 (bug) → STORY-012/013 (features) → 014/015/016 (stretch).