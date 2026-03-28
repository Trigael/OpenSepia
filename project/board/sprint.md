# Sprint 5 — v1.0 Hardening

**Goal**: Dry-run mode, secrets management, and integration tests to harden CloudDeploy for v1.0 readiness
**Start**: 2026-03-28 13:37

## TODO

## IN PROGRESS

## REVIEW

## TESTING

## DONE
- [x] STORY-017: Deployment dry-run mode (dev2) — `--dry-run` flag validates config and prints planned actions without API calls. All ACs met.
- [x] STORY-018: Secrets management integration (dev1) — Fernet-encrypted secrets in SQLite, CLI CRUD commands, injected at deploy time. All ACs met.
- [x] STORY-019: Integration test suite (tester) — 40 integration tests covering deploy lifecycle (AWS/GCP/Azure), promote workflow, rollback state verification, and secrets workflows. All ACs met.

## BLOCKED

## Security Findings

### SEC-023: Stored XSS in dashboard templates
**Severity**: HIGH
**Category**: A7 — Cross-Site Scripting (XSS)
**File**: workspace/src/clouddeploy/dashboard/templates.py:143-153, 170-179
**Status**: OPEN — FIX NOT APPLIED TO WORKSPACE (verified cycle 7)
**Description**: Workspace `templates.py` has zero HTML escaping. No `html.escape` import, no `_esc()` calls. All dynamic fields (`id`, `image`, `version`, `message`, `commit_sha`, `app`, `endpoint`, `status`) are interpolated raw into HTML via f-strings. Additionally, `_status_badge()` (line 24) and `_health_badge()` (line 30) render labels without escaping.
**PoC**: Deploy with `id` = `<img src=x onerror=alert(document.cookie)>` → JavaScript executes when any user views the dashboard.
**Impact**: Stored XSS — attacker-controlled deployment metadata executes arbitrary JavaScript in all dashboard viewers' browsers. Can steal session data, redirect users, or deface the dashboard.
**Remediation**: Import `from html import escape as _esc` and wrap every dynamic field in `_esc()` before interpolation into HTML.

### SEC-024: SSE endpoint has no connection limit
**Severity**: MEDIUM
**Category**: A5 — Security Misconfiguration / Resource Exhaustion
**File**: workspace/src/clouddeploy/dashboard/app.py:138-156
**Status**: OPEN — FIX NOT APPLIED TO WORKSPACE (verified cycle 7)
**Description**: Workspace `app.py` has no `MAX_SSE_CONNECTIONS` constant, no asyncio lock, no connection counter, and no 503 response. The SSE endpoint at line 148 returns `StreamingResponse` with an infinite generator (`_event_generator`) and no concurrency guard. Each SSE client opens a new `DeployDB` connection every 3 seconds (lines 223-229), amplifying the resource cost per connection.
**PoC**: `for i in $(seq 1 1000); do curl -s -N http://localhost:8080/api/events & done` — opens 1000 persistent connections, each polling SQLite every 3 seconds.
**Impact**: Resource exhaustion DoS — unbounded SSE connections consume memory, file descriptors, and database connections.
**Remediation**: Add `MAX_SSE_CONNECTIONS = 50` constant, asyncio lock-guarded counter, 503 response when limit reached, and try/finally decrement on disconnect.

### SEC-025: Secret value exposed in shell history via CLI argument
**Severity**: MEDIUM
**Category**: A3 — Sensitive Data Exposure
**File**: workspace/src/clouddeploy/cli.py:611-624
**Status**: OPEN — FIX NOT APPLIED TO WORKSPACE (verified cycle 7)
**Description**: `secrets set` command at line 614 declares `value` as a mandatory positional argument via `@click.argument("value")`. The secure-input fix (optional value with stdin/prompt fallback) was never applied to the workspace copy.
**PoC**: `clouddeploy secrets set prod DB_PASSWORD hunter2` → visible in `ps aux`, shell history (`~/.bash_history`), and process audit logs.
**Impact**: Sensitive secrets exposed in shell history, process listings, and audit logs.
**Remediation**: Make `value` optional (`required=False`). When omitted: read from stdin if piped, else use `click.prompt(hide_input=True)`.

### SEC-026: Dashboard serves without authentication
**Severity**: LOW
**Category**: A2 — Broken Authentication
**File**: workspace/src/clouddeploy/dashboard/app.py:28-158
**Status**: OPEN — INFO
**Description**: No authentication or authorization on any dashboard endpoint. Localhost-only binding limits exposure.
**Impact**: Information disclosure of deployment metadata to unauthorized local users. Low severity because localhost-only and no secrets exposed.
**Recommendation**: Acceptable for v1.0 if documented. For multi-user environments, add bearer token or basic auth middleware.

### SEC-027: Azure API error responses logged at debug level
**Severity**: INFO
**Category**: A3 — Sensitive Data Exposure
**File**: workspace/src/clouddeploy/providers/azure_container_apps.py:393-397, 467-471
**Status**: OPEN — INFO
**Description**: `logger.debug` logs full `exc.response.text` from Azure API errors, which can contain subscription IDs, resource group names, and occasionally token fragments.
**Impact**: Minimal — requires debug-level logging enabled and log file access.
**Recommendation**: Sanitize or truncate error response bodies before logging.

### SEC-028: Fix drift — workspace diverged from src, claimed fixes not present
**Severity**: HIGH
**Category**: Process / Configuration Management
**Status**: OPEN (verified cycle 7 — still diverged)
**Description**: Three security findings (SEC-023, SEC-024, SEC-025) were reported FIXED by sec_engineer in cycle 5, but verification shows: (1) workspace `templates.py` has no `html.escape` import or `_esc()` calls, (2) workspace `app.py` has no `MAX_SSE_CONNECTIONS` or connection guard, (3) workspace `cli.py:614` still has mandatory `@click.argument("value")`, (4) claimed test files `test_xss_escaping.py` and `test_secrets_prompt.py` do not exist in the workspace `tests/` directory.
**Impact**: False sense of security. Sprint board reports resolved vulnerabilities that remain exploitable in the deliverable code. v1.0 cannot ship with these open.
**Remediation**: sec_engineer must apply fixes directly to `workspace/src/clouddeploy/` files and add test files under `workspace/tests/`. Verify by reading the workspace files after patching.

### Closed Findings (verified this cycle)
- **SEC-019**: CLOSED — `_mask_sensitive()` correctly masks keys matching `*KEY*`, `*SECRET*`, `*PASSWORD*`, `*TOKEN*`, `*CREDENTIAL*` patterns.
- **SEC-020**: CLOSED — Rollback rejects targets with `status != succeeded`.
- **SEC-021**: CLOSED — `latest_deployment()` cached before confirm prompt, eliminating TOCTOU race.

### Verified Secure Areas
- **SQL injection**: All queries use parameterized `?` placeholders — no injection vectors found in `db.py` or `secrets.py`.
- **Path traversal**: `_validate_db_path()` in `config.py` properly rejects absolute paths and `..` components.
- **Secrets encryption**: Fernet with auto-generated key, file permissions `0o600` — solid.
- **Input validation**: `validation.py` enforces strict regex on app names, environments, and providers.
- **Credential handling**: All three cloud providers read creds from env vars and fail-closed if missing.
- **Production safety**: Rollback and promote to prod require explicit `--yes` or interactive confirmation.
- **Sensitive masking**: CLI output masks env var values matching sensitive key patterns.