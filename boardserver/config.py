"""
Board Server — Configuration and schema loading.

Loads board-server.yaml, validates the schema definition, and provides
field validation for API requests.
"""

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


FIELD_TYPES = {"string", "text", "enum", "integer", "boolean"}


@dataclass
class FieldDef:
    """Definition of a single field in an item type."""
    name: str
    type: str
    required: bool = False
    default: Any = None
    values: list[str] | None = None  # For enum type

    def validate(self, value: Any) -> tuple[bool, str]:
        """Validate a value against this field definition.
        Returns (ok, error_message)."""
        if value is None:
            if self.required:
                return False, f"'{self.name}' is required"
            return True, ""

        if self.type == "string":
            if not isinstance(value, str):
                return False, f"'{self.name}' must be a string"
        elif self.type == "text":
            if not isinstance(value, str):
                return False, f"'{self.name}' must be a string"
        elif self.type == "integer":
            if not isinstance(value, (int, float)):
                return False, f"'{self.name}' must be an integer"
        elif self.type == "boolean":
            if not isinstance(value, bool):
                return False, f"'{self.name}' must be a boolean"
        elif self.type == "enum":
            if self.values and value not in self.values:
                return False, f"'{self.name}' must be one of: {', '.join(self.values)}"

        return True, ""

    def apply_default(self, value: Any) -> Any:
        """Return the value, or the default if value is None."""
        return value if value is not None else self.default


@dataclass
class ItemTypeDef:
    """Definition of an item type (story, bug, etc.)."""
    name: str
    id_prefix: str
    fields: dict[str, FieldDef]

    def validate_data(self, data: dict) -> tuple[bool, list[str]]:
        """Validate a full item data dict. Returns (ok, errors)."""
        errors = []
        for field_name, field_def in self.fields.items():
            value = data.get(field_name)
            ok, msg = field_def.validate(value)
            if not ok:
                errors.append(msg)
        # Check for unknown fields
        known = set(self.fields.keys())
        for key in data:
            if key not in known and key not in ("type", "id"):
                errors.append(f"Unknown field: '{key}'")
        return len(errors) == 0, errors

    def apply_defaults(self, data: dict) -> dict:
        """Apply default values to missing fields."""
        result = dict(data)
        for field_name, field_def in self.fields.items():
            if field_name not in result or result[field_name] is None:
                default = field_def.apply_default(None)
                if default is not None:
                    result[field_name] = default
        return result


@dataclass
class AgentDef:
    """Known agent identity."""
    id: str
    name: str


@dataclass
class EventAction:
    """An action triggered by an event."""
    action: str          # "notify_inbox", "webhook"
    agent: str = ""      # Template: "{assigned}" or literal "po"
    message: str = ""    # Template with {item_id}, {item_type}, etc.
    url: str = ""        # For webhook actions


@dataclass
class BoardConfig:
    """Full board server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    db_path: str = "board.db"
    item_types: dict[str, ItemTypeDef] = field(default_factory=dict)
    agents: dict[str, AgentDef] = field(default_factory=dict)
    events: dict[str, list[EventAction]] = field(default_factory=dict)
    webhooks: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, config_path: Path | None = None) -> "BoardConfig":
        """Load configuration from YAML file.

        If no path given, looks for board-server.yaml in CWD,
        then falls back to the default config bundled with the package.
        """
        if config_path is None:
            cwd_config = Path("board-server.yaml")
            if cwd_config.exists():
                config_path = cwd_config
            else:
                config_path = Path(__file__).parent / "default_config.yaml"

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        return cls._parse(raw)

    @classmethod
    def _parse(cls, raw: dict) -> "BoardConfig":
        """Parse raw YAML dict into BoardConfig."""
        server = raw.get("server", {})

        # Parse item types
        item_types = {}
        for type_name, type_def in raw.get("item_types", {}).items():
            fields = {}
            for fname, fdef in type_def.get("fields", {}).items():
                fields[fname] = FieldDef(
                    name=fname,
                    type=fdef.get("type", "string"),
                    required=fdef.get("required", False),
                    default=fdef.get("default"),
                    values=fdef.get("values"),
                )
            item_types[type_name] = ItemTypeDef(
                name=type_name,
                id_prefix=type_def.get("id_prefix", type_name.upper()),
                fields=fields,
            )

        # Parse agents
        agents = {}
        for agent_raw in raw.get("agents", []):
            agent = AgentDef(id=agent_raw["id"], name=agent_raw.get("name", agent_raw["id"]))
            agents[agent.id] = agent

        # Parse events
        events = {}
        for event_name, actions_raw in raw.get("events", {}).items():
            actions = []
            for a in actions_raw:
                actions.append(EventAction(
                    action=a.get("action", ""),
                    agent=a.get("agent", ""),
                    message=a.get("message", ""),
                    url=a.get("url", ""),
                ))
            events[event_name] = actions

        # Parse webhooks
        webhooks = raw.get("webhooks", []) or []

        return cls(
            host=server.get("host", "0.0.0.0"),
            port=server.get("port", 8080),
            db_path=server.get("db", "board.db"),
            item_types=item_types,
            agents=agents,
            events=events,
            webhooks=webhooks,
        )

    def get_item_type(self, type_name: str) -> Optional[ItemTypeDef]:
        return self.item_types.get(type_name)

    def get_agent(self, agent_id: str) -> Optional[AgentDef]:
        return self.agents.get(agent_id)
