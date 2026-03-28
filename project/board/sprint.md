# Sprint 2 — Core Features

**Goal**: Deliver rollback support and environment management CLI — completing the MVP deployment workflow
**Start**: 2026-03-28 12:32

## TODO

## IN PROGRESS

## REVIEW
- [x] STORY-008: Environment management (dev2)
- [x] STORY-011: Rollback support (dev1)

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

## Security Analysis [Cycle 2 — Sprint 2]

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
| SEC-019 Env Var Display | CLOSED (fixed C2S2) | ~~INFO~~ |
| SEC-020 Rollback to Failed Deploy | CLOSED (fixed C2S2) | ~~LOW~~ |
| SEC-021 Rollback TOCTOU Metadata | CLOSED (fixed C2S2) | ~~INFO~~ |
| SEC-022 Env Create No Instance Bounds | NEW | ~~INFO~~ |

### Cycle 2 Review Notes (Pentest Pass 2)

**Full Re-Verification**: All prior remediations confirmed intact:
- `yaml.safe_load` — verified in config.py:123, environments.py:49
- Parameterized SQL — all db.py queries use `?` placeholders, zero string formatting
- `validate_identifier()` — present at all CLI entry points (deploy run, rollback run, env show, env create, status show, health check, logs show/history)
- `validate_environment()` — enforces whitelist `{dev, staging, prod}` at all env-accepting commands
- `validate_provider()` — enforces whitelist `{aws-ecs, gcp-cloudrun, azure-container-apps}`
- SigV4 signing — verified on ECS and CloudWatch Logs requests
- Error messages — no stack traces or internal details leaked
- Docker: resource limits, read-only fs, non-root user, localhost-only ports
- `_mask_sensitive()` applied to `env show` variable output (SEC-019)
- Rollback rejects non-SUCCEEDED targets (SEC-020)
- TOCTOU mitigated by caching `latest_deployment()` before confirm prompt (SEC-021)

**STORY-008 Pentest (environments.py, cli.py env commands)**:
- Path traversal via env name: BLOCKED — `validate_identifier()` rejects `../`, special chars
- YAML deserialization: SAFE — uses `yaml.safe_load` (no arbitrary code execution)
- Env file overwrite: SAFE — `create_environment` checks `file_path.exists()` before write
- Sensitive vars in `env show`: SAFE — `_mask_sensitive()` masks `*KEY*`, `*SECRET*`, `*PASSWORD*`, `*TOKEN*`, `*CREDENTIAL*` patterns
- Variable injection via `-v` flag: SAFE — stored as plain dict, no shell expansion or eval

**STORY-011 Pentest (rollback CLI)**:
- Rollback to foreign app/env: BLOCKED — explicit `target.app != app` and `target.environment != env` checks (cli.py:345-351)
- Rollback to failed deployment: BLOCKED — `target.status != SUCCEEDED` guard (cli.py:353-359)
- TOCTOU on `rollback_from` metadata: FIXED — `latest_deployment()` cached at cli.py:368 before confirm prompt
- Deployment ID injection: BLOCKED — `validate_identifier(target_id)` at cli.py:334
- Prod rollback without confirmation: BLOCKED — prompt enforced unless `--yes` flag (cli.py:371-379)

### PENTEST-022: Environment Create — No Instance Count Bounds Check
**Severity**: INFO
**CVSS**: 2.0
**Attack vector**: `clouddeploy env create foo --min-instances -1 --max-instances 999999` — Click accepts any integer, no upper/lower bound validation. Could cause unexpected behavior when passed to cloud provider APIs.
**PoC**: `clouddeploy env create broken --min-instances 0 --max-instances 1000000`
**Impact**: Misconfiguration risk — provider API may reject or (worse) accept absurd instance counts, leading to cost runaway or service failure. Low practical risk since provider APIs have their own limits.
**Remediation**: Add bounds validation: `min_instances >= 1`, `max_instances <= 100` (or configurable cap). Not blocking — deferred as INFO.

### Standing Security Approvals

- **STORY-004** (cli.py skeleton): APPROVED
- **STORY-005** (models/config): APPROVED
- **STORY-006** (provider abstraction): APPROVED
- **STORY-007** (aws_ecs.py): APPROVED
- **STORY-008** (environments.py): **APPROVED** ✓
- **STORY-009** (db.py): APPROVED
- **STORY-010** (health.py): APPROVED
- **STORY-011** (rollback): **APPROVED** ✓
- **STORY-012** (tests): APPROVED

### Security Posture: GREEN ✓