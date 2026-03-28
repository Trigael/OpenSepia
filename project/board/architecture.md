# Architecture — AgentBoard

## Product Vision

AgentBoard is an agent-first project management API. It replaces Jira/Plane for AI agent teams by providing:
- REST API for work items (stories/bugs) with status tracking and priority management
- First-class agent inbox messaging (per-agent endpoints, not comment threading)
- Pages/document storage for architecture docs, standups, decisions
- Markdown-native context builder (sprint.md and backlog.md output)
- Cycle/sprint management with assignment
- Board state endpoint returning items grouped by status
- Human supervision dashboard with htmx UI, audit trail, WebSocket live updates
- Supervision queue for human approval of agent output
- Danger detection for destructive changes
- Per-agent capability rules

The API implements all endpoints needed by the OpenSepia BoardAdapter (15 methods) and BoardProvider (25+ methods) interfaces.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI (Python 3.10+) |
| Database | SQLite (async via aiosqlite), upgradeable to PostgreSQL |
| Migrations | Manual SQL scripts in migrations/ folder |
| Dashboard | htmx + minimal CSS |
| Live updates | WebSocket (fastapi.websockets) |
| Testing | pytest + httpx (async test client) |
| Config | Environment variables via python-dotenv |

## Data Model

### work_items
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | PK, auto-increment |
| item_id | TEXT | UNIQUE — "STORY-001", "BUG-003" |
| type | TEXT | "story" or "bug" |
| title | TEXT | NOT NULL |
| description | TEXT | Markdown body |
| status | TEXT | todo, in_progress, review, testing, done, blocked |
| priority | TEXT | critical, high, medium, low |
| assigned | TEXT | Agent ID: po, pm, dev1, dev2, devops, tester, etc. |
| labels | TEXT | JSON array of label strings |
| sprint_id | INTEGER | FK to sprints.id (nullable) |
| is_deleted | BOOLEAN | Soft delete flag, default false |
| created_at | TEXT | ISO 8601 timestamp |
| updated_at | TEXT | ISO 8601 timestamp |

Auto-ID logic: separate sequences for STORY-NNN and BUG-NNN. On create, if no item_id provided, auto-assign next available.

### inbox_messages
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | PK |
| from_agent | TEXT | Sender agent ID |
| to_agent | TEXT | Recipient agent ID |
| message | TEXT | Markdown content |
| created_at | TEXT | ISO 8601 |

### pages
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | PK |
| slug | TEXT | UNIQUE — "architecture", "standup-s1c3" |
| title | TEXT | Display title |
| content | TEXT | Markdown body |
| created_at | TEXT | ISO 8601 |
| updated_at | TEXT | ISO 8601 |

### sprints
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | PK |
| name | TEXT | "Sprint 1", "Sprint 2" |
| goal | TEXT | Sprint goal description |
| start_date | TEXT | ISO 8601 |
| end_date | TEXT | ISO 8601 (nullable) |
| status | TEXT | active, completed, planned |

### comments
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | PK |
| item_id | TEXT | FK to work_items.item_id |
| agent_id | TEXT | Author agent ID |
| body | TEXT | Markdown content |
| system | BOOLEAN | True for auto-generated notes |
| created_at | TEXT | ISO 8601 |

### audit_log
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | PK |
| agent_id | TEXT | Who did it |
| action | TEXT | "create_item", "update_status", "send_message", etc. |
| target_type | TEXT | "work_item", "inbox", "page", etc. |
| target_id | TEXT | ID of affected entity |
| detail | TEXT | JSON blob with old/new values |
| created_at | TEXT | ISO 8601 |

## Entity Relationships

```
sprints 1──N work_items
work_items 1──N comments
work_items (soft-delete via is_deleted)
inbox_messages: standalone (from_agent → to_agent)
pages: standalone documents
audit_log: references any entity by (target_type, target_id)
```

## API Endpoints

### Health
- `GET /api/health` — server status + DB connectivity

### Work Items (BoardProvider: create_issue, close_issue, reopen_issue, update_issue_labels, update_issue_status, find_issue_by_id, list_issues, search_issues)
- `POST /api/items` — create work item `{type, title, description, status, priority, assigned, labels, sprint_id}`
- `GET /api/items` — list items. Query params: `status`, `priority`, `assigned`, `type`, `sprint_id`, `state` (open/closed/all)
- `GET /api/items/{item_id}` — get single item by STORY-001 or BUG-001
- `PATCH /api/items/{item_id}` — update fields
- `DELETE /api/items/{item_id}` — soft-delete
- `PUT /api/items/{item_id}` — upsert (create-or-update)
- `POST /api/items/{item_id}/reopen` — reopen soft-deleted item
- `PATCH /api/items/{item_id}/labels` — replace labels
- `PATCH /api/items/{item_id}/status` — update status `{from_status, to_status}`
- `GET /api/items/search?q=query` — full-text search

### Comments (BoardProvider: comment_on_issue, get_issue_comments)
- `POST /api/items/{item_id}/comments` — add comment `{agent_id, body}`
- `GET /api/items/{item_id}/comments` — list comments. Query: `limit`

### Inbox (BoardAdapter: get_inbox, archive_inbox, send_inbox_message)
- `GET /api/inbox/{agent_id}` — list messages for agent
- `POST /api/inbox/{agent_id}` — send message `{from_agent, message}`
- `DELETE /api/inbox/{agent_id}` — archive and clear inbox

### Board (BoardAdapter: get_board_summary; BoardProvider: get_board_state, get_board_summary_md)
- `GET /api/board` — items grouped by status `{todo: [...], in_progress: [...], ...}`
- `GET /api/board/summary` — counts by status `{todo: 5, in_progress: 3, ...}`
- `GET /api/board/sprint.md` — markdown export in sprint.md format
- `GET /api/board/backlog.md` — markdown export in backlog.md format

### Pages (document storage)
- `POST /api/pages` — create page `{slug, title, content}`
- `GET /api/pages` — list all pages
- `GET /api/pages/{slug}` — get page by slug
- `PATCH /api/pages/{slug}` — update page
- `DELETE /api/pages/{slug}` — delete page

### Sprints / Cycles
- `POST /api/sprints` — create sprint `{name, goal, start_date}`
- `GET /api/sprints` — list sprints
- `GET /api/sprints/{id}` — get sprint
- `PATCH /api/sprints/{id}` — update sprint
- `GET /api/sprints/{id}/items` — list items in sprint

### Snapshots (BoardAdapter: create_snapshot)
- `POST /api/snapshots` — create board snapshot
- `GET /api/snapshots` — list snapshots

### MR/PR Proxy (BoardProvider: create_mr, list_mrs, get_mr, comment_on_mr, approve_mr, merge_mr, close_mr, get_open_mrs_md, get_mr_changes, get_mr_approvals)
- `POST /api/mrs` — create MR `{source_branch, target_branch, title, description}`
- `GET /api/mrs` — list MRs. Query: `state`
- `GET /api/mrs/{mr_id}` — get MR
- `POST /api/mrs/{mr_id}/comments` — comment on MR
- `POST /api/mrs/{mr_id}/approve` — approve MR
- `POST /api/mrs/{mr_id}/merge` — merge MR `{squash: bool}`
- `POST /api/mrs/{mr_id}/close` — close MR
- `GET /api/mrs/{mr_id}/changes` — get MR diff/changes
- `GET /api/mrs/{mr_id}/approvals` — get approval status

### Audit Log
- `GET /api/audit` — list audit entries. Query: `agent_id`, `action`, `target_type`, `limit`

## BoardAdapter Method Mapping (15 methods)

| BoardAdapter Method | AgentBoard Endpoint |
|---|---|
| get_agent_context | Composite: GET /api/board/sprint.md + backlog.md + inbox + standup |
| apply_agent_output | Composite: PATCH /api/items + POST /api/pages |
| get_inbox | GET /api/inbox/{agent_id} |
| archive_inbox | DELETE /api/inbox/{agent_id} |
| init_standup | POST /api/pages (slug: standup-s{N}c{N}) |
| ensure_board_ready | POST /api/health (init check) |
| get_sprint_text | GET /api/board/sprint.md |
| get_backlog_text | GET /api/board/backlog.md |
| get_standup_text | GET /api/pages/standup-current |
| get_sprint_number | GET /api/sprints?status=active |
| get_active_story_ids | GET /api/items?status=todo,in_progress,review,testing |
| get_board_summary | GET /api/board/summary |
| check_board_health | GET /api/health |
| create_snapshot | POST /api/snapshots |
| send_inbox_message | POST /api/inbox/{agent_id} |

## Sprint 1 Scope (MVP)

Sprint 1 delivers the core API without auth or dashboard:
1. **STORY-002**: FastAPI scaffold, SQLite, health endpoint
2. **STORY-003**: Work item CRUD (the heart of the system)
3. **STORY-004**: Agent inbox messaging
4. **STORY-005**: Board state + markdown export

No authentication in Sprint 1. No dashboard. No supervision queue. Those come in Sprint 2+.

## Project Structure (target)

```
workspace/
├── src/
│   └── agentboard/
│       ├── __init__.py
│       ├── main.py          # FastAPI app + lifespan
│       ├── config.py         # Settings from env vars
│       ├── database.py       # SQLite connection + init
│       ├── models.py         # Pydantic models (request/response)
│       ├── routers/
│       │   ├── health.py
│       │   ├── items.py
│       │   ├── inbox.py
│       │   ├── board.py
│       │   ├── pages.py
│       │   ├── sprints.py
│       │   └── comments.py
│       └── migrations/
│           └── 001_initial.sql
├── tests/
│   ├── conftest.py           # Shared fixtures (test client, test DB)
│   ├── test_health.py
│   ├── test_items.py
│   ├── test_inbox.py
│   ├── test_board.py
│   └── test_pages.py
├── config/
│   └── .env.example
├── requirements.txt
└── pyproject.toml
```