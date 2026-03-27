"""
Board Server — REST API.

HTTP handler for the board server API. Uses stdlib http.server
with a simple routing system. No external dependencies.

All requests can include agent identification via:
  - X-Agent-Id header
  - ?agent=<id> query parameter

API routes:
  GET    /api/items                    List items (filter: type, status, assigned, sprint)
  POST   /api/items                    Create item
  GET    /api/items/{id}               Get item with comments
  PATCH  /api/items/{id}               Update item fields
  DELETE /api/items/{id}               Delete item

  GET    /api/items/{id}/comments      Get comments
  POST   /api/items/{id}/comments      Add comment

  GET    /api/inbox/{agent_id}         Get inbox (unread by default)
  POST   /api/inbox/{agent_id}         Send message to agent
  DELETE /api/inbox/{agent_id}         Mark all as read

  GET    /api/board                    Kanban board view
  GET    /api/agents                   List known agents
  GET    /api/events                   Recent events
  GET    /api/schema                   Item type schemas

  GET    /                             Web UI (static files)
"""

import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from typing import Any

from boardserver.config import BoardConfig
from boardserver.db import Database
from boardserver.events import EventProcessor

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTP server that handles each request in a new thread."""
    daemon_threads = True


class APIHandler(BaseHTTPRequestHandler):
    """Request handler for the board server API."""

    # These are set by the server factory
    db: Database = None  # type: ignore
    config: BoardConfig = None  # type: ignore
    events: EventProcessor = None  # type: ignore
    auth_token: str | None = None  # Set from BOARD_SERVER_TOKEN env var

    def address_string(self):
        """Override to skip reverse DNS lookup (causes 5-10s delay per request)."""
        return self.client_address[0]

    def log_message(self, format, *args):
        """Override to use Python logging instead of stderr."""
        logger.debug("%s %s", self.client_address[0], format % args)

    # ----- Auth -----

    def _check_auth(self) -> bool:
        """Verify Bearer token if BOARD_SERVER_TOKEN is configured.

        Returns True if the request is authorized, False otherwise
        (and sends a 401 response).
        """
        token = self.auth_token
        if not token:
            return True  # No token configured — skip auth

        auth_header = self.headers.get("Authorization", "")
        if auth_header == f"Bearer {token}":
            return True

        self._json_error(401, "Unauthorized")
        return False

    # ----- Routing -----

    def do_GET(self) -> None:
        if not self._check_auth():
            return
        path, params = self._parse_url()

        if path == "/api/items":
            self._list_items(params)
        elif path.startswith("/api/items/") and path.endswith("/comments"):
            item_id = path.split("/")[3]
            self._get_comments(item_id)
        elif path.startswith("/api/items/"):
            item_id = path.split("/")[3]
            self._get_item(item_id)
        elif path.startswith("/api/inbox/"):
            agent_id = path.split("/")[3]
            self._get_inbox(agent_id, params)
        elif path == "/api/board":
            self._get_board()
        elif path == "/api/agents":
            self._get_agents()
        elif path == "/api/events":
            self._get_events(params)
        elif path == "/api/schema":
            self._get_schema()
        elif path == "/" or path == "/index.html":
            self._serve_static("index.html")
        elif path.startswith("/"):
            # Try to serve as static file
            filename = path.lstrip("/")
            if (STATIC_DIR / filename).exists():
                self._serve_static(filename)
            else:
                self._json_error(404, "Not found")
        else:
            self._json_error(404, "Not found")

    def do_POST(self) -> None:
        if not self._check_auth():
            return
        path, params = self._parse_url()
        body = self._read_body()

        if path == "/api/items":
            self._create_item(body)
        elif path.startswith("/api/items/") and path.endswith("/comments"):
            item_id = path.split("/")[3]
            self._add_comment(item_id, body)
        elif path.startswith("/api/inbox/"):
            agent_id = path.split("/")[3]
            self._send_inbox(agent_id, body)
        else:
            self._json_error(404, "Not found")

    def do_PATCH(self) -> None:
        if not self._check_auth():
            return
        path, params = self._parse_url()
        body = self._read_body()

        if path.startswith("/api/items/"):
            item_id = path.split("/")[3]
            self._update_item(item_id, body)
        else:
            self._json_error(404, "Not found")

    def do_DELETE(self) -> None:
        if not self._check_auth():
            return
        path, params = self._parse_url()

        if path.startswith("/api/items/"):
            item_id = path.split("/")[3]
            self._delete_item(item_id)
        elif path.startswith("/api/inbox/"):
            agent_id = path.split("/")[3]
            self._mark_inbox_read(agent_id)
        else:
            self._json_error(404, "Not found")

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(204)
        self._add_cors_headers()
        self.end_headers()

    # ----- API implementations -----

    def _list_items(self, params: dict) -> None:
        items = self.db.list_items(
            item_type=params.get("type"),
            status=params.get("status"),
            assigned=params.get("assigned"),
            sprint=int(params["sprint"]) if params.get("sprint") else None,
        )
        self._json_response(items)

    def _get_item(self, item_id: str) -> None:
        item = self.db.get_item(item_id)
        if not item:
            self._json_error(404, f"Item {item_id} not found")
            return
        item["comments"] = self.db.get_comments(item_id)
        self._json_response(item)

    def _create_item(self, body: dict) -> None:
        item_type = body.pop("type", None)
        if not item_type:
            self._json_error(400, "Missing 'type' field")
            return

        if item_type not in self.config.item_types:
            self._json_error(400, f"Unknown item type: {item_type}. Valid: {', '.join(self.config.item_types)}")
            return

        agent = self._get_agent_id()
        try:
            item = self.db.create_item(item_type, body, created_by=agent)
        except ValueError as e:
            self._json_error(400, str(e))
            return

        # Fire event
        self.events.fire("item_created", {
            "item_type": item_type,
            "item_id": item["id"],
            "title": item.get("title", ""),
            "created_by": agent,
            "item": item,
        })

        self._json_response(item, status=201)

    def _update_item(self, item_id: str, body: dict) -> None:
        agent = self._get_agent_id()
        old_item = self.db.get_item(item_id)
        if not old_item:
            self._json_error(404, f"Item {item_id} not found")
            return

        try:
            item = self.db.update_item(item_id, body, updated_by=agent)
        except ValueError as e:
            self._json_error(400, str(e))
            return

        # Fire events for changes
        changes = item.pop("_changes", {})
        if "status" in changes:
            self.events.fire("status_changed", {
                "item_type": item["type"],
                "item_id": item_id,
                "assigned": item.get("assigned", ""),
                "old_value": changes["status"]["old"],
                "new_value": changes["status"]["new"],
                "agent": agent,
                "item": item,
            })

        self._json_response(item)

    def _delete_item(self, item_id: str) -> None:
        if self.db.delete_item(item_id):
            self._json_response({"deleted": item_id})
        else:
            self._json_error(404, f"Item {item_id} not found")

    def _get_comments(self, item_id: str) -> None:
        comments = self.db.get_comments(item_id)
        self._json_response(comments)

    def _add_comment(self, item_id: str, body: dict) -> None:
        agent = self._get_agent_id()
        text = body.get("body", body.get("text", ""))
        if not text:
            self._json_error(400, "Missing 'body' field")
            return

        comment = self.db.add_comment(item_id, agent, text)
        if not comment:
            self._json_error(404, f"Item {item_id} not found")
            return

        # Fire event
        item = self.db.get_item(item_id) or {}
        self.events.fire("comment_added", {
            "item_type": item.get("type", ""),
            "item_id": item_id,
            "agent": agent,
            "body": text,
            "item": item,
        })

        self._json_response(comment, status=201)

    def _get_inbox(self, agent_id: str, params: dict) -> None:
        unread_only = params.get("all") != "true"
        messages = self.db.get_inbox(agent_id, unread_only=unread_only)
        self._json_response(messages)

    def _send_inbox(self, agent_id: str, body: dict) -> None:
        message = body.get("message", body.get("text", ""))
        if not message:
            self._json_error(400, "Missing 'message' field")
            return

        from_agent = self._get_agent_id()
        item_id = body.get("item_id", "")

        msg = self.db.send_inbox(agent_id, message, from_agent=from_agent, item_id=item_id)

        # Fire event
        self.events.fire("inbox_received", {
            "agent_id": agent_id,
            "from_agent": from_agent,
            "message": message,
        })

        self._json_response(msg, status=201)

    def _mark_inbox_read(self, agent_id: str) -> None:
        count = self.db.mark_inbox_read(agent_id)
        self._json_response({"agent_id": agent_id, "marked_read": count})

    def _get_board(self) -> None:
        board = self.db.get_board()
        self._json_response(board)

    def _get_agents(self) -> None:
        agents = [{"id": a.id, "name": a.name} for a in self.config.agents.values()]
        self._json_response(agents)

    def _get_events(self, params: dict) -> None:
        limit = int(params.get("limit", "100"))
        event_type = params.get("type")
        events = self.db.get_events(limit=limit, event_type=event_type)
        self._json_response(events)

    def _get_schema(self) -> None:
        schema = {}
        for name, type_def in self.config.item_types.items():
            schema[name] = {
                "id_prefix": type_def.id_prefix,
                "fields": {
                    fname: {
                        "type": fdef.type,
                        "required": fdef.required,
                        "default": fdef.default,
                        **({"values": fdef.values} if fdef.values else {}),
                    }
                    for fname, fdef in type_def.fields.items()
                },
            }
        self._json_response(schema)

    # ----- Static files -----

    def _serve_static(self, filename: str) -> None:
        filepath = STATIC_DIR / filename
        if not filepath.exists():
            self._json_error(404, "Not found")
            return

        content_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }
        ext = filepath.suffix
        content_type = content_types.get(ext, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(filepath.read_bytes())

    # ----- Helpers -----

    def _get_agent_id(self) -> str:
        """Extract agent ID from request (header or query param)."""
        agent = self.headers.get("X-Agent-Id", "")
        if not agent:
            _, params = self._parse_url()
            agent = params.get("agent", "")
        return agent or "anonymous"

    def _parse_url(self) -> tuple[str, dict]:
        """Parse URL path and query parameters."""
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return parsed.path.rstrip("/"), params

    def _read_body(self) -> dict:
        """Read and parse JSON body."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _json_response(self, data: Any, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, message: str) -> None:
        """Send a JSON error response."""
        self._json_response({"error": message}, status=status)

    def _add_cors_headers(self) -> None:
        """Add CORS headers for browser access."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Agent-Id, Authorization")


def create_server(config: BoardConfig, db: Database) -> ThreadedHTTPServer:
    """Create and configure the HTTP server."""
    events = EventProcessor(db, config)

    # Inject dependencies into the handler class
    APIHandler.db = db
    APIHandler.config = config
    APIHandler.events = events
    APIHandler.auth_token = os.environ.get("BOARD_SERVER_TOKEN") or None

    server = ThreadedHTTPServer((config.host, config.port), APIHandler)
    return server
