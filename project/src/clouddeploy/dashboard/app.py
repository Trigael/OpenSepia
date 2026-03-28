"""FastAPI application for the CloudDeploy web dashboard.

Serves a deployment overview with per-environment history, health check
visualization, and real-time status updates via Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from clouddeploy.db import DeployDB
from clouddeploy.dashboard.templates import render_index

logger = logging.getLogger(__name__)

ENVIRONMENTS = ("dev", "staging", "prod")
SSE_POLL_INTERVAL = 3  # seconds between DB polls for SSE clients
MAX_SSE_CONNECTIONS = 50  # hard cap on concurrent SSE clients


def create_app(db_path: str | Path | None = None) -> FastAPI:
    """Create and configure the dashboard FastAPI application.

    Args:
        db_path: Path to the SQLite state database. Defaults to
                 ``~/.clouddeploy/state.db``.
    """
    if db_path is None:
        db_path = Path.home() / ".clouddeploy" / "state.db"
    db_path = Path(db_path)

    app = FastAPI(title="CloudDeploy Dashboard", version="0.1.0")

    # SSE connection tracking
    _sse_connection_count = 0
    _sse_lock = asyncio.Lock()

    def _get_db() -> DeployDB:
        return DeployDB(db_path)

    # ------------------------------------------------------------------
    # HTML page
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index(
        app_name: str | None = Query(None, alias="app"),
        environment: str | None = Query(None, alias="env"),
        limit: int = Query(50, ge=1, le=500),
    ) -> HTMLResponse:
        """Serve the main dashboard page."""
        db = _get_db()
        try:
            deployments_raw = db.list_deployments(app=app_name, environment=environment, limit=limit)
            health_raw = db.get_health_checks(app=app_name, environment=environment, limit=limit)

            deployments = [_deployment_dict(d) for d in deployments_raw]
            health_checks = [_health_dict(h) for h in health_raw]

            # Discover which environments have data
            envs_with_data = sorted(
                {d["environment"] for d in deployments}
            )
            # Ensure standard environments appear in order
            env_order = [e for e in ENVIRONMENTS if e in envs_with_data]
            # Append any non-standard environments
            for e in envs_with_data:
                if e not in env_order:
                    env_order.append(e)

            summary = _compute_summary(deployments)

            html = render_index(
                deployments=deployments,
                health_checks=health_checks,
                environments=env_order,
                summary=summary,
            )
            return HTMLResponse(content=html)
        finally:
            db.close()

    # ------------------------------------------------------------------
    # JSON API
    # ------------------------------------------------------------------

    @app.get("/api/deployments")
    async def api_deployments(
        app_name: str | None = Query(None, alias="app"),
        environment: str | None = Query(None, alias="env"),
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict]:
        """Return deployment records as JSON."""
        db = _get_db()
        try:
            rows = db.list_deployments(app=app_name, environment=environment, limit=limit)
            return [_deployment_dict(d) for d in rows]
        finally:
            db.close()

    @app.get("/api/health-checks")
    async def api_health_checks(
        app_name: str | None = Query(None, alias="app"),
        environment: str | None = Query(None, alias="env"),
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict]:
        """Return health check records as JSON."""
        db = _get_db()
        try:
            rows = db.get_health_checks(
                app=app_name, environment=environment, limit=limit
            )
            return [_health_dict(h) for h in rows]
        finally:
            db.close()

    @app.get("/api/summary")
    async def api_summary(
        app_name: str | None = Query(None, alias="app"),
        environment: str | None = Query(None, alias="env"),
    ) -> dict:
        """Return deployment summary statistics."""
        db = _get_db()
        try:
            rows = db.list_deployments(app=app_name, environment=environment, limit=500)
            deployments = [_deployment_dict(d) for d in rows]
            return _compute_summary(deployments)
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Server-Sent Events for real-time updates
    # ------------------------------------------------------------------

    @app.get("/api/events")
    async def sse_events(
        app_name: str | None = Query(None, alias="app"),
    ) -> StreamingResponse | JSONResponse:
        """Stream deployment updates via Server-Sent Events.

        The endpoint polls the database at a fixed interval and sends
        a ``refresh`` event whenever the deployment count changes,
        prompting the browser to reload the dashboard.

        Returns HTTP 503 when the maximum number of concurrent SSE
        connections has been reached.
        """
        nonlocal _sse_connection_count

        async with _sse_lock:
            if _sse_connection_count >= MAX_SSE_CONNECTIONS:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Too many SSE connections. Try again later."},
                )
            _sse_connection_count += 1

        async def _guarded_generator() -> AsyncGenerator[str, None]:
            nonlocal _sse_connection_count
            try:
                async for event in _event_generator(db_path, app_name):
                    yield event
            finally:
                async with _sse_lock:
                    _sse_connection_count -= 1

        return StreamingResponse(
            _guarded_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _deployment_dict(dep) -> dict:
    """Convert a Deployment model to a plain dict for templates/JSON."""
    return {
        "id": dep.id,
        "app": dep.app,
        "environment": dep.environment,
        "provider": dep.provider,
        "image": dep.image,
        "version": dep.version,
        "commit_sha": dep.commit_sha,
        "status": dep.status.value,
        "message": dep.message,
        "details": dep.details,
        "created_at": dep.created_at,
        "finished_at": dep.finished_at,
    }


def _health_dict(hc) -> dict:
    """Convert a HealthCheckRecord model to a plain dict."""
    return {
        "id": hc.id,
        "app": hc.app,
        "environment": hc.environment,
        "deployment_id": hc.deployment_id,
        "healthy": hc.healthy,
        "endpoint": hc.endpoint,
        "attempts": hc.attempts,
        "elapsed_seconds": hc.elapsed_seconds,
        "should_rollback": hc.should_rollback,
        "message": hc.message,
        "details": hc.details,
        "checked_at": hc.checked_at,
    }


def _compute_summary(deployments: list[dict]) -> dict:
    """Compute aggregate stats from a list of deployment dicts."""
    total = len(deployments)
    succeeded = sum(1 for d in deployments if d["status"] == "succeeded")
    failed = sum(1 for d in deployments if d["status"] == "failed")
    running = sum(1 for d in deployments if d["status"] == "running")
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "running": running,
    }


async def _event_generator(
    db_path: Path, app_name: str | None
) -> AsyncGenerator[str, None]:
    """Poll the database and yield SSE events when data changes."""
    last_count = -1
    while True:
        try:
            db = DeployDB(db_path)
            try:
                rows = db.list_deployments(app=app_name, limit=1)
                # Use the latest deployment's finished_at as a change indicator
                current = len(db.list_deployments(app=app_name, limit=500))
            finally:
                db.close()

            if last_count == -1:
                last_count = current
            elif current != last_count:
                last_count = current
                yield f"data: {json.dumps({'type': 'refresh'})}\n\n"
            else:
                # Send a keep-alive comment to prevent connection timeout
                yield ": keep-alive\n\n"
        except Exception:
            logger.debug("SSE poll error", exc_info=True)
            yield ": error\n\n"

        await asyncio.sleep(SSE_POLL_INTERVAL)