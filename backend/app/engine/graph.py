"""Workflow graph format (stored in DB, exported/imported as JSON)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class Position(BaseModel):
    x: float = 0
    y: float = 0


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    position: Position = Field(default_factory=Position)
    config: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    disabled: bool = False


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1, max_length=64)
    source: str
    source_port: str = "out"
    target: str
    target_port: str = "in"


class Graph(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: int = SCHEMA_VERSION
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)

    def node(self, node_id: str) -> GraphNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def incoming(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.target == node_id]

    def outgoing(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.source == node_id]


def topological_order(graph: Graph) -> list[str] | None:
    """Kahn's algorithm; None if the graph has a cycle. Edges to unknown nodes are ignored."""
    ids = [n.id for n in graph.nodes]
    known = set(ids)
    indeg = dict.fromkeys(ids, 0)
    succ: dict[str, list[str]] = {i: [] for i in ids}
    for e in graph.edges:
        if e.source in known and e.target in known:
            indeg[e.target] += 1
            succ[e.source].append(e.target)
    queue = [i for i in ids if indeg[i] == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for t in succ[n]:
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    return order if len(order) == len(ids) else None
