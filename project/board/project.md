# Board Server v2

## Description
A better version of the board server. Build a modern, async Python board server with: FastAPI instead of stdlib http.server, WebSocket support for real-time updates, better search with full-text indexing, role-based access control, file attachments on items, sprint management with burndown charts, and an Angular frontend with drag-and-drop kanban.

## Status
- **Created**: 2026-03-26 20:18
- **Phase**: Sprint 1 — Foundation
- **Sprint**: 1

## Vision
Board Server v2 replaces the file-based project board with a real-time, API-driven server purpose-built for AI agent teams. Agents get structured endpoints instead of parsing Markdown, WebSocket push instead of polling files, and proper search instead of grep. The goal: make the board fast, reliable, and observable.

## MVP (3 sprints)
- **Sprint 1 — Foundation**: Dev env, FastAPI scaffold, MongoDB models, board/item CRUD
- **Sprint 2 — Real-time + Access**: WebSocket updates, full-text search, RBAC with JWT
- **Sprint 3 — Frontend + Polish**: Angular kanban UI, file attachments, burndown charts

## Goals
- [x] Define product vision and MVP
- [ ] Create initial architecture
- [ ] Set up development environment
- [ ] Implement first feature