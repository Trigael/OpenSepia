"""
Mock Plane.so API server for testing.

Lightweight HTTP server that simulates Plane.so REST API v1.
In-memory storage for work items, states, cycles, pages, comments, labels.
Pre-seeded with test data matching OpenSepia conventions.
"""

import json
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any


def _uuid() -> str:
    return str(uuid.uuid4())


class PlaneStore:
    """In-memory storage for mock Plane.so data."""

    def __init__(self) -> None:
        self.states: list[dict] = []
        self.labels: list[dict] = []
        self.work_items: list[dict] = []
        self.cycles: list[dict] = []
        self.pages: list[dict] = []
        self.comments: dict[str, list[dict]] = {}  # work_item_id -> comments
        self.cycle_issues: dict[str, list[str]] = {}  # cycle_id -> [work_item_ids]
        self.workspaces: list[dict] = [
            {"id": _uuid(), "name": "Test Workspace", "slug": "test-ws"},
        ]
        self.projects: list[dict] = [
            {"id": "test-proj", "name": "Test Project", "description": "A test project"},
        ]
        self.seed()

    def seed(self) -> None:
        """Pre-seed with standard test data."""
        # States
        self.states = [
            {"id": _uuid(), "name": "Todo", "group": "unstarted", "color": "#ccc"},
            {"id": _uuid(), "name": "In Progress", "group": "started", "color": "#ffa"},
            {"id": _uuid(), "name": "Review", "group": "started", "color": "#aaf"},
            {"id": _uuid(), "name": "Testing", "group": "started", "color": "#afa"},
            {"id": _uuid(), "name": "Done", "group": "completed", "color": "#afa"},
            {"id": _uuid(), "name": "Blocked", "group": "started", "color": "#faa"},
        ]

        state_map = {s["name"]: s["id"] for s in self.states}

        # Labels
        for lbl_name in [
            "agent::po", "agent::pm", "agent::dev1", "agent::dev2",
            "agent::devops", "agent::tester",
            "type::story", "type::bug",
            "status::todo", "status::in-progress", "status::review",
            "status::testing", "status::done", "status::blocked",
            "priority::critical", "priority::high", "priority::medium", "priority::low",
        ]:
            self.labels.append({"id": _uuid(), "name": lbl_name, "color": "#6B7280"})

        label_map = {l["name"]: l["id"] for l in self.labels}

        # Work items
        self.work_items = [
            {
                "id": _uuid(), "name": "[STORY-001] User login page",
                "state_id": state_map["Todo"], "priority": 2,
                "label_ids": [label_map.get("agent::dev1", ""), label_map.get("type::story", "")],
                "label_detail": [{"name": "agent::dev1"}, {"name": "type::story"}],
                "description_html": "<p>Create a login page</p>",
            },
            {
                "id": _uuid(), "name": "[STORY-002] Dashboard",
                "state_id": state_map["In Progress"], "priority": 2,
                "label_ids": [label_map.get("agent::dev2", ""), label_map.get("type::story", "")],
                "label_detail": [{"name": "agent::dev2"}, {"name": "type::story"}],
                "description_html": "<p>Build dashboard</p>",
            },
            {
                "id": _uuid(), "name": "[STORY-003] API endpoints",
                "state_id": state_map["Review"], "priority": 3,
                "label_ids": [label_map.get("agent::dev1", ""), label_map.get("type::story", "")],
                "label_detail": [{"name": "agent::dev1"}, {"name": "type::story"}],
                "description_html": "<p>REST API</p>",
            },
            {
                "id": _uuid(), "name": "[STORY-004] CI/CD pipeline",
                "state_id": state_map["Done"], "priority": 4,
                "label_ids": [label_map.get("agent::devops", ""), label_map.get("type::story", "")],
                "label_detail": [{"name": "agent::devops"}, {"name": "type::story"}],
                "description_html": "<p>Set up CI/CD</p>",
            },
            {
                "id": _uuid(), "name": "[BUG-001] Login redirect broken",
                "state_id": state_map["Todo"], "priority": 1,
                "label_ids": [label_map.get("agent::dev1", ""), label_map.get("type::bug", "")],
                "label_detail": [{"name": "agent::dev1"}, {"name": "type::bug"}],
                "description_html": "<p>Fix redirect</p>",
            },
        ]

        # Cycle
        cycle_id = _uuid()
        self.cycles = [{"id": cycle_id, "name": "Sprint 1"}]
        self.cycle_issues[cycle_id] = [wi["id"] for wi in self.work_items]

        # Pages
        self.pages = [
            {"id": _uuid(), "name": "project-description", "description": "# Test Project\n\nA test project.", "access": 0},
            {"id": _uuid(), "name": "architecture", "description": "# Architecture\n\nMicroservices.", "access": 0},
            {"id": _uuid(), "name": "decisions", "description": "# Decisions\n\nUse REST.", "access": 0},
        ]

    def find_state(self, state_id: str) -> dict | None:
        for s in self.states:
            if s["id"] == state_id:
                return s
        return None

    def find_work_item(self, wi_id: str) -> dict | None:
        for wi in self.work_items:
            if wi["id"] == wi_id:
                return wi
        return None

    def find_page(self, name: str) -> dict | None:
        for p in self.pages:
            if p["name"].lower() == name.lower():
                return p
        return None


class MockPlaneHandler(BaseHTTPRequestHandler):
    """HTTP handler simulating Plane.so API v1."""

    store: PlaneStore  # Set by the server

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress logging in tests

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _parse_path(self) -> tuple[str, str]:
        """Extract the resource type and optional ID from the path."""
        # Strip query string
        path = self.path.split("?")[0]
        # Remove prefix: /api/v1/workspaces/{slug}/projects/{project_id}/
        # We match anything ending with a known resource
        parts = path.rstrip("/").split("/")
        # Find the resource type
        known = {"states", "labels", "work-items", "cycles", "pages",
                 "comments", "cycle-issues", "members"}
        resource = ""
        resource_id = ""
        for i, part in enumerate(parts):
            if part in known:
                resource = part
                remaining = parts[i + 1:]
                if remaining and remaining[0] not in known:
                    resource_id = remaining[0]
                    # Check for sub-resource
                    if len(remaining) > 1 and remaining[1] in known:
                        return f"{resource}/{resource_id}/{remaining[1]}", (
                            remaining[2] if len(remaining) > 2 else ""
                        )
                break
        return resource, resource_id

    def _is_global_endpoint(self) -> tuple[bool, str, str]:
        """Check if this is a global/workspace-scoped endpoint.

        Global: /api/v1/workspaces/ (list/create workspaces)
        Workspace: /api/v1/workspaces/{slug}/projects/ (list/create projects)
        Returns (is_global, resource, rid).
        """
        path = self.path.split("?")[0].rstrip("/")
        parts = [p for p in path.split("/") if p]
        # /api/v1/workspaces → global workspaces endpoint
        if parts == ["api", "v1", "workspaces"]:
            return True, "workspaces", ""
        # /api/v1/workspaces/{slug}/projects → workspace projects endpoint
        if len(parts) == 5 and parts[:2] == ["api", "v1"] and parts[2] == "workspaces" and parts[4] == "projects":
            return True, "projects", ""
        return False, "", ""

    def do_GET(self) -> None:
        is_global, g_resource, g_rid = self._is_global_endpoint()
        if is_global:
            if g_resource == "workspaces":
                self._send_json({"results": self.store.workspaces})
            elif g_resource == "projects":
                self._send_json({"results": self.store.projects})
            else:
                self._send_json({"error": "unknown"}, 404)
            return

        resource, rid = self._parse_path()

        if resource == "states":
            self._send_json({"results": self.store.states})
        elif resource == "labels":
            self._send_json({"results": self.store.labels})
        elif resource == "work-items" and not rid:
            self._send_json({"results": self.store.work_items})
        elif resource == "work-items" and rid:
            wi = self.store.find_work_item(rid)
            if wi:
                self._send_json(wi)
            else:
                self._send_json({"error": "not found"}, 404)
        elif resource.startswith("work-items/") and resource.endswith("/comments"):
            wi_id = resource.split("/")[1]
            comments = self.store.comments.get(wi_id, [])
            self._send_json({"results": comments})
        elif resource == "cycles" and not rid:
            self._send_json({"results": self.store.cycles})
        elif resource == "cycles" and rid:
            for c in self.store.cycles:
                if c["id"] == rid:
                    self._send_json(c)
                    return
            self._send_json({"error": "not found"}, 404)
        elif resource.startswith("cycles/") and resource.endswith("/cycle-issues"):
            cycle_id = resource.split("/")[1]
            wi_ids = self.store.cycle_issues.get(cycle_id, [])
            issues = [
                {"issue_detail": wi}
                for wi in self.store.work_items
                if wi["id"] in wi_ids
            ]
            self._send_json({"results": issues})
        elif resource == "pages" and not rid:
            self._send_json({"results": self.store.pages})
        elif resource == "pages" and rid:
            for p in self.store.pages:
                if p["id"] == rid:
                    self._send_json(p)
                    return
            self._send_json({"error": "not found"}, 404)
        elif resource == "members":
            self._send_json({"results": []})
        else:
            self._send_json({"error": "unknown endpoint", "path": self.path}, 404)

    def do_POST(self) -> None:
        is_global, g_resource, _ = self._is_global_endpoint()
        body = self._read_body()

        if is_global:
            if g_resource == "workspaces":
                ws = {"id": _uuid(), "slug": body.get("slug", "new-ws"), **body}
                self.store.workspaces.append(ws)
                self._send_json(ws, 201)
            elif g_resource == "projects":
                proj = {"id": _uuid(), **body}
                self.store.projects.append(proj)
                self._send_json(proj, 201)
            else:
                self._send_json({"error": "unknown"}, 404)
            return

        resource, rid = self._parse_path()

        if resource == "states":
            state = {"id": _uuid(), **body}
            self.store.states.append(state)
            self._send_json(state, 201)
        elif resource == "labels":
            label = {"id": _uuid(), **body}
            self.store.labels.append(label)
            self._send_json(label, 201)
        elif resource == "work-items":
            wi = {"id": _uuid(), "label_detail": [], **body}
            # Resolve label_ids to label_detail
            if "label_ids" in wi:
                for lid in wi["label_ids"]:
                    for lbl in self.store.labels:
                        if lbl["id"] == lid:
                            wi["label_detail"].append({"name": lbl["name"]})
            self.store.work_items.append(wi)
            self._send_json(wi, 201)
        elif resource.startswith("work-items/") and resource.endswith("/comments"):
            wi_id = resource.split("/")[1]
            comment = {
                "id": _uuid(),
                "comment_stripped": body.get("comment_html", body.get("comment_stripped", "")),
                "comment_html": body.get("comment_html", ""),
                "actor_detail": {"display_name": "Agent"},
                "created_at": "2026-03-27T00:00:00Z",
            }
            self.store.comments.setdefault(wi_id, []).append(comment)
            self._send_json(comment, 201)
        elif resource == "cycles":
            cycle = {"id": _uuid(), **body}
            self.store.cycles.append(cycle)
            self.store.cycle_issues[cycle["id"]] = []
            self._send_json(cycle, 201)
        elif resource.startswith("cycles/") and resource.endswith("/cycle-issues"):
            cycle_id = resource.split("/")[1]
            issues = body.get("issues", [])
            self.store.cycle_issues.setdefault(cycle_id, []).extend(issues)
            self._send_json({"status": "ok"}, 201)
        elif resource == "pages":
            page = {"id": _uuid(), "description": body.get("description", ""), **body}
            self.store.pages.append(page)
            self._send_json(page, 201)
        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    def do_PATCH(self) -> None:
        resource, rid = self._parse_path()
        body = self._read_body()

        if resource == "work-items" and rid:
            wi = self.store.find_work_item(rid)
            if wi:
                wi.update(body)
                # Resolve label_ids to label_detail
                if "label_ids" in body:
                    wi["label_detail"] = []
                    for lid in body["label_ids"]:
                        for lbl in self.store.labels:
                            if lbl["id"] == lid:
                                wi["label_detail"].append({"name": lbl["name"]})
                self._send_json(wi)
            else:
                self._send_json({"error": "not found"}, 404)
        elif resource == "pages" and rid:
            for p in self.store.pages:
                if p["id"] == rid:
                    p.update(body)
                    self._send_json(p)
                    return
            self._send_json({"error": "not found"}, 404)
        elif resource == "states" and rid:
            for s in self.store.states:
                if s["id"] == rid:
                    s.update(body)
                    self._send_json(s)
                    return
            self._send_json({"error": "not found"}, 404)
        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    def do_DELETE(self) -> None:
        resource, rid = self._parse_path()

        if resource == "work-items" and rid:
            self.store.work_items = [wi for wi in self.store.work_items if wi["id"] != rid]
            self._send_json({"status": "ok"}, 204)
        elif resource == "pages" and rid:
            self.store.pages = [p for p in self.store.pages if p["id"] != rid]
            self._send_json({"status": "ok"}, 204)
        else:
            self._send_json({"error": "unknown endpoint"}, 404)


def start_mock_plane_server(store: PlaneStore | None = None) -> tuple[HTTPServer, str, PlaneStore]:
    """Start a mock Plane server on a random port.

    Returns (server, base_url, store).
    """
    store = store or PlaneStore()

    class Handler(MockPlaneHandler):
        pass
    Handler.store = store

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, url, store
