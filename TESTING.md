# Testing

## Run tests

```bash
python3 -m pytest tests/ -v
```

142 tests, no external API calls. All provider interactions are mocked.

## Test coverage

| Module | Tests | What's tested |
|--------|-------|---------------|
| `test_agent_parser.py` | 12 | ---FILES--- parsing, standup fallback, edge cases |
| `test_pipeline.py` | 8 | Step execution, critical/non-critical errors, context flow |
| `test_orchestrator_config.py` | 19 | Config loading, mode resolution, aliases, execution params |
| `test_daemon_state.py` | 12 | State serialization, PID checks, atomic writes |
| `test_sync_board.py` | 18 | Backlog parsing, status normalization, sprint parsing |
| `test_sync_comments.py` | 30 | Story refs, MR refs, reviews, approvals, active story IDs |
| `test_restore_board.py` | 7 | Board health check, missing/empty file detection |
| `test_base.py` | 14 | Labels, agent display, comment formatting |
| `test_config.py` | 14 | Git config, Docker config, env vars |
| `test_providers.py` | 6 | Provider auto-detection (GitLab vs GitHub) |

## Rate limits for live testing

| Plan | Messages/5h | Recommended cycles/day | Agents per cycle |
|------|-------------|----------------------|-----------------|
| **Pro** ($20/mo) | ~45 | 3-4 | 3 (minimal) |
| **Max** ($100/mo) | ~225 | 15-20 | 6-9 (full team) |

## Quick live test

```bash
# Dry run — shows what would be sent to Claude, without calling it
opensepia run po --dry-run

# Single agent — cheapest real test (1 Claude call)
opensepia run po

# Minimal team — 3 agents
opensepia run minimal
```
