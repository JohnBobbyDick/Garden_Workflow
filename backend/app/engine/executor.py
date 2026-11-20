"""Workflow executor: topological, event-driven, parallel branches on asyncio.

Semantics:
* a node starts when every predecessor is terminal;
* an edge is *active* when its source succeeded and produced data on that port (IF/ELSE produces one branch);
* a node with incoming edges is ``skipped`` when none of them is active (or a required input has no active edge),
  so an untaken branch is skipped together with everything that depends only on it; a join waits for active inputs;
* a failed node makes its exclusive dependents ``skipped`` and the run ``failed``; other branches continue;
* node timeout → node ``failed``; run timeout / cancel → running and pending nodes ``cancelled``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.masking import Masker
from app.engine.context import EventSink, NodeContext, RunInfo, RunServices
from app.engine.graph import Graph, GraphNode, topological_order
from app.nodes.base import BaseNode, Envelope, NodeRegistry

logger = logging.getLogger(__name__)

PREVIEW_CHARS = 2000
TERMINAL = {"success", "failed", "skipped", "cancelled"}


class ListSink:
    """In-memory event sink (used by the CLI runner and tests)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, type_: str, node_id: str | None, data: dict[str, Any]) -> None:
        self.events.append({"type": type_, "node_id": node_id, "data": data})


@dataclass
class RunResult:
    status: str
    node_status: dict[str, str]
    outputs: dict[str, dict[str, Envelope]] = field(default_factory=dict)
    error: str | None = None
    state: dict[str, Any] = field(default_factory=dict)


def apply_defaults(schema: dict, config: dict) -> dict:
    out = dict(config)
    for key, prop in (schema.get("properties") or {}).items():
        if key not in out and isinstance(prop, dict) and "default" in prop:
            out[key] = prop["default"]
    return out


def envelope_preview(env: Envelope, masker: Masker) -> dict[str, Any]:
    data = env.data
    count = None
    if env.type == "findings":
        count = len(data.get("findings", []))
    try:
        text = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(data)
    text = masker.mask(text)
    if len(text) > PREVIEW_CHARS:
        text = text[:PREVIEW_CHARS] + "…"
    return {"type": env.type, "summary": masker.mask(env.meta.summary), "count": count, "preview": text}


class Executor:
    def __init__(self, graph: Graph, registry: NodeRegistry, run: RunInfo, sink: EventSink, *,
                 masker: Masker | None = None, services: RunServices | None = None,
                 node_timeout: float = 300.0, run_timeout: float = 1800.0,
                 cancel_check: Callable[[], Awaitable[bool]] | None = None, poll_interval: float = 0.5) -> None:
        self.graph = graph
        self.registry = registry
        self.run_info = run
        self.sink = sink
        self.masker = masker or Masker()
        self.services = services
        self.node_timeout = node_timeout
        self.run_timeout = run_timeout
        self.cancel_check = cancel_check
        self.poll_interval = poll_interval
        self.status: dict[str, str] = {n.id: "pending" for n in graph.nodes}
        self.outputs: dict[str, dict[str, Envelope]] = {}
        self.active_edges: set[str] = set()
        self.state: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._started: dict[str, float] = {}
        self._cancelled = False

    # -- events ---------------------------------------------------------------------------------------------
    def _node_status(self, node_id: str, status: str, **extra: Any) -> None:
        self.status[node_id] = status
        data: dict[str, Any] = {"status": status}
        if node_id in self._started and status in TERMINAL:
            data["duration_ms"] = int((time.monotonic() - self._started[node_id]) * 1000)
        for k, v in extra.items():
            data[k] = self.masker.mask(v) if isinstance(v, str) else v
        self.sink.emit("node.status", node_id, data)

    # -- main -----------------------------------------------------------------------------------------------
    async def run(self) -> RunResult:
        self.sink.emit("run.status", None, {"status": "running"})
        error: str | None = None
        order = topological_order(self.graph)
        if order is None:
            error = "граф содержит цикл"
            for nid in self.status:
                self._node_status(nid, "cancelled")
        else:
            try:
                await asyncio.wait_for(self._loop(order), timeout=self.run_timeout)
            except TimeoutError:
                error = f"run timeout after {self.run_timeout:g}s"
            for nid, st in self.status.items():
                if st in ("pending", "running"):
                    self._node_status(nid, "cancelled")
        if self._cancelled:
            final = "cancelled"
        elif error or any(s == "failed" for s in self.status.values()):
            final = "failed"
            if error is None:
                failed = [n for n, s in self.status.items() if s == "failed"]
                error = "ошибка в нодах: " + ", ".join(failed)
        else:
            final = "success"
        self.sink.emit("run.status", None, {"status": final, "error": error})
        return RunResult(final, dict(self.status), self.outputs, error, self.state)

    async def _loop(self, order: list[str]) -> None:
        try:
            while True:
                self._schedule_ready(order)
                if not self._tasks:
                    if all(self.status[n] in TERMINAL for n in order):
                        return
                    # unreachable in a DAG; guard against a stuck loop
                    for n in order:
                        if self.status[n] == "pending":
                            self._node_status(n, "skipped", reason="не достижима")
                    return
                done, _ = await asyncio.wait(set(self._tasks.values()), timeout=self.poll_interval,
                                             return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    nid = next(k for k, t in self._tasks.items() if t is task)
                    del self._tasks[nid]
                    self._finish(nid, task)
                if self.cancel_check is not None and await self.cancel_check():
                    self._cancelled = True
                    await self._cancel_running()
                    return
        except asyncio.CancelledError:
            await self._cancel_running()
            raise

    async def _cancel_running(self) -> None:
        tasks = list(self._tasks.items())
        for _, t in tasks:
            t.cancel()
        for nid, t in tasks:
            try:
                await t
            except BaseException:  # noqa: BLE001 - we only wait for the cancellation to settle
                pass
            self._node_status(nid, "cancelled")
        self._tasks.clear()

    def _schedule_ready(self, order: list[str]) -> None:
        for nid in order:
            if self.status[nid] != "pending":
                continue
            incoming = self.graph.incoming(nid)
            if any(self.status.get(e.source) in ("pending", "running") for e in incoming):
                continue
            node = self.graph.node(nid)
            assert node is not None
            cls = self.registry.get(node.type)
            reason = self._skip_reason(node, cls, incoming)
            if reason:
                self._node_status(nid, "skipped", reason=reason)
                continue
            self._started[nid] = time.monotonic()
            self._node_status(nid, "running")
            self._tasks[nid] = asyncio.create_task(self._execute(node, cls))

    def _skip_reason(self, node: GraphNode, cls: type[BaseNode] | None, incoming: list) -> str | None:
        if cls is None:
            return f"неизвестный тип ноды {node.type}"
        if node.disabled:
            return "нода отключена"
        if cls.category == "trigger":
            tid = self.run_info.trigger_node_id
            return None if tid in (None, node.id) else "запуск инициирован другим триггером"
        if not incoming:
            return None
        active = [e for e in incoming if e.id in self.active_edges]
        if not active:
            return "нет активных входов (ветка не выбрана или предыдущая нода не выполнена)"
        for p in cls.inputs:
            if p.required and not any(e.target_port == p.name for e in active):
                return f"обязательный вход «{p.name}» не получил данных"
        return None

    def _gather_inputs(self, node: GraphNode, cls: type[BaseNode]) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for p in cls.inputs:
            envs = [self.outputs[e.source][e.source_port] for e in self.graph.incoming(node.id)
                    if e.target_port == p.name and e.id in self.active_edges]
            if p.multiple:
                if envs:
                    inputs[p.name] = envs
            elif envs:
                inputs[p.name] = envs[0]
        return inputs

    async def _execute(self, node: GraphNode, cls: type[BaseNode]) -> dict[str, Envelope]:
        inputs = self._gather_inputs(node, cls)
        if inputs:
            self.sink.emit("node.input", node.id, {"ports": {
                k: ([envelope_preview(e, self.masker) for e in v] if isinstance(v, list)
                    else envelope_preview(v, self.masker)) for k, v in inputs.items()}})
        ctx = NodeContext(self.run_info, node.id, node.type, self.sink, self.masker, self.services, self.state)
        config = apply_defaults(cls.config_schema, node.config)
        timeout = cls.timeout_seconds or self.node_timeout
        try:
            result = await asyncio.wait_for(cls().execute(ctx, inputs, config), timeout=timeout)
        except TimeoutError as exc:
            raise NodeTimeout(f"node timeout after {timeout:g}s") from exc
        if not isinstance(result, dict):
            raise TypeError(f"node {node.type} returned {type(result).__name__}, expected dict of envelopes")
        for port, env in result.items():
            if cls.output_port(port) is None or not isinstance(env, Envelope):
                raise TypeError(f"node {node.type} produced invalid output on port {port!r}")
        return result

    def _finish(self, nid: str, task: asyncio.Task) -> None:
        exc = task.exception() if not task.cancelled() else asyncio.CancelledError()
        if isinstance(exc, asyncio.CancelledError):
            self._node_status(nid, "cancelled")
            return
        if exc is not None:
            msg = str(exc) if isinstance(exc, NodeTimeout) else f"{type(exc).__name__}: {exc}"
            logger.info("node %s failed: %s", nid, self.masker.mask(msg))
            self._node_status(nid, "failed", error=self.masker.mask(msg)[:4000])
            return
        result: dict[str, Envelope] = task.result()
        self.outputs[nid] = result
        ports = {}
        for port, env in result.items():
            ports[port] = envelope_preview(env, self.masker)
        self.sink.emit("node.output", nid, {"ports": ports})
        for e in self.graph.outgoing(nid):
            if e.source_port in result:
                self.active_edges.add(e.id)
                pv = ports[e.source_port]
                self.sink.emit("edge.data", None, {"edge_id": e.id, "count": pv["count"], "summary": pv["summary"]})
        summary = "; ".join(p["summary"] for p in ports.values() if p["summary"])
        self._node_status(nid, "success", summary=summary, ports=sorted(result))


class NodeTimeout(Exception):
    pass
