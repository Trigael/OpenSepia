"""
Board Server — Event system and webhook delivery.

Processes events (status changes, comments, etc.) and triggers
configured actions (inbox notifications, webhooks).
"""

import json
import logging
import urllib.request
import urllib.error
import threading
from typing import Any

from boardserver.config import BoardConfig, EventAction
from boardserver.db import Database

logger = logging.getLogger(__name__)


class EventProcessor:
    """Processes board events and triggers configured actions."""

    def __init__(self, db: Database, config: BoardConfig):
        self.db = db
        self.config = config

    def fire(self, event_type: str, context: dict[str, Any]) -> None:
        """Fire an event with the given context.

        Context keys depend on event type:
          item_created:  item_type, item_id, title, created_by
          status_changed: item_type, item_id, assigned, old_value, new_value, agent
          comment_added: item_type, item_id, item (dict), agent, body
          inbox_received: agent_id, from_agent, message
        """
        # Log the event
        self.db.log_event(
            event_type=event_type,
            item_id=context.get("item_id", ""),
            agent_id=context.get("agent", context.get("created_by", "")),
            data=context,
        )

        # Process configured actions
        actions = self.config.events.get(event_type, [])
        for action in actions:
            try:
                self._execute_action(action, context)
            except Exception as e:
                logger.warning("Event action failed (%s): %s", action.action, e)

        # Fire webhooks
        self._fire_webhooks(event_type, context)

    def _execute_action(self, action: EventAction, context: dict[str, Any]) -> None:
        """Execute a single event action."""
        if action.action == "notify_inbox":
            agent_id = self._render_template(action.agent, context)
            message = self._render_template(action.message, context)

            if not agent_id or agent_id.startswith("{"):
                return  # Template couldn't resolve — skip silently

            self.db.send_inbox(
                agent_id=agent_id,
                message=message,
                from_agent="system",
                item_id=context.get("item_id", ""),
            )

    def _render_template(self, template: str, context: dict[str, Any]) -> str:
        """Render a simple template string like "{assigned}" or "{item_id}"."""
        if not template or "{" not in template:
            return template

        result = template
        # Flatten item fields into context for template rendering
        flat = dict(context)
        item = context.get("item", {})
        if isinstance(item, dict):
            for k, v in item.items():
                flat[f"item.{k}"] = v
                if k not in flat:
                    flat[k] = v

        for key, value in flat.items():
            result = result.replace(f"{{{key}}}", str(value) if value else "")

        return result

    def _fire_webhooks(self, event_type: str, context: dict[str, Any]) -> None:
        """Send webhooks for this event (async, non-blocking)."""
        for hook in self.config.webhooks:
            if not hook.get("active", True):
                continue
            events = hook.get("events", [])
            if events and event_type not in events:
                continue

            url = hook.get("url", "")
            if not url:
                continue

            # Fire in background thread to not block the API
            payload = {"event": event_type, "data": context}
            thread = threading.Thread(
                target=self._send_webhook,
                args=(url, payload),
                daemon=True,
            )
            thread.start()

    def _send_webhook(self, url: str, payload: dict) -> None:
        """Send a single webhook (called in background thread)."""
        try:
            data = json.dumps(payload, default=str).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.debug("Webhook %s: %d", url, resp.status)
        except Exception as e:
            logger.warning("Webhook %s failed: %s", url, e)
