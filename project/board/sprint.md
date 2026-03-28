# Sprint 1 — Initialization

**Goal**: Establish project foundation — CLI skeleton, data models, provider abstraction, dev environment
**Start**: 2026-03-28 11:19

## TODO

## IN PROGRESS

## REVIEW
- [ ] STORY-012: Basic unit test suite (tester)

## TESTING
- [ ] STORY-007: Implement AWS ECS provider (dev1)

## DONE
- [x] STORY-001: Define MVP scope
- [x] STORY-002: Set up project scaffolding
- [x] STORY-003: Docker development environment
- [x] STORY-004: Implement CLI skeleton with Click
- [x] STORY-005: Define core data models and configuration schema
- [x] STORY-006: Implement provider abstraction layer

## BLOCKED

## Security Analysis [Cycle 12]

### Finding Status Summary

| Finding | Status | Severity |
|---------|--------|----------|
| SEC-001 Redis Exposed | CLOSED (fixed C3) | ~~HIGH~~ |
| SEC-002 Secrets in Config | CLOSED (fixed C2) | ~~MEDIUM~~ |
| SEC-003 Input Validation | CLOSED (fixed C2) | ~~HIGH~~ |
| SEC-006 Port Exposure | CLOSED (fixed C3) | ~~MEDIUM~~ |
| SEC-007 YAML Loading | CLOSED (safe) | ~~INFO~~ |
| SEC-008 SQL Formatting | CLOSED (info) | ~~INFO~~ |
| SEC-009 Healthcheck | CLOSED (fixed C4) | ~~LOW~~ |
| SEC-010 No Auth (deferred) | OPEN (deferred) | MEDIUM |
| SEC-011 Missing SigV4 (ECS) | CLOSED (fixed C6) | ~~HIGH~~ |
| SEC-012 Error Leakage | CLOSED (fixed C4) | ~~MEDIUM~~ |
| SEC-013 Hardcoded Cluster | CLOSED (fixed C6) | ~~LOW~~ |
| SEC-014 TLS Config | CLOSED (fixed C4) | ~~LOW~~ |
| SEC-015 CloudWatch Unsigned | CLOSED (fixed C7) | ~~HIGH~~ |
| SEC-016 Public IP Default | CLOSED (verified C8) | ~~MEDIUM~~ |
| SEC-017 Cluster State Mutation | CLOSED (verified C8) | ~~LOW~~ |

### Cycle 12 — Maintenance Review

No source code changes since Cycle 8. All workspace files confirmed unchanged. Security posture remains **GREEN**.

**Existing controls verified intact:**
- `yaml.safe_load` in config.py (no unsafe deserialization)
- Parameterized SQL in db.py (all queries use `?` placeholders)
- Input validation in validation.py (regex allowlist `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$`)
- Path traversal protection in config.py (`_validate_db_path`)
- SigV4 signing on all AWS API calls via `_sign_and_merge_headers()`
- Credentials fail-closed (`_get_aws_credentials` raises on missing keys)
- Generic error messages to users; details at DEBUG only
- `assign_public_ip` defaults `False`
- Docker: non-root user, ports on 127.0.0.1, Redis password-protected
- TLS verification enabled (`verify=True`)

### New Findings — Cycle 12

(none)

### Open Items

**SEC-010 (No Auth — Deferred)**: Remains deferred. No web endpoints exist. Will become actionable when STORY-011 (web dashboard) enters development. Auth middleware, rate limiting, and CORS must be implemented before any HTTP listener goes live.

### Sprint 2 Pre-Review — Threat Model Notes

PM flagged STORY-009 and STORY-010 for proactive security review. Documenting anticipated attack surface for dev guidance:

**STORY-009 (SQLite State Tracking)**: Existing `db.py` already uses parameterized queries — new code must maintain this pattern. Watch for: (1) any string-formatted SQL, (2) DB file permissions (should be 0600 or project-directory-scoped), (3) no user-controlled table/column names in dynamic queries, (4) VACUUM/integrity checks if DB is user-accessible.

**STORY-010 (Rollback Support)**: Rollback logic must validate deployment IDs against DB before acting. Watch for: (1) TOCTOU between "check deployment exists" and "execute rollback", (2) rollback to attacker-controlled image tag, (3) missing authorization — any user who can deploy should not automatically be able to roll back prod. Recommend rollback target validation: only allow rollback to previously-successful deployment IDs from the DB.
## Security Analysis [Cycle 10]

### Finding Status Summary

| Finding | Status | Severity |
|---------|--------|----------|
| SEC-001 Redis Exposed | CLOSED (fixed C3) | ~~HIGH~~ |
| SEC-002 Secrets in Config | CLOSED (fixed C2) | ~~MEDIUM~~ |
| SEC-003 Input Validation | CLOSED (fixed C2) | ~~HIGH~~ |
| SEC-006 Port Exposure | CLOSED (fixed C3) | ~~MEDIUM~~ |
| SEC-007 YAML Loading | CLOSED (safe) | ~~INFO~~ |
| SEC-008 SQL Formatting | CLOSED (info) | ~~INFO~~ |
| SEC-009 Healthcheck | CLOSED (fixed C4) | ~~LOW~~ |
| SEC-010 No Auth (deferred) | OPEN (deferred) | MEDIUM |
| SEC-011 Missing SigV4 (ECS) | CLOSED (fixed C6) | ~~HIGH~~ |
| SEC-012 Error Leakage | CLOSED (fixed C4) | ~~MEDIUM~~ |
| SEC-013 Hardcoded Cluster | CLOSED (fixed C6) | ~~LOW~~ |
| SEC-014 TLS Config | CLOSED (fixed C4) | ~~LOW~~ |
| SEC-015 CloudWatch Unsigned | CLOSED (fixed C7) | ~~HIGH~~ |
| SEC-016 Public IP Default | CLOSED (verified C8) | ~~MEDIUM~~ |
| SEC-017 Cluster State Mutation | CLOSED (verified C8) | ~~LOW~~ |

### Cycle 10 — Maintenance Review

No source code changes since Cycle 8. All workspace files confirmed unchanged. Security posture remains **GREEN**.

**Existing controls verified intact:**
- `yaml.safe_load` in config.py (no unsafe deserialization)
- Parameterized SQL in db.py (all queries use `?` placeholders)
- Input validation in validation.py (regex allowlist `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$`)
- Path traversal protection in config.py (`_validate_db_path`)
- SigV4 signing on all AWS API calls via `_sign_and_merge_headers()`
- Credentials fail-closed (`_get_aws_credentials` raises on missing keys)
- Generic error messages to users; details at DEBUG only
- `assign_public_ip` defaults `False`
- Docker: non-root user, ports on 127.0.0.1, Redis password-protected
- TLS verification enabled (`verify=True`)

### New Findings — Cycle 10

(none)

### Open Items

**SEC-010 (No Auth — Deferred)**: Remains deferred. No web endpoints exist. Will become actionable when STORY-011 (web dashboard) enters development. Auth middleware, rate limiting, and CORS must be implemented before any HTTP listener goes live.

### Pending Reviews

- **STORY-007 (AWS ECS provider)**: In TESTING — will perform targeted pentest once verified by QA.
- **STORY-012 (Unit test suite)**: In REVIEW — will review test coverage for security-relevant paths.