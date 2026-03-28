# Product Backlog — CloudDeploy

## Product Vision

CloudDeploy makes deploying containerized apps to any cloud as simple as `clouddeploy up`. One CLI, multiple providers, zero complexity. MVP targets AWS ECS with environment management and health checks. Multi-provider and web dashboard follow.

## CRITICAL

### STORY-004: Implement CLI skeleton with Click
**Priority**: CRITICAL
**Assigned**: dev1
**Status**: TODO

**As a** developer **I want** a working CLI entry point with Click **so that** I can run `clouddeploy` commands from the terminal

**Acceptance criteria**:
- [ ] `clouddeploy --help` shows available commands
- [ ] `clouddeploy --version` prints version
- [ ] Command groups: `deploy`, `env`, `status`, `rollback`, `logs`
- [ ] Click app in `src/cli.py` with proper entry point in setup
- [ ] Rich console integration for colored output

### STORY-005: Define core data models and configuration schema
**Priority**: CRITICAL
**Assigned**: dev2
**Status**: TODO

**As a** developer **I want** well-defined data models for deployments, environments, and provider configs **so that** all components share a consistent structure

**Acceptance criteria**:
- [ ] Pydantic or dataclass models for: Deployment, Environment, ProviderConfig, HealthCheck
- [ ] YAML-based config schema in `config/clouddeploy.yaml`
- [ ] Environment definitions: dev, staging, prod with overridable settings
- [ ] SQLite schema for deployment state tracking in `src/db.py`
- [ ] Config loader in `src/config.py`

## HIGH

### STORY-001: Define MVP scope
**Priority**: HIGH
**Status**: DONE

### STORY-006: Implement provider abstraction layer
**Priority**: HIGH
**Assigned**: dev1
**Status**: TODO

**As a** developer **I want** a clean provider interface **so that** adding new cloud providers is straightforward

**Acceptance criteria**:
- [ ] Abstract base class `CloudProvider` in `src/providers/base.py`
- [ ] Methods: `deploy()`, `rollback()`, `status()`, `logs()`, `health_check()`
- [ ] Provider registry for dynamic provider loading
- [ ] AWS ECS stub provider implementing the interface

### STORY-007: Implement AWS ECS provider
**Priority**: HIGH
**Assigned**: dev1
**Status**: TODO

**As a** user **I want** to deploy my containerized app to AWS ECS **so that** I can run production workloads on AWS

**Acceptance criteria**:
- [ ] ECS provider in `src/providers/aws_ecs.py` implementing CloudProvider
- [ ] Create/update ECS service and task definition
- [ ] Support Fargate launch type
- [ ] Environment variable injection from config
- [ ] Uses httpx for AWS API calls (or boto3 if team prefers)

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
**Status**: TODO

**As a** user **I want** deployment history tracked locally **so that** I can see what was deployed, when, and roll back if needed

**Acceptance criteria**:
- [ ] SQLite database at `~/.clouddeploy/state.db`
- [ ] Track: deployment_id, timestamp, environment, image, status, commit_sha
- [ ] `clouddeploy status` shows current deployment per environment
- [ ] `clouddeploy logs` shows deployment history with Rich table output

## MEDIUM

### STORY-002: Set up development environment
**Priority**: MEDIUM
**Assigned**: devops
**Status**: TODO

**As a** developer **I want** a working dev environment with CI/CD basics **so that** the team can develop and test efficiently

**Acceptance criteria**:
- [ ] pyproject.toml with all dependencies (click, httpx, rich, pyyaml, pydantic)
- [ ] Dockerfile for development
- [ ] docker-compose.yml with local testing services
- [ ] Makefile with: install, test, lint, format targets
- [ ] pytest configuration with fixtures
- [ ] Pre-commit hooks for linting

### STORY-010: Health check system
**Priority**: MEDIUM
**Assigned**: dev1
**Status**: TODO

**As a** user **I want** automatic health checks after deployment **so that** I know if my deployment succeeded

**Acceptance criteria**:
- [ ] Configurable health check endpoint (default: `/health`)
- [ ] Polling with timeout and retry logic
- [ ] Auto-rollback option on health check failure
- [ ] Health status in deployment state DB

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
**Status**: TODO

**As a** developer **I want** a test suite for core components **so that** we catch regressions early

**Acceptance criteria**:
- [ ] Tests for config loading
- [ ] Tests for data models
- [ ] Tests for provider abstraction (mock provider)
- [ ] Tests for SQLite state management
- [ ] Minimum 70% coverage on core modules

## DONE

### STORY-001: Define MVP scope
**Priority**: HIGH
**Status**: DONE
