# Sprint 6 — v1.0 Release

**Goal**: Fix all open security findings, polish CLI help, and complete release checklist to ship CloudDeploy v1.0
**Start**: 2026-03-28 14:18

## TODO

## IN PROGRESS

### STORY-021: v1.0 release checklist
**Priority**: HIGH
**Assigned**: devops
**Status**: IN_PROGRESS

**As a** maintainer **I want** a complete release checklist executed **so that** v1.0 is tagged, documented, and ready to distribute

**Acceptance criteria**:
- [x] Version bumped to 1.0.0 in `pyproject.toml` and `__init__.py`
- [x] CHANGELOG.md created with all features from Sprints 1-6
- [x] README.md with quickstart guide, installation, and usage examples
- [ ] All tests pass (`pytest tests/ -v` and `pytest tests/integration/ -v`) — reassigned to dev1
- [x] Dockerfile builds and runs successfully
- [x] Git tag `v1.0.0` ready (do not push) — reassigned to dev2

## REVIEW

## TESTING

## DONE

(completed stories omitted)

## BLOCKED

## Active Blockers
(none)

## Security Analysis [cycle 14]

### Summary

**All security findings resolved.** SEC-008 fix verified — `docker-compose.yml:242` now reads `["CMD-SHELL", "REDISCLI_AUTH=$REDIS_PASSWORD redis-cli ping"]`. The Redis password is no longer exposed in process listings.

**Verified fixes (all in place):**
- SEC-004 (db_path traversal) — `_validate_db_path()` in `config.py:140` rejects absolute paths and `..` traversal. ✅
- SEC-008 (Redis password in process listing) — `docker-compose.yml:242` uses `REDISCLI_AUTH` env var with `CMD-SHELL`. ✅ **FIX VERIFIED**
- SEC-020 (rollback to non-succeeded) — `cli.py:490` enforces `status == SUCCEEDED` check. ✅
- SEC-021 (TOCTOU on rollback) — `cli.py:505` caches `latest_deployment` before confirm prompt. ✅

**Security posture (unchanged):**
- Parameterized SQL everywhere — no injection vectors
- `yaml.safe_load` only — no deserialization risk
- Strict input validation via regex in `validation.py`
- TLS verification enforced (`verify=True`) on all provider HTTP clients
- Fail-closed credential loading from env vars
- Fernet encryption for secrets at rest; key file `0o600`
- HTML-escaped dashboard templates — no XSS
- Hardened Dockerfile: multi-stage, non-root, read-only FS, resource limits
- Docker Compose localhost-only port bindings
- Sensitive env vars masked in CLI output

### Open Findings

### SEC-007: Dashboard has no authentication or authorization
**Severity**: MEDIUM
**Category**: Broken Access Control (OWASP A01)
**File**: src/clouddeploy/dashboard/app.py:32-176
**Description**: All dashboard endpoints are publicly accessible with zero authentication.
**Impact**: Information disclosure to anyone who can reach the server.
**Mitigation**: Default `--host 127.0.0.1` and docker-compose `127.0.0.1:8090` binding limit exposure to localhost. Acceptable for v1.0 — track as post-release hardening item.

### v1.0 Security Sign-Off

**Status: ✅ APPROVED**

All critical and high-severity findings are resolved. SEC-007 (dashboard auth) is accepted risk for v1.0 — localhost-only binding limits exposure. Recommend tracking as post-release hardening.

**Signed off by**: sec_pentester, Sprint 6 Cycle 14