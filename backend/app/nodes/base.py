"""Node plugin contract and registry.

A node type is one class in one file under ``app.nodes`` decorated with ``@register_node``. The registry discovers
the package automatically; the engine, the API (``GET /api/nodes``) and the editor (form generated from
``config_schema``) need no changes when a node is added."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.engine.context import NodeContext

logger = logging.getLogger(__name__)

PORT_TYPES = ("trigger", "repo", "findings", "report", "json", "text", "bool", "any")
CATEGORIES = ("trigger", "source", "scanner", "logic", "analysis", "ai", "output", "notify")


@dataclass(frozen=True)
class Port:
    name: str
    type: str
    required: bool = True
    multiple: bool = False
    title_ru: str = ""
    title_en: str = ""

    def __post_init__(self) -> None:
        if self.type not in PORT_TYPES:
            raise ValueError(f"unknown port type {self.type!r}")

    def spec(self) -> dict:
        return {"name": self.name, "type": self.type, "required": self.required, "multiple": self.multiple,
                "title": {"ru": self.title_ru or self.name, "en": self.title_en or self.name}}


def ports_compatible(out_type: str, in_type: str) -> bool:
    return out_type == in_type or "any" in (out_type, in_type)


class EnvelopeMeta(BaseModel):
    node_id: str = ""
    produced_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    summary: str = ""


class Envelope(BaseModel):
    """Unified data passed along an edge."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    meta: EnvelopeMeta = Field(default_factory=EnvelopeMeta)

    @classmethod
    def make(cls, type_: str, data: dict[str, Any], node_id: str, summary: str = "") -> Envelope:
        return cls(type=type_, data=data, meta=EnvelopeMeta(node_id=node_id, summary=summary))


class BaseNode(ABC):
    type: ClassVar[str]
    category: ClassVar[str]
    title: ClassVar[dict[str, str]]
    description: ClassVar[dict[str, str]] = {"ru": "", "en": ""}
    icon: ClassVar[str] = ""
    inputs: ClassVar[list[Port]] = []
    outputs: ClassVar[list[Port]] = []
    config_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    # outputs that are alternatives (only one becomes active), e.g. IF/ELSE true/false
    branch_outputs: ClassVar[tuple[str, ...]] = ()
    # nodes whose timeout is longer than the default (seconds); None → engine default
    timeout_seconds: ClassVar[float | None] = None

    @abstractmethod
    async def execute(self, ctx: NodeContext, inputs: dict[str, Any], config: dict[str, Any]) -> dict[str, Envelope]:
        """Run the node. ``inputs`` maps port → Envelope (list of Envelopes for ``multiple`` ports); returns
        port → Envelope for every *active* output (an omitted branch output means that branch is not taken)."""

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> list[str]:
        """Node-specific semantic checks beyond JSON Schema (expression syntax, cron...). Returns messages."""
        return []

    @classmethod
    def input_port(cls, name: str) -> Port | None:
        return next((p for p in cls.inputs if p.name == name), None)

    @classmethod
    def output_port(cls, name: str) -> Port | None:
        return next((p for p in cls.outputs if p.name == name), None)

    @classmethod
    def credential_fields(cls) -> list[str]:
        props = cls.config_schema.get("properties", {})
        return [k for k, v in props.items() if v.get("credential_ref")]

    @classmethod
    def spec(cls) -> dict:
        return {
            "type": cls.type, "category": cls.category, "title": cls.title, "description": cls.description,
            "icon": cls.icon, "inputs": [p.spec() for p in cls.inputs], "outputs": [p.spec() for p in cls.outputs],
            "branch_outputs": list(cls.branch_outputs), "config_schema": cls.config_schema,
        }


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, type[BaseNode]] = {}

    def register(self, cls: type[BaseNode]) -> type[BaseNode]:
        for attr in ("type", "category", "title"):
            if not getattr(cls, attr, None):
                raise ValueError(f"node class {cls.__name__} misses {attr}")
        if cls.category not in CATEGORIES:
            raise ValueError(f"node {cls.type}: unknown category {cls.category!r}")
        existing = self._nodes.get(cls.type)
        if existing is not None and existing.__qualname__ != cls.__qualname__:
            raise ValueError(f"node type {cls.type!r} registered twice ({existing.__name__}, {cls.__name__})")
        self._nodes[cls.type] = cls
        return cls

    def get(self, type_: str) -> type[BaseNode] | None:
        return self._nodes.get(type_)

    def all(self) -> list[type[BaseNode]]:
        return sorted(self._nodes.values(), key=lambda c: (CATEGORIES.index(c.category), c.type))

    def types(self) -> set[str]:
        return set(self._nodes)

    def unregister(self, type_: str) -> None:
        self._nodes.pop(type_, None)


registry = NodeRegistry()
_discovered = False


def register_node(cls: type[BaseNode]) -> type[BaseNode]:
    return registry.register(cls)


def discover(package: str = "app.nodes", force: bool = False) -> NodeRegistry:
    """Import every module of the node package so that ``@register_node`` decorators run."""
    global _discovered
    if _discovered and not force:
        return registry
    pkg = importlib.import_module(package)
    importlib.invalidate_caches()
    for info in pkgutil.walk_packages(pkg.__path__, prefix=package + "."):
        if info.name.endswith(".base"):
            continue
        if info.name in sys.modules and not force:
            continue
        try:
            if info.name in sys.modules:
                importlib.reload(sys.modules[info.name])
            else:
                importlib.import_module(info.name)
        except Exception:
            logger.exception("failed to load node module %s", info.name)
            raise
    _discovered = True
    return registry


def get_registry() -> NodeRegistry:
    return discover()
