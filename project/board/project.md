# AgentBoard

## Description
An agent-first project management and board system. Built to replace Jira/Plane for AI agent teams. Core features: REST API for work items (stories/bugs) with status tracking (todo/in_progress/review/testing/done/blocked), priority management (critical/high/medium/low), agent assignment labels. First-class agent inbox messaging (per-agent endpoints, not comment threading). Pages/document storage for architecture docs, standups, decisions. Markdown-native context builder that produces sprint.md and backlog.md format output with enforced context size limits. Cycle/sprint management with assignment. Board state endpoint returning items grouped by status. Human supervision dashboard with htmx UI, audit trail, activity log, WebSocket live updates. Supervision queue where human approves agent output before it applies. Danger detection for destructive changes. Per-agent capability rules. Tech stack: Python 3.10+, FastAPI, SQLite (upgradeable to PostgreSQL), htmx for dashboard, WebSocket for live updates. The API must implement all endpoints needed by the OpenSepia BoardAdapter interface (15 methods) and BoardProvider interface (25+ methods).

## Status
- **Created**: 2026-03-27 22:40
- **Phase**: Initialization
- **Sprint**: 1

## Goals
- [ ] Define product vision and MVP
- [ ] Create initial architecture
- [ ] Set up development environment
- [ ] Implement first feature
