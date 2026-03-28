# Product Backlog — CloudDeploy

## Product Vision

CloudDeploy makes deploying containerized apps to any cloud as simple as `clouddeploy up`. One CLI, multiple providers, zero complexity. MVP targets AWS ECS with environment management and health checks. Multi-provider and web dashboard follow.

## CRITICAL

### STORY-004: Implement CLI skeleton with Click
**Priority**: CRITICAL
**Assigned**: dev1
**Status**: DONE

**As a** developer **I want** a working CLI entry point with Click **so that** I can run `clouddeploy` commands from the terminal

**Acceptance criteria**:
- [x] `clouddeploy --help` shows available commands
- [x] `clouddeploy --version` prints version
- [x] Command groups: `deploy`, `env`, `status`, `rollback`, `logs`
- [x] Click app in `src/cli.py` with proper entry point in setup
- [x] Rich console integration for colored output

### STORY-005: Define core data models and configuration schema
**Priority**: CRITICAL
**Assigned**: dev2
**Status**: DONE

**As a** developer **I want** well-defined data models for deployments, environments, and provider configs **so that** all components share a consistent structure

**Acceptance criteria**:
- [x] Pydantic or dataclass models for: Deployment, Environment, ProviderConfig, HealthCheck
- [x] YAML-based config schema in `config/clouddeploy.yaml`
- [x] Environment definitions: dev, staging, prod with overridable settings
- [x] SQLite schema for deployment state tracking in `src/db.py`
- [x] Config loader in `src/config.py`

## HIGH

### STORY-001: Define MVP scope
**Priority**: HIGH
**Status**: DONE

### STORY-006: Implement provider abstraction layer
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

**As a** developer **I want** a clean provider interface **so that** adding new cloud providers is straightforward

**Acceptance criteria**:
- [x] Abstract base class `CloudProvider` in `src/providers/base.py`
- [x] Methods: `deploy()`, `rollback()`, `status()`, `logs()`, `health_check()`
- [x] Provider registry for dynamic provider loading
- [x] AWS ECS stub provider implementing the interface

### STORY-007: Implement AWS ECS provider
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

**As a** user **I want** to deploy my containerized app to AWS ECS **so that** I can run production workloads on AWS

**Acceptance criteria**:
- [x] ECS provider in `src/providers/aws_ecs.py` implementing CloudProvider
- [x] Create/update ECS service and task definition
- [x] Support Fargate launch type
- [x] Environment variable injection from config
- [x] Uses httpx for AWS API calls (or boto3 if team prefers)

### STORY-008: Environment management (dev/staging/prod)
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

**As a** user **I want** to manage multiple deployment environments **so that** I can promote builds from dev → staging → prod

**Acceptance criteria**:
- [x] `clouddeploy env list` shows configured environments
- [x] `clouddeploy env show <name>` shows environment details
- [x] `clouddeploy env create <name>` creates new environment config
- [x] Each environment has: provider, region, replicas, env vars, resource limits
- [x] Environment configs stored in `config/environments/`

### STORY-009: Deployment state tracking with SQLite
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

**As a** user **I want** deployment history tracked locally **so that** I can see what was deployed, when, and roll back if needed

**Acceptance criteria**:
- [x] SQLite database at `~/.clouddeploy/state.db`
- [x] Track: deployment_id, timestamp, environment, image, status, commit_sha
- [x] `clouddeploy status` shows current deployment per environment
- [x] `clouddeploy logs` shows deployment history with Rich table output

### STORY-021: v1.0 release checklist
**Priority**: HIGH
**Assigned**: devops
**Status**: IN_PROGRESS

**As a** maintainer **I want** a complete release checklist executed **so that** v1.0 is tagged, documented, and ready to distribute

**Acceptance criteria**:
- [x] Version bumped to 1.0.0 in `pyproject.toml` and `__init__.py`
- [x] CHANGELOG.md created with all features from Sprints 1-6
- [x] README.md with quickstart guide, installation, and usage examples
- [ ] All tests pass (`pytest tests/ -v` and `pytest tests/integration/ -v`)
- [x] Dockerfile builds and runs successfully
- [ ] Git tag `v1.0.0` ready (do not push)

## MEDIUM

### STORY-002: Set up development environment
**Priority**: MEDIUM
**Assigned**: devops
**Status**: IN_PROGRESS

**As a** developer **I want** a working dev environment with CI/CD basics **so that** the team can develop and test efficiently

**Acceptance criteria**:
- [x] pyproject.toml with all dependencies (click, httpx, rich, pyyaml, pydantic)
- [x] Dockerfile for development
- [x] docker-compose.yml with local testing services
- [x] Makefile with: install, test, lint, format targets
- [x] pytest configuration with fixtures
- [x] Pre-commit hooks for linting

### STORY-010: Health check system
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

**As a** user **I want** automatic health checks after deployment **so that** I know if my deployment succeeded

**Acceptance criteria**:
- [x] Configurable health check endpoint (default: `/health`)
- [x] Polling with timeout and retry logic
- [x] Auto-rollback option on health check failure
- [x] Health status in deployment state DB

### STORY-011: Rollback support
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

**As a** user **I want** to rollback to a previous deployment **so that** I can recover from bad deploys quickly

**Acceptance criteria**:
- [x] `clouddeploy rollback <env>` rolls back to previous deployment
- [x] `clouddeploy rollback <env> --to <deployment_id>` targets specific version
- [x] Rollback creates a new deployment record (not delete)
- [x] Confirmation prompt before rollback to prod

### STORY-014: Web dashboard — deployment overview
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

**As a** user **I want** a web dashboard **so that** I can monitor deployments visually

**Acceptance criteria**:
- [x] Local web server (Flask or FastAPI)
- [x] Dashboard showing deployment history per environment
- [x] Real-time status updates
- [x] Health check visualization

### STORY-015: Azure Container Apps provider
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: DONE

**As a** user **I want** to deploy to Azure Container Apps **so that** I can use Azure infrastructure

**Acceptance criteria**:
- [x] Azure provider in `src/providers/azure_container_apps.py`
- [x] Container app creation and update
- [x] Revision management
- [x] Ingress configuration

### STORY-017: Deployment dry-run mode
**Priority**: MEDIUM
**Assigned**: dev2
**Status**: DONE

**As a** user **I want** `clouddeploy deploy --dry-run` **so that** I can preview what a deployment would do without actually executing it

**Acceptance criteria**:
- [x] `--dry-run` flag on `clouddeploy deploy` command
- [x] Dry-run validates config, resolves provider, and prints planned actions
- [x] No API calls made to cloud providers during dry-run
- [x] Output shows: image to deploy, target environment, provider config, and estimated changes

### STORY-018: Secrets management integration
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: DONE

**As a** user **I want** to manage deployment secrets securely **so that** sensitive values are not stored in plaintext config files

**Acceptance criteria**:
- [x] `clouddeploy secrets set <env> <key> <value>` stores encrypted secrets
- [x] `clouddeploy secrets list <env>` shows secret keys (not values)
- [x] Secrets injected into deployments as environment variables
- [x] Secrets stored encrypted in local SQLite (using Fernet symmetric encryption)
- [x] `clouddeploy secrets delete <env> <key>` removes a secret

### STORY-019: Integration test suite
**Priority**: MEDIUM
**Assigned**: tester
**Status**: DONE

**As a** developer **I want** integration tests that exercise full deploy workflows **so that** we catch end-to-end regressions before release

**Acceptance criteria**:
- [x] Integration test fixtures with mock cloud provider responses
- [x] Test full deploy → health check → status flow per provider (AWS, GCP, Azure)
- [x] Test promote workflow: dev → staging → prod
- [x] Test rollback workflow with deployment state verification
- [x] Tests run with `pytest tests/integration/ -v`

## LOW

### STORY-012: Basic unit test suite
**Priority**: LOW
**Assigned**: tester
**Status**: DONE

**As a** developer **I want** a test suite for core components **so that** we catch regressions early

**Acceptance criteria**:
- [x] Tests for config loading
- [x] Tests for data models
- [x] Tests for provider abstraction (mock provider)
- [x] Tests for SQLite state management
- [x] Minimum 70% coverage on core modules

### STORY-020: CLI help and documentation improvements
**Priority**: LOW
**Assigned**: dev1
**Status**: DONE

**As a** user **I want** clear `--help` text and usage examples on every command **so that** I can use CloudDeploy without reading external docs

**Acceptance criteria**:
- [x] Every Click command and subcommand has a descriptive help string
- [x] `clouddeploy deploy --help` shows usage examples
- [x] `clouddeploy --help` shows grouped commands with descriptions
- [x] Add `examples` callback or `--examples` flag showing common workflows

## DONE

### STORY-001: Define MVP scope
**Priority**: HIGH
**Status**: DONE

### STORY-013: GCP Cloud Run provider
**Priority**: HIGH
**Assigned**: dev2
**Status**: DONE

**As a** user **I want** to deploy to GCP Cloud Run **so that** I have multi-cloud options

**Acceptance criteria**:
- [x] Cloud Run provider in `src/providers/gcp_cloudrun.py`
- [x] Service creation and update
- [x] Traffic splitting support
- [x] Region configuration

### STORY-016: Deployment promotion workflow
**Priority**: HIGH
**Assigned**: dev1
**Status**: DONE

**As a** user **I want** `clouddeploy promote <env>` **so that** I can promote a deployment from dev → staging → prod in sequence

**Acceptance criteria**:
- [x] `clouddeploy promote <env>` promotes latest successful deployment to next tier
- [x] Promotion chain: dev → staging → prod
- [x] Confirmation prompt for prod promotion
- [x] Promotion recorded in deployment history
### STORY-022: [Alert] Agent failure: DevOps Engineer, QA Engineer (2026-03-28 17:29)
**Priority**: MEDIUM
**Status**: TODO

## Agent Failure Alert

**Time**: 2026-03-28T17:29:32.302709
**Mode**: dev-team
**Failed**: DevOps Engineer, QA Engineer

Check logs in `logs/runs/` for details.

---
*Automatic alert from the AI Dev Team orchestrator.*

