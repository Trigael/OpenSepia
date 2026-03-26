# Product Backlog — Board Server v2

## CRITICAL

### STORY-001: Define MVP scope
**Priority**: CRITICAL
**Assigned**: po
**Status**: DONE

**As a** product owner **I want** a clear MVP definition **so that** the team knows what to build.

**Acceptance criteria**:
- [x] Product vision documented
- [x] MVP broken into user stories
- [x] Stories prioritized in backlog

### STORY-003: Core API scaffold with FastAPI
**Priority**: CRITICAL
**Assigned**: dev1
**Status**: TODO

**As a** developer **I want** a FastAPI project structure with routing, error handling, and config **so that** we have a solid foundation to build on.

**Acceptance criteria**:
- [ ] FastAPI app with health endpoint (`GET /health`)
- [ ] Project structure: `src/api/`, `src/models/`, `src/services/`, `src/config/`
- [ ] Config loading from environment variables
- [ ] Proper error handling middleware
- [ ] Pydantic models for request/response validation
- [ ] App runs with `uvicorn`

### STORY-004: Database models and MongoDB integration
**Priority**: CRITICAL
**Assigned**: dev2
**Status**: TODO

**As a** developer **I want** MongoDB models for boards, items, and sprints **so that** data is persisted properly.

**Acceptance criteria**:
- [ ] MongoDB connection with motor (async driver)
- [ ] Board model: id, name, description, created_at, updated_at
- [ ] Item model: id, board_id, title, description, status, priority, assigned, story_id, created_at, updated_at
- [ ] Sprint model: id, board_id, name, goal, start_date, end_date, items[]
- [ ] Database initialization and index creation
- [ ] Connection pooling configured

## HIGH

### STORY-002: Set up development environment
**Priority**: HIGH
**Assigned**: devops
**Status**: TODO

**As a** developer **I want** a working dev environment with Docker, linting, and CI **so that** the team can develop and test efficiently.

**Acceptance criteria**:
- [ ] Dockerfile for the API server
- [ ] docker-compose.yml with API + MongoDB
- [ ] requirements.txt with pinned dependencies
- [ ] Makefile with common commands (run, test, lint)
- [ ] Basic CI pipeline config (lint + test)
- [ ] .env.example with required variables

### STORY-005: CRUD endpoints for boards
**Priority**: HIGH
**Assigned**: dev1
**Status**: TODO

**As a** user **I want** to create, read, update, and delete boards **so that** I can manage my projects.

**Acceptance criteria**:
- [ ] `POST /api/boards` — create board
- [ ] `GET /api/boards` — list boards (with pagination)
- [ ] `GET /api/boards/{id}` — get board detail
- [ ] `PUT /api/boards/{id}` — update board
- [ ] `DELETE /api/boards/{id}` — delete board
- [ ] Input validation with Pydantic
- [ ] Unit tests for all endpoints

### STORY-006: CRUD endpoints for items
**Priority**: HIGH
**Assigned**: dev1
**Status**: TODO

**As a** user **I want** to create, read, update, and delete items on a board **so that** I can track work.

**Acceptance criteria**:
- [ ] `POST /api/boards/{id}/items` — create item
- [ ] `GET /api/boards/{id}/items` — list items (filterable by status, priority, assigned)
- [ ] `GET /api/items/{id}` — get item detail
- [ ] `PUT /api/items/{id}` — update item (including status transitions)
- [ ] `DELETE /api/items/{id}` — delete item
- [ ] Status transition validation (only valid transitions allowed)
- [ ] Unit tests for all endpoints

### STORY-007: WebSocket real-time updates
**Priority**: HIGH
**Assigned**: dev2
**Status**: TODO

**As a** client **I want** real-time updates via WebSocket **so that** all connected clients see changes immediately.

**Acceptance criteria**:
- [ ] WebSocket endpoint at `/ws/boards/{id}`
- [ ] Broadcasts item create/update/delete events to all connected clients
- [ ] JSON message format with event type, item data, and timestamp
- [ ] Connection management (join/leave board rooms)
- [ ] Heartbeat/ping to detect stale connections
- [ ] Unit tests with WebSocket test client

## MEDIUM

### STORY-008: Full-text search
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TODO

**As a** user **I want** to search items by title and description **so that** I can quickly find what I need.

**Acceptance criteria**:
- [ ] `GET /api/search?q=term&board_id=X` endpoint
- [ ] MongoDB text index on item title + description
- [ ] Results ranked by relevance
- [ ] Pagination support
- [ ] Highlights matched terms in response

### STORY-009: Role-based access control
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: TODO

**As an** admin **I want** role-based access control **so that** users only see and do what they're allowed to.

**Acceptance criteria**:
- [ ] User model with roles: admin, member, viewer
- [ ] JWT authentication middleware
- [ ] Role-based permission checks on all endpoints
- [ ] Board-level membership (users belong to boards with roles)
- [ ] Admin can manage users and board membership

### STORY-010: Sprint management with burndown
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: TODO

**As a** project manager **I want** sprint management with burndown data **so that** I can track progress.

**Acceptance criteria**:
- [ ] CRUD endpoints for sprints
- [ ] Assign/remove items to/from sprints
- [ ] `GET /api/sprints/{id}/burndown` returns daily remaining story points
- [ ] Sprint status: planning, active, completed
- [ ] Only one active sprint per board at a time

### STORY-011: File attachments on items
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: TODO

**As a** user **I want** to attach files to items **so that** I can share relevant documents.

**Acceptance criteria**:
- [ ] `POST /api/items/{id}/attachments` — upload file
- [ ] `GET /api/items/{id}/attachments` — list attachments
- [ ] `DELETE /api/attachments/{id}` — delete attachment
- [ ] File storage on disk with configurable path
- [ ] Max file size limit (configurable, default 10MB)
- [ ] File type validation

## LOW

### STORY-012: Angular kanban frontend
**Priority**: LOW
**Assigned**: dev2
**Status**: TODO

**As a** user **I want** a drag-and-drop kanban board UI **so that** I can visually manage items.

**Acceptance criteria**:
- [ ] Angular app with board view
- [ ] Columns for each status (TODO, IN_PROGRESS, REVIEW, TESTING, DONE)
- [ ] Drag-and-drop items between columns (updates status via API)
- [ ] Real-time updates via WebSocket
- [ ] Create/edit item dialog
- [ ] Responsive layout

## DONE