# Sprint 9 — Documentation, Observability & Production Readiness

**Goal**: Deliver OpenAPI docs (STORY-023), attachments (STORY-029), activity filtering (STORY-031), agent metrics (STORY-032), and PostgreSQL support (STORY-036)
**Start**: 2026-03-28
**End**: 2026-04-01
**Carry-over**: none

## Stories

### STORY-023: OpenAPI/Swagger documentation
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TODO

**As a** developer integrating with AgentBoard **I want** auto-generated OpenAPI documentation **so that** I can discover and understand all endpoints without reading source code.

**Acceptance criteria**:
- [ ] GET /docs — Swagger UI accessible (FastAPI built-in)
- [ ] GET /openapi.json — full OpenAPI 3.0 spec
- [ ] All endpoints have summary and description
- [ ] All request/response models documented with examples
- [ ] Authentication scheme documented (API key header)
- [ ] Error responses documented (400, 401, 403, 404, 429)

### STORY-029: Item attachments API
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: TODO

**As an** agent **I want** to attach files (logs, screenshots, diffs) to work items **so that** context is preserved alongside the item.

**Acceptance criteria**:
- [ ] POST /api/items/{id}/attachments — upload file (multipart/form-data)
- [ ] GET /api/items/{id}/attachments — list attachments with metadata
- [ ] GET /api/attachments/{id} — download attachment
- [ ] DELETE /api/attachments/{id} — delete attachment
- [ ] Max file size: 10MB, configurable
- [ ] Stored on local filesystem in ./attachments/ directory
- [ ] Attachment metadata in DB (filename, size, mime_type, uploaded_by, created_at)

### STORY-031: Activity feed filtering
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: TODO

**As a** human supervisor **I want** to filter the activity feed by agent, action type, item, and date range **so that** I can investigate specific events efficiently.

**Acceptance criteria**:
- [ ] GET /api/activity accepts filters: agent_id, action, item_id, date_from, date_to
- [ ] Multiple filters combine with AND logic
- [ ] Paginated with same envelope as STORY-016
- [ ] Action types: created, updated, transitioned, commented, approved, rejected, deleted
- [ ] Date filtering uses ISO 8601 format
- [ ] Dashboard activity feed supports the same filters via query params

### STORY-032: Agent performance metrics API
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TODO

**As a** project manager **I want** to view per-agent metrics (items completed, avg cycle time, rejection rate) **so that** I can identify bottlenecks and improve team efficiency.

**Acceptance criteria**:
- [ ] GET /api/metrics/agents — return per-agent stats
- [ ] Metrics per agent: items_completed, items_rejected, avg_cycle_time_hours, items_in_progress
- [ ] GET /api/metrics/agents/{id} — detailed metrics for one agent
- [ ] Optional date range filter (date_from, date_to)
- [ ] Computed from audit log data (no separate metrics store)
- [ ] Response cached for 5 minutes

### STORY-036: PostgreSQL migration support
**Priority**: MEDIUM
**Assigned**: devops
**Status**: TODO

**As a** system administrator **I want** to run AgentBoard on PostgreSQL instead of SQLite **so that** the system can handle concurrent writes and larger deployments.

**Acceptance criteria**:
- [ ] DATABASE_URL env var selects backend: sqlite:///path or postgresql://...
- [ ] All SQL queries compatible with both SQLite and PostgreSQL
- [ ] Migration script to move data from SQLite to PostgreSQL
- [ ] Connection pooling configured for PostgreSQL (default pool size 5)
- [ ] CI runs tests against both backends
- [ ] SQLite remains the default for single-node deployments

## Bugs

(none)