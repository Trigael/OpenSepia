# Sprint 1 — Initialization

**Goal**: Establish project foundation — CLI skeleton, data models, provider abstraction, dev environment
**Start**: 2026-03-28 11:19

## TODO

## IN PROGRESS
- [ ] STORY-005: Define core data models and configuration schema (dev2)
- [ ] STORY-002: Set up development environment (devops)
- [ ] STORY-007: Implement AWS ECS provider (dev1)
- [ ] STORY-012: Basic unit test suite (tester)

## REVIEW
- [x] STORY-004: Implement CLI skeleton with Click (dev1)
- [x] STORY-006: Implement provider abstraction layer (dev1)

## DONE
- [x] STORY-001: Define MVP scope (po)
- [x] STORY-003: Create initial project structure (devops)

## BLOCKED

## Security Analysis [Cycle 3]

### Re-review of Previous Findings

**SEC-001 (Redis Exposed) — VERIFIED FIXED**
Redis now has `--requirepass ${REDIS_PASSWORD}` (docker-compose.yml:26) and port bound to `127.0.0.1:6379:6379` (line 28). Healthcheck uses auth flag. Properly depends on service_healthy. Good work, devops.

**SEC-002 (Secrets in Config) — VERIFIED FIXED (Cycle 2)**
`config.py` uses `${ENV:VAR_NAME}` with strict regex. No secrets in `clouddeploy.yaml`. Remains good.

**SEC-003 (Input Validation) — VERIFIED FIXED (Cycle 2)**
`validation.py` allowlists remain effective. Test coverage includes injection attempts and path traversal (`test_validation.py`). Remains good.

**SEC-006 (Docker Compose Exposes Ports) — VERIFIED FIXED**
Both app (line 8: `127.0.0.1:8080:8080`) and Redis (line 28: `127.0.0.1:6379:6379`) now bind to localhost only. Inter-service uses `clouddeploy-net` bridge. Good.

**SEC-007 (YAML safe_load) — VERIFIED SAFE**
`config.py:123` uses `yaml.safe_load()`. No `yaml.load()` anywhere in codebase. Closed.

**SEC-008 (SQL String Formatting in db.py) — DOWNGRADED TO INFO**
Re-reviewed `db.py:91-103`. The f-string in `update_status()` uses only hardcoded column name strings (`"status = ?"`, `"finished_at = ?"`, `"message = ?"`). All values are parameterized. This is a safe pattern. While not ideal stylistically, it's not exploitable and all callers pass `DeploymentStatus` enum or string literals. Downgraded from LOW to INFO — no action required.

### New Findings

### SEC-009: Dockerfile HEALTHCHECK Leaks Internal URL Pattern
**Severity**: LOW
**CVSS**: 2.0
**Category**: A05 Security Misconfiguration
**File**: Dockerfile:30
**Description**: The HEALTHCHECK command uses `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"`. While functionally correct, this embeds the health endpoint path in the image metadata visible to anyone with `docker inspect` access. More importantly, the healthcheck uses an unvalidated HTTP request — if the `/health` endpoint ever returns a redirect to an external URL, `urlopen` will follow it.
**Impact**: Low — container metadata exposure is minor. The redirect-following behavior is theoretical but worth noting for defense-in-depth.
**Recommendation**: Consider using `CMD ["curl", "-f", "http://localhost:8080/health"]` if curl is available, or add a simple healthcheck script that doesn't follow redirects. Not urgent.

### SEC-010: No Rate Limiting or Authentication on App Service
**Severity**: MEDIUM (Deferred)
**Category**: A07 Identification and Authentication Failures
**Description**: The app service exposes port 8080 (localhost only, which is good) but there is no authentication middleware, API key requirement, or rate limiting mentioned in any code. The CLI currently has no web-facing endpoints implemented yet, so this is a **forward-looking finding** — when the web dashboard (STORY-011) and API endpoints are built, authentication and rate limiting MUST be implemented from the start.
**Impact**: Deferred — no exploitable surface exists yet.
**Recommendation**: When implementing STORY-011 (web dashboard), include: (1) API key or session-based auth, (2) rate limiting middleware, (3) CORS configuration. Filing as a tracking item for sec_analyst to add to the security requirements.

### Summary — Cycle 3 Security Posture

| Finding | Status | Severity |
|---------|--------|----------|
| SEC-001 Redis Exposed | **FIXED** | ~~HIGH~~ |
| SEC-002 Secrets in Config | **FIXED** | ~~MEDIUM~~ |
| SEC-003 Input Validation | **FIXED** | ~~HIGH~~ |
| SEC-006 Port Exposure | **FIXED** | ~~MEDIUM~~ |
| SEC-007 YAML Loading | **SAFE** | ~~INFO~~ |
| SEC-008 SQL Formatting | Downgraded | INFO |
| SEC-009 Healthcheck | NEW | LOW |
| SEC-010 No Auth (deferred) | NEW | MEDIUM (deferred) |

**Overall**: Security posture has significantly improved. All critical and high findings from Cycles 1-2 are resolved. Remaining items are low-severity or deferred. The codebase demonstrates good security practices: parameterized SQL, input validation, safe YAML loading, localhost-only ports, non-root Docker user, multi-stage builds. Well done team.