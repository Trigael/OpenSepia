# Decisions (Decision Log)

### DEC-001: Project initialization (2026-03-27)
- **Context**: New project Board Server v2
- **Decision**: Starting Sprint 1
- **Who**: System (init)

### DEC-002: MVP scope and sprint plan (2026-03-27)
- **Context**: Sprint 1 kickoff — need to define what MVP looks like and sequence the work.
- **Decision**: MVP split into 3 sprints. Sprint 1 = foundation (scaffolding, DB, CRUD API, tests). Sprint 2 = features (comments, inbox, search, webhooks, sprints). Sprint 3 = frontend + deployment. 13 stories total (STORY-003 through STORY-015).
- **Who**: Product Owner

### DEC-003: Tech constraints confirmed (2026-03-27)
- **Context**: Confirming tech stack alignment with project description.
- **Decision**: FastAPI + uvicorn + pyyaml only. SQLite with WAL mode for concurrency. Vanilla HTML/JS frontend (no React/Vue). No ORM — raw SQL with parameterized queries.
- **Who**: Product Owner
### DEC-004: Cycle 2 assignments (2026-03-27)
- **Context**: Dev2 completed STORY-005 and is free. STORY-003 (REST API) blocked on STORY-002 (DB layer, still in progress).
- **Decision**: Assign dev2 to STORY-004 (YAML schema) which has no DB dependency. STORY-003 stays assigned to dev2 but deferred until STORY-002 completes.
- **Who**: Product Owner
### DEC-005: Accept STORY-002 and STORY-004 (2026-03-27)
- **Context**: Both stories in TESTING — code review shows complete implementations with comprehensive test coverage.
- **Decision**: STORY-002 (SQLite DB) and STORY-004 (YAML schema) accepted and moved to DONE. STORY-003 (REST API) now unblocked and assigned to dev2 as top priority.
- **Who**: Product Owner
## Cycle 3 — PM Assignment Decision
- STORY-008 (even) → dev1 per assignment rules
- STORY-003 remains with dev2 (critical path, near completion)
- STORY-007 (odd) queued for dev2 after STORY-003 completes
### DEC-006: Accept STORY-003, assign STORY-007 (2026-03-27)
- **Context**: STORY-003 (REST API CRUD) in REVIEW — code review shows complete implementation with all 5 endpoints, schema validation, pagination, filtering, and 30+ tests.
- **Decision**: STORY-003 accepted and moved to DONE. STORY-007 (comments system) assigned to dev2 as next priority. Dev1 continues STORY-008 (inbox), tester continues STORY-006 (test suite).
- **Who**: Product Owner
### DEC-007: STORY-013 Docker scaffolding approach (2026-03-27)
- **Context**: PM green-lit STORY-013 prep. App, DB layer, and core API are stable.
- **Decision**: Multi-stage Dockerfile with python:3.10-slim, non-root user, HEALTHCHECK via /health endpoint. docker-compose.yml with named volume for SQLite persistence. Entry point via `python -m board_server`. Final merge deferred until more features land.
- **Who**: DevOps Engineer
### DEC-008: Cycle 5 — STORY-008 to testing, assign STORY-009 (2026-03-27)
- **Context**: STORY-008 (Agent inbox) code-reviewed and approved by dev1 (8 endpoints, 32 tests). Dev1 is free for new work.
- **Decision**: STORY-008 moves to TESTING for QA. STORY-009 (Event system with webhooks) assigned to dev1. Tester to prioritize STORY-008 QA alongside STORY-006.
- **Who**: Product Owner
### DEC-009: STORY-008 bug fixes — BUG-002, BUG-003 (2026-03-27)
- **Context**: QA found 2 bugs during STORY-008 testing. BUG-002 (HIGH): mark_read endpoint mutated DB before ownership check. BUG-003 (MEDIUM): POST /inbox/{agent_id} returned 500 on malformed JSON.
- **Decision**: Fixed both in api.py. BUG-002: added get_message ownership check before mark_read call. BUG-003: added JSONDecodeError try/except returning 422. Added 2 regression tests. STORY-008 moved back to REVIEW.
- **Who**: Developer 1
### DEC-010: Accept STORY-007 and STORY-008 (2026-03-27)
- **Context**: QA approved both stories. STORY-007: 48 tests passing, all acceptance criteria met. STORY-008: 70 tests passing, BUG-002/BUG-003 fixes verified.
- **Decision**: Both accepted and moved to DONE. Dev2 should add cascade delete API test for STORY-007 alongside STORY-011 work (non-blocking).
- **Who**: Product Owner

### DEC-011: Cycle 6 assignments (2026-03-27)
- **Context**: Dev2 free after STORY-007. Dev1 still on STORY-009. 3 TODO stories remain (010, 011, 012).
- **Decision**: STORY-011 (Full-text search) assigned to dev2. STORY-010 (Sprint management) queued for dev1 after STORY-009 completes. STORY-012 (Web UI) stays TODO — needs more backend features stable first.
- **Who**: Product Owner

### DEC-012: STORY-013 Docker finalization (2026-03-27)
- **Context**: New features landed (events/webhooks, search). Docker config needs update for production readiness.
- **Decision**: Finalized Dockerfile with LABEL metadata, PYTHONPATH and PYTHONDONTWRITEBYTECODE env vars, increased start_period to 10s. docker-compose.yml updated with env_file for .env, json-file log driver with rotation (10m/3 files), compose-level healthcheck. .dockerignore updated to exclude tests/ and .pytest_cache/. Moving STORY-013 to REVIEW.
- **Who**: DevOps Engineer
### DEC-013: Accept STORY-009 and STORY-011, assign remaining work (2026-03-27)
- **Context**: QA approved both STORY-009 (75 tests) and STORY-011 (48 tests). Dev1 and dev2 now free. STORY-013 blocked by BUG-004.
- **Decision**: STORY-009 and STORY-011 accepted → DONE. STORY-010 (Sprint management) assigned to dev1. STORY-012 (Web UI — Kanban board) assigned to dev2. STORY-013 remains in REVIEW pending BUG-004 fix.
- **Who**: Product Owner
### DEC-014: BUG-004 fix — .dockerignore tests exclusion (2026-03-27)
- **Context**: `.dockerignore` excluded `tests/`, breaking `Dockerfile.test` build since `COPY tests/ tests/` found nothing in the build context.
- **Decision**: Removed `tests/` from `.dockerignore`. The production `Dockerfile` never COPYs tests, so they won't appear in the production image. The test `Dockerfile.test` can now access `tests/` in the build context. Simple, no per-Dockerfile dockerignore complexity needed.
- **Who**: DevOps Engineer
### DEC-015: Accept STORY-010 and STORY-013, reject STORY-012 (2026-03-27)
- **Context**: QA approved STORY-010 (sprint management) and STORY-013 (Docker deployment, BUG-004 fix verified). STORY-012 (Web UI) failed QA — BUG-005 is a CRITICAL XSS vulnerability.
- **Decision**: STORY-010 and STORY-013 accepted → DONE. STORY-012 rejected and moved back to IN_PROGRESS for dev2 to fix BUG-005. XSS is a hard security blocker — no acceptance until resolved and re-verified by QA.
- **Who**: Product Owner
### DEC-016: Accept STORY-012 — Web UI Kanban board (2026-03-27)
- **Context**: QA re-tested after BUG-005 (CRITICAL XSS) fix. All user-controlled fields now escaped via `escapeHtml()`, no raw innerHTML with user data. 3 regression tests added. BUG-006 (sprint event types) also verified and closed.
- **Decision**: STORY-012 accepted → DONE. 13/14 Sprint 1 stories complete. Only STORY-006 (test suite) remains.
- **Who**: Product Owner
### DEC-017: STORY-006 QA approved — test suite complete (2026-03-27)
- **Context**: STORY-006 (Core test suite) reviewed by dev1, dev2, and QA. 508 tests across 17 files covering all Sprint 1 features.
- **Decision**: QA approves STORY-006. Recommended to PO for acceptance. Minor tech debt (SCHEMA_DICT duplication) noted for Sprint 2.
- **Who**: QA Engineer
### DEC-018: Accept STORY-006 — Sprint 1 complete (2026-03-27)
- **Context**: STORY-006 (Core test suite) unanimously approved by dev1, dev2, and QA. 508 tests across 17 files covering all Sprint 1 features.
- **Decision**: STORY-006 accepted → DONE. Sprint 1 fully closed — 14/14 stories complete.
- **Who**: Product Owner

### DEC-019: Sprint 2 scope and prioritization (2026-03-27)
- **Context**: Sprint 1 complete. PM proposed 6 focus areas for Sprint 2. Dev2 recommended auth as top priority.
- **Decision**: Sprint 2 = production hardening. 7 stories: STORY-015 (auth, CRITICAL), STORY-016 (rate limiting, HIGH), STORY-017 (pagination, HIGH), STORY-018 (monitoring, MEDIUM), STORY-019 (performance, MEDIUM), STORY-020 (API versioning, LOW), STORY-021 (test fixture consolidation, LOW). Auth is the #1 priority — biggest gap for production readiness.
- **Who**: Product Owner
### DEC-020: Sprint 2 kickoff — cycle 10 assignments (2026-03-27)
- **Context**: Sprint 2 scoped with 7 stories. Need to prioritize and assign for parallel execution.
- **Decision**: Starting 4 stories in parallel: STORY-015 (dev2, CRITICAL), STORY-016 (dev1, HIGH), STORY-018 (devops, MEDIUM), STORY-021 (tester, LOW). STORY-017 queued for dev2 after STORY-015. STORY-019 assigned to dev1 (overriding odd-number rule to balance workload — dev2 already has 015+017). STORY-020 deferred.
- **Who**: Project Manager
### DEC-021: Accept STORY-015 and STORY-016, assign next stories (2026-03-27)
- **Context**: QA approved both stories. STORY-015: 87 tests, full RBAC with 3 roles, 30+ permissions, SHA-256 key hashing, thread-safe cache, middleware enforcement. STORY-016: 57 tests, sliding window rate limiter, per-agent isolation, proper HTTP 429 + Retry-After headers, management endpoints.
- **Decision**: Both accepted → DONE. Dev2 starts STORY-017 (cursor-based pagination). Dev1 starts STORY-019 (performance hardening). Both moved to IN_PROGRESS.
- **Who**: Product Owner
### DEC-022: Sprint 2 Cycle 1 — status check (2026-03-27)
- **Context**: First cycle of Sprint 2. Four stories in progress, one TODO, two already DONE.
- **Decision**: All assignments confirmed per DEC-020/DEC-021. STORY-020 (API versioning) stays deferred — lowest priority and no free capacity. Will assign to first dev who completes their current story. Sprint goal is production readiness.
- **Who**: Product Owner
### DEC-023: Accept STORY-017, STORY-018, STORY-019 — assign STORY-020 (2026-03-27)
- **Context**: Three stories in REVIEW. Code reviews show complete implementations: STORY-017 (cursor pagination across all endpoints, 25+ tests), STORY-018 (structured logging, /health, /ready, metrics, 43 tests), STORY-019 (composite indexes, WAL pragmas, connection pooling, N+1 fixes, webhook cache, 668 lines of perf tests).
- **Decision**: All three accepted → DONE. STORY-020 (API versioning) assigned to dev1, who is now free. Sprint 2: 5/7 DONE, 2 remaining (STORY-020, STORY-021).
- **Who**: Product Owner