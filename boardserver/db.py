"""
Board Server — SQLite database layer.

Generic item storage with JSON fields, plus comments, inbox, and events.
All queries go through this module.
"""

import json
import sqlite3
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from boardserver.config import BoardConfig, ItemTypeDef

logger = logging.getLogger(__name__)


class Database:
    """SQLite-backed storage for the board server."""

    def __init__(self, db_path: str, config: BoardConfig):
        self.db_path = db_path
        self.config = config
        self.conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    def connect(self) -> None:
        """Open database connection and create tables."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _create_tables(self) -> None:
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                prefix_id TEXT NOT NULL UNIQUE,
                fields TEXT NOT NULL DEFAULT '{}',
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_items_type ON items(type);
            CREATE INDEX IF NOT EXISTS idx_items_prefix_id ON items(prefix_id);

            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id),
                author TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comments_item ON comments(item_id);

            CREATE TABLE IF NOT EXISTS inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                from_agent TEXT DEFAULT '',
                item_id INTEGER REFERENCES items(id),
                message TEXT NOT NULL,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_inbox_agent ON inbox(agent_id, read);

            CREATE TABLE IF NOT EXISTS events_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                item_id INTEGER REFERENCES items(id),
                agent_id TEXT DEFAULT '',
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS counters (
                type TEXT PRIMARY KEY,
                next_num INTEGER NOT NULL DEFAULT 1
            );
        """)
        c.commit()

    def _next_id(self, item_type: str, prefix: str) -> str:
        """Generate the next sequential ID like STORY-001."""
        with self._lock:
            c = self.conn
            row = c.execute("SELECT next_num FROM counters WHERE type = ?", (item_type,)).fetchone()
            if row:
                num = row["next_num"]
                c.execute("UPDATE counters SET next_num = ? WHERE type = ?", (num + 1, item_type))
            else:
                num = 1
                c.execute("INSERT INTO counters (type, next_num) VALUES (?, ?)", (item_type, 2))
            c.commit()
            return f"{prefix}-{num:03d}"

    # ----- Items -----

    def create_item(self, item_type: str, fields: dict, created_by: str = "") -> dict:
        """Create a new item. Returns the created item dict."""
        with self._lock:
            type_def = self.config.get_item_type(item_type)
            if not type_def:
                raise ValueError(f"Unknown item type: {item_type}")

            fields = type_def.apply_defaults(fields)
            ok, errors = type_def.validate_data(fields)
            if not ok:
                raise ValueError(f"Validation failed: {'; '.join(errors)}")

            prefix_id = self._next_id(item_type, type_def.id_prefix)
            now = datetime.now().isoformat()

            self.conn.execute(
                "INSERT INTO items (type, prefix_id, fields, created_by, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_type, prefix_id, json.dumps(fields), created_by, now, now),
            )
            self.conn.commit()

            return self._item_to_dict(
                self.conn.execute("SELECT * FROM items WHERE prefix_id = ?", (prefix_id,)).fetchone()
            )

    def get_item(self, prefix_id: str) -> Optional[dict]:
        """Get an item by its prefix ID (e.g., STORY-001)."""
        with self._lock:
            row = self.conn.execute("SELECT * FROM items WHERE prefix_id = ?", (prefix_id,)).fetchone()
            return self._item_to_dict(row) if row else None

    def list_items(
        self,
        item_type: str | None = None,
        status: str | None = None,
        assigned: str | None = None,
        sprint: int | None = None,
    ) -> list[dict]:
        """List items with optional filters."""
        with self._lock:
            query = "SELECT * FROM items WHERE 1=1"
            params: list[Any] = []

            if item_type:
                query += " AND type = ?"
                params.append(item_type)

            rows = self.conn.execute(query + " ORDER BY id", params).fetchall()
            items = [self._item_to_dict(r) for r in rows]

            # Filter by field values (done in Python since fields are JSON)
            if status:
                items = [i for i in items if i.get("status") == status]
            if assigned:
                items = [i for i in items if i.get("assigned") == assigned]
            if sprint is not None:
                items = [i for i in items if i.get("sprint") == sprint]

            return items

    def update_item(self, prefix_id: str, updates: dict, updated_by: str = "") -> Optional[dict]:
        """Update an item's fields. Returns updated item or None if not found."""
        with self._lock:
            row = self.conn.execute("SELECT * FROM items WHERE prefix_id = ?", (prefix_id,)).fetchone()
            if not row:
                return None

            current_fields = json.loads(row["fields"])
            item_type = row["type"]
            type_def = self.config.get_item_type(item_type)

            # Track changes for events
            changes = {}
            for key, value in updates.items():
                if key in ("type", "id", "prefix_id"):
                    continue
                old = current_fields.get(key)
                if old != value:
                    changes[key] = {"old": old, "new": value}
                    current_fields[key] = value

            if not changes:
                return self._item_to_dict(row)

            # Validate updated fields
            if type_def:
                ok, errors = type_def.validate_data(current_fields)
                if not ok:
                    raise ValueError(f"Validation failed: {'; '.join(errors)}")

            now = datetime.now().isoformat()
            self.conn.execute(
                "UPDATE items SET fields = ?, updated_at = ? WHERE prefix_id = ?",
                (json.dumps(current_fields), now, prefix_id),
            )
            self.conn.commit()

            item = self._item_to_dict(
                self.conn.execute("SELECT * FROM items WHERE prefix_id = ?", (prefix_id,)).fetchone()
            )
            item["_changes"] = changes
            return item

    def delete_item(self, prefix_id: str) -> bool:
        """Delete an item and its comments. Returns True if deleted."""
        with self._lock:
            row = self.conn.execute("SELECT id FROM items WHERE prefix_id = ?", (prefix_id,)).fetchone()
            if not row:
                return False
            self.conn.execute("DELETE FROM comments WHERE item_id = ?", (row["id"],))
            self.conn.execute("DELETE FROM items WHERE id = ?", (row["id"],))
            self.conn.commit()
            return True

    def _item_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a flat dict (fields merged in)."""
        fields = json.loads(row["fields"])
        return {
            "id": row["prefix_id"],
            "type": row["type"],
            "_db_id": row["id"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **fields,
        }

    # ----- Comments -----

    def add_comment(self, prefix_id: str, author: str, body: str) -> Optional[dict]:
        """Add a comment to an item. Returns the comment dict."""
        with self._lock:
            row = self.conn.execute("SELECT id FROM items WHERE prefix_id = ?", (prefix_id,)).fetchone()
            if not row:
                return None

            now = datetime.now().isoformat()
            cursor = self.conn.execute(
                "INSERT INTO comments (item_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                (row["id"], author, body, now),
            )
            self.conn.commit()

            return {
                "id": cursor.lastrowid,
                "item_id": prefix_id,
                "author": author,
                "body": body,
                "created_at": now,
            }

    def get_comments(self, prefix_id: str, limit: int = 50) -> list[dict]:
        """Get comments for an item, newest first."""
        with self._lock:
            row = self.conn.execute("SELECT id FROM items WHERE prefix_id = ?", (prefix_id,)).fetchone()
            if not row:
                return []

            rows = self.conn.execute(
                "SELECT * FROM comments WHERE item_id = ? ORDER BY id DESC LIMIT ?",
                (row["id"], limit),
            ).fetchall()

            return [
                {
                    "id": r["id"],
                    "item_id": prefix_id,
                    "author": r["author"],
                    "body": r["body"],
                    "created_at": r["created_at"],
                }
                for r in reversed(rows)
            ]

    # ----- Inbox -----

    def send_inbox(self, agent_id: str, message: str, from_agent: str = "", item_id: str = "") -> dict:
        """Send a message to an agent's inbox."""
        with self._lock:
            db_item_id = None
            if item_id:
                row = self.conn.execute("SELECT id FROM items WHERE prefix_id = ?", (item_id,)).fetchone()
                if row:
                    db_item_id = row["id"]

            now = datetime.now().isoformat()
            cursor = self.conn.execute(
                "INSERT INTO inbox (agent_id, from_agent, item_id, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (agent_id, from_agent, db_item_id, message, now),
            )
            self.conn.commit()

            return {
                "id": cursor.lastrowid,
                "agent_id": agent_id,
                "from_agent": from_agent,
                "item_id": item_id,
                "message": message,
                "read": False,
                "created_at": now,
            }

    def get_inbox(self, agent_id: str, unread_only: bool = True) -> list[dict]:
        """Get inbox messages for an agent."""
        with self._lock:
            query = "SELECT * FROM inbox WHERE agent_id = ?"
            params: list[Any] = [agent_id]
            if unread_only:
                query += " AND read = 0"
            query += " ORDER BY id"

            rows = self.conn.execute(query, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "agent_id": r["agent_id"],
                    "from_agent": r["from_agent"],
                    "message": r["message"],
                    "read": bool(r["read"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def mark_inbox_read(self, agent_id: str) -> int:
        """Mark all inbox messages as read for an agent. Returns count."""
        with self._lock:
            cursor = self.conn.execute(
                "UPDATE inbox SET read = 1 WHERE agent_id = ? AND read = 0",
                (agent_id,),
            )
            self.conn.commit()
            return cursor.rowcount

    # ----- Events log -----

    def log_event(self, event_type: str, item_id: str = "", agent_id: str = "", data: dict | None = None) -> dict:
        """Log an event."""
        with self._lock:
            db_item_id = None
            if item_id:
                row = self.conn.execute("SELECT id FROM items WHERE prefix_id = ?", (item_id,)).fetchone()
                if row:
                    db_item_id = row["id"]

            now = datetime.now().isoformat()
            self.conn.execute(
                "INSERT INTO events_log (event_type, item_id, agent_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_type, db_item_id, agent_id, json.dumps(data or {}), now),
            )
            self.conn.commit()

            return {"event_type": event_type, "item_id": item_id, "agent_id": agent_id, "created_at": now}

    def get_events(self, limit: int = 100, event_type: str | None = None) -> list[dict]:
        """Get recent events."""
        with self._lock:
            query = "SELECT * FROM events_log"
            params: list[Any] = []
            if event_type:
                query += " WHERE event_type = ?"
                params.append(event_type)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            rows = self.conn.execute(query, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "agent_id": r["agent_id"],
                    "data": json.loads(r["data"]),
                    "created_at": r["created_at"],
                }
                for r in reversed(rows)
            ]

    # ----- Board view -----

    def get_board(self) -> dict:
        """Get kanban board view — items grouped by status."""
        with self._lock:
            items = self.list_items()
            board: dict[str, list[dict]] = {}
            for item in items:
                status = item.get("status", "unknown")
                if status not in board:
                    board[status] = []
                board[status].append(item)
            return board
