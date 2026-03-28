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

## Security Analysis [cycle 10]

### Summary

Final v1.0 release security review. All code reviewed — no new vulnerabilities found since cycle 9. Security posture confirmed stable.

**Resolved findings (confirmed fixed):**
- SEC-004 (db_path traversal) — `_validate_db_path()` in `config.py:140` rejects absolute paths and `..` traversal. ✅
- SEC-020 (rollback to non-succeeded) — `cli.py:490` enforces `status == SUCCEEDED` check. ✅
- SEC-021 (TOCTOU on rollback) — `cli.py:505` caches `latest_deployment` before confirm prompt. ✅

**Security posture (unchanged from cycle 9):**
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

### Open Findings (acceptable for v1.0)

### SEC-007: Dashboard has no authentication or authorization
**Severity**: MEDIUM
**Category**: Broken Access Control (OWASP A01)
**File**: src/clouddeploy/dashboard/app.py:32-176
**Description**: All dashboard endpoints are publicly accessible with zero authentication.
**Impact**: Information disclosure to anyone who can reach the server.
**Mitigation**: Default `--host 127.0.0.1` and docker-compose `127.0.0.1:8090` binding limit exposure to localhost. Acceptable for v1.0 — track as post-release hardening item.

### SEC-008: Redis password exposed in process listing
**Severity**: LOW
**Category**: Sensitive Data Exposure (OWASP A02)
**File**: docker-compose.yml:242
**Description**: `redis-cli -a ${REDIS_PASSWORD} ping` leaks password via `/proc/*/cmdline`.
**Recommendation**: Use `REDISCLI_AUTH` env var instead: `test: ["CMD-SHELL", "REDISCLI_AUTH=$REDIS_PASSWORD redis-cli ping"]`

### v1.0 Security Sign-Off

**Pentester assessment**: The codebase is **ready for v1.0 release** from a security standpoint.

All critical and high-severity findings from previous cycles have been resolved and verified. The two remaining open findings (SEC-007 localhost-only dashboard, SEC-008 Redis password in process list) are low-risk with existing mitigations and acceptable for a v1.0 release targeting local/developer use.

Key strengths: parameterized SQL, strict input validation, Fernet encryption at rest, hardened containers, HTML escaping, TLS enforcement.

Recommended post-v1.0 hardening (tracked in backlog):
- Dashboard authentication (SEC-007)
- Redis healthcheck using REDISCLI_AUTH env var (SEC-008)
- Encryption key rotation mechanism
- Increase deployment ID entropy from 32-bit to 64-bit