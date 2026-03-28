# Sprint 1 — Initialization

**Goal**: Establish project foundation — CLI skeleton, data models, provider abstraction, dev environment
**Start**: 2026-03-28 11:19

## TODO

## IN PROGRESS
- [ ] STORY-002: Set up development environment (devops)
- [ ] STORY-007: Implement AWS ECS provider (dev1)
- [ ] STORY-012: Basic unit test suite (tester)

## REVIEW
- [x] STORY-004: Implement CLI skeleton with Click (dev1)
- [x] STORY-005: Define core data models and configuration schema (dev2)
- [x] STORY-006: Implement provider abstraction layer (dev1)

## DONE
- [x] STORY-001: Define MVP scope (po)
- [x] STORY-003: Create initial project structure (devops)

## BLOCKED

## Security Analysis [Cycle 7]

### Status of Previous Findings

| Finding | Status | Severity |
|---------|--------|----------|
| SEC-001 Redis Exposed | CLOSED (fixed C3) | ~~HIGH~~ |
| SEC-002 Secrets in Config | CLOSED (fixed C2) | ~~MEDIUM~~ |
| SEC-003 Input Validation | CLOSED (fixed C2) | ~~HIGH~~ |
| SEC-006 Port Exposure | CLOSED (fixed C3) | ~~MEDIUM~~ |
| SEC-007 YAML Loading | CLOSED (safe) | ~~INFO~~ |
| SEC-008 SQL Formatting | CLOSED (info) | ~~INFO~~ |
| SEC-009 Healthcheck | VERIFIED FIXED (C5) | ~~LOW~~ |
| SEC-010 No Auth (deferred) | OPEN (deferred) | MEDIUM |
| SEC-011 Missing SigV4 (ECS) | VERIFIED FIXED (C7) | ~~HIGH~~ |
| SEC-012 Error Leakage | VERIFIED FIXED (C4) | ~~MEDIUM~~ |
| SEC-013 Hardcoded Cluster | VERIFIED FIXED (C7) | ~~LOW~~ |
| SEC-014 TLS Config | VERIFIED FIXED (C4) | ~~LOW~~ |
| SEC-015 CloudWatch Unsigned | VERIFIED FIXED (C7) | ~~HIGH~~ |

### Pentest Verification — Cycle 7

**SEC-011 + SEC-015: AWS SigV4 Request Signing — VERIFIED FIXED ✓**

Verified by code review of `src/clouddeploy/providers/aws_ecs.py`:

1. **Signing coverage**: Both `_ecs_request()` (line 359) and `_logs_request()` (line 375) call `_sign_and_merge_headers()` before every HTTP POST. No code path can bypass signing.
2. **Fail-closed**: `_get_aws_credentials()` raises `ValueError` when `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` are missing or empty. No silent fallback to unsigned requests.
3. **Header completeness**: `Authorization`, `X-Amz-Date`, `X-Amz-Content-Sha256` are set on every request. `X-Amz-Security-Token` included when STS credentials are present.
4. **Single code path**: Both ECS and CloudWatch Logs requests share `_sign_and_merge_headers()` → `_sigv4_sign()`. No duplicate signing logic to drift.
5. **Canonical request construction**: Content-Type is included in signed headers, preventing header tampering. Payload hash covers the request body.
6. **Test coverage**: `test_sigv4.py` covers credential loading (success, with token, missing, empty), header generation, credential scope per region/service, fail-closed behavior, and verifies no HTTP call is made when credentials are absent.

**SEC-013: Hardcoded Default Cluster — VERIFIED FIXED ✓**

1. `AwsEcsProvider.__init__()` accepts `cluster` parameter, stores as `self._cluster`.
2. `rollback()` (line 522), `status()` (line 558), `health_check()` (line 595) all use `self._cluster`.
3. `deploy()` correctly reads cluster from `EcsConfig` for per-deployment override — no conflict.
4. Test `test_provider_uses_configured_cluster` confirms cluster propagation to API calls.

### Remaining Open Finding

| Finding | Status | Severity | Notes |
|---------|--------|----------|-------|
| SEC-010 No Auth (deferred) | OPEN | MEDIUM | Deferred to STORY-011 (web dashboard). Acceptable for Sprint 1 CLI-only scope. |

### Summary — Cycle 7 Security Posture

No remaining security blockers for STORY-007. All HIGH-severity findings are now verified fixed. The only open finding (SEC-010) is deferred to a future story and does not affect the current sprint scope.

**STORY-007 security gate: PASSED** — no security objection to moving to REVIEW/DONE.