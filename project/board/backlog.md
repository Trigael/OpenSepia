# Product Backlog — AgentBoard

## CRITICAL

(none)

## HIGH

### BUG-006: Rate limiter memory exhaustion (PENTEST-009)
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

**As a** system administrator **I want** the rate limiter to bound its memory usage **so that** an attacker cannot exhaust server memory by generating many unique client keys.

**Acceptance criteria**:
- [ ] Rate limiter evicts stale entries (e.g., LRU or time-based expiry)
- [ ] Maximum number of tracked clients is bounded (configurable, default 10000)
- [ ] Memory usage stays constant under sustained load from many unique IPs
- [ ] Existing rate limiting behavior unchanged for normal traffic
- [ ] Unit test demonstrating memory bound under adversarial load

### BUG-007: Dashboard HTML partials served without authentication (PENTEST-007)
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

**As a** security engineer **I want** dashboard endpoints to require authentication **so that** board data is not exposed to unauthenticated users.

**Acceptance criteria**:
- [ ] All /dashboard/* endpoints require valid session cookie
- [ ] Unauthenticated requests to dashboard partials return 401 or redirect to login
- [ ] /dashboard/login remains accessible without authentication
- [ ] Existing dashboard functionality unchanged for authenticated users
- [ ] Integration test verifying unauthenticated access is blocked

## MEDIUM

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

### STORY-026: Import/export API (JSON/CSV)
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TODO

**As a** project manager **I want** to export all items as JSON or CSV and import from those formats **so that** I can migrate data or create reports.

**Acceptance criteria**:
- [ ] GET /api/export?format=json — export all items with labels, comments as JSON
- [ ] GET /api/export?format=csv — export items as flat CSV (one row per item)
- [ ] POST /api/import — import items from JSON (same schema as export)
- [ ] Import validates all required fields before inserting
- [ ] Import supports "upsert" mode (update existing items by ID, create new ones)
- [ ] Audit log entry for import/export operations

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

### STORY-030: Tags and custom fields API
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TODO

**As a** project manager **I want** to define custom fields on work items **so that** teams can track project-specific metadata without schema changes.

**Acceptance criteria**:
- [ ] POST /api/custom-fields — define field {name, type: text|number|boolean|select, options (for select)}
- [ ] GET /api/custom-fields — list defined fields
- [ ] DELETE /api/custom-fields/{id} — remove field definition and all values
- [ ] PATCH /api/items/{id} accepts custom_fields: {field_name: value}
- [ ] Custom field values validated against field type
- [ ] Custom fields included in item detail and export responses
- [ ] GET /api/items?custom.{field_name}={value} — filter by custom field

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

### STORY-033: Cycle velocity tracking API
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TODO

**As a** project manager **I want** to track how many story points or items are completed per cycle/sprint **so that** I can forecast capacity and detect slowdowns.

**Acceptance criteria**:
- [ ] GET /api/metrics/velocity — return per-cycle completion counts
- [ ] Response: list of {cycle_id, sprint_id, items_completed, items_added, items_carried_over, date}
- [ ] GET /api/metrics/velocity/trend — rolling average over last N cycles (default 5)
- [ ] Dashboard widget showing velocity chart data
- [ ] Computed from audit log + sprint history

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

## LOW

(none)

## DONE

### BUG-005: Agent-written source files silently deleted from workspace
**Priority**: CRITICAL
**Assigned**: devops
**Status**: DONE

### STORY-013: Security hardening — fix all RE-OPENED findings
**Priority**: CRITICAL
**Assigned**: dev1
**Status**: DONE

### BUG-002: AgentCommitStep merge-on-DONE causes file disappearances
**Priority**: CRITICAL
**Assigned**: devops
**Status**: DONE

### BUG-003: Merge conflict markers staged by git add -A
**Priority**: HIGH
**Assigned**: devops
**Status**: DONE

### BUG-004: Merge story branches on REVIEW status, not just DONE
**Priority**: HIGH
**Assigned**: devops
**Status**: DONE

### STORY-001: Define AgentBoard product vision and architecture
**Priority**: HIGH
**Assigned**: po
**Status**: REVIEW

### STORY-002: Set up FastAPI project scaffold with SQLite and health endpoint
**Priority**: HIGH
**Assigned**: dev1
**Status**: IN_PROGRESS

### STORY-003: Work item CRUD API for stories and bugs
**Priority**: HIGH
**Assigned**: dev2
**Status**: TODO

### STORY-004: Agent inbox messaging API
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

### STORY-005: Board state endpoint with markdown export
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

### STORY-006: Pages / document storage API
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: DONE

### STORY-007: Sprint / cycle management API
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: DONE

### STORY-008: Story comments API
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

### STORY-009: Audit log and activity tracking
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: DONE

### STORY-010: Human supervision dashboard (htmx)
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

### STORY-011: Supervision queue and approval workflow
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

### STORY-012: MR/PR proxy API
**Priority**: LOW
**Assigned**: dev1
**Status**: DONE

### STORY-014: Labels API
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

### STORY-015: Bulk operations API
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

### STORY-016: Pagination on all list endpoints
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

### STORY-017: Search endpoint for items
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

### STORY-018: Snapshot/backup API
**Priority**: HIGH
**Assigned**: devops
**Status**: DONE

### STORY-019: WebSocket ticket-based auth
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

### STORY-020: Rollback support
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TESTING

### STORY-021: Per-agent capability rules
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

### STORY-022: Rate limiting middleware
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

### STORY-024: Configuration API
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: TODO

### STORY-025: Health check with DB stats
**Priority**: MEDIUM
**Assigned**: devops
**Status**: DONE

### STORY-027: Notification/webhook system
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

### STORY-028: Item relations API
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: DONE

### STORY-034: Fix SEC-015 — require API key for production
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

### STORY-035: Fix PENTEST-004 — supervision queue pagination
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

### STORY-037: API versioning
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE
