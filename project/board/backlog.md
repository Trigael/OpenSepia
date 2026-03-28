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
**Status**: TODO

**As a** user **I want** to manage multiple deployment environments **so that** I can promote builds from dev → staging → prod

**Acceptance criteria**:
- [ ] `clouddeploy env list` shows configured environments
- [ ] `clouddeploy env show <name>` shows environment details
- [ ] `clouddeploy env create <name>` creates new environment config
- [ ] Each environment has: provider, region, replicas, env vars, resource limits
- [ ] Environment configs stored in `config/environments/`

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

## MEDIUM

### STORY-002: Set up development environment
**Priority**: MEDIUM
**Assigned**: devops
**Status**: DONE

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
**Assigned**: dev2
**Status**: TODO

**As a** user **I want** to rollback to a previous deployment **so that** I can recover from bad deploys quickly

**Acceptance criteria**:
- [ ] `clouddeploy rollback <env>` rolls back to previous deployment
- [ ] `clouddeploy rollback <env> --to <deployment_id>` targets specific version
- [ ] Rollback creates a new deployment record (not delete)
- [ ] Confirmation prompt before rollback to prod

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

## DONE

### STORY-001: Define MVP scope
**Priority**: HIGH
**Status**: DONE