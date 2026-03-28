# Sprint 2 — Core Features

**Goal**: Deliver rollback support and environment management CLI — completing the MVP deployment workflow
**Start**: 2026-03-28 12:32

## TODO

## IN PROGRESS
- [ ] STORY-011: Rollback support (dev1)
- [ ] STORY-008: Environment management (dev2)

## REVIEW

## TESTING

## DONE
- [x] STORY-004: Implement CLI skeleton with Click (dev1)
- [x] STORY-005: Define core data models and configuration schema (dev2)
- [x] STORY-006: Implement provider abstraction layer (dev1)
- [x] STORY-007: Implement AWS ECS provider (dev1)
- [x] STORY-009: Deployment state tracking with SQLite (dev2)
- [x] STORY-010: Health check system (dev1)
- [x] STORY-002: Set up development environment (devops)
- [x] STORY-012: Basic unit test suite (tester)

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
| SEC-018 Docker Resource Limits | CLOSED (fixed C10) | ~~LOW~~ |

### Cycle 12 — Maintenance Audit (Sprint 2 Start, No New Code)

Sprint 2 started with STORY-011 (Rollback support) and STORY-008 (Environment management) in progress. No source modifications delivered yet. Spot-checked existing codebase — all prior remediations intact.

**Standing security approvals (unchanged):**
- **STORY-010** (health.py): APPROVED
- **STORY-009** (db.py): APPROVED
- **STORY-012** (tests): APPROVED
- **STORY-007** (aws_ecs.py): APPROVED

**No new findings.**

### Threat Preview — Sprint 2 Stories

**STORY-011 (Rollback)**: Will need review for:
- State manipulation attacks (rolling back to a compromised deployment)
- Race conditions between concurrent rollback/deploy operations
- Insufficient authorization checks on rollback actions
- Deployment history tampering via SQLite

**STORY-008 (Environment management)**: Will need review for:
- Environment promotion bypass (dev → prod without gates)
- Secret leakage between environments
- Config injection via environment YAML files
- Privilege escalation through environment switching

### Open Items

**SEC-010 (No Auth — Deferred)**: No web endpoints exist yet. Will become actionable when web dashboard enters development. Auth middleware, rate limiting, and CORS must be implemented before any HTTP listener goes live.

### Security Posture: GREEN ✓