"""Graph validation used before every run, by the editor ("Проверить граф") and by AI workflow generation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

import jsonschema
from pydantic import BaseModel

from app.engine.graph import SCHEMA_VERSION, Graph, topological_order
from app.nodes.base import NodeRegistry, ports_compatible


class ValidationIssue(BaseModel):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None


def _schema_errors(schema: dict, config: dict) -> list[tuple[str | None, str]]:
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(config), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) or None
        if err.validator == "required":
            missing = err.message.split("'")[1] if "'" in err.message else None
            out.append((missing, f"обязательное поле «{missing}» не заполнено" if missing else err.message))
        else:
            out.append((path, err.message))
    return out


def validate_graph(graph: Graph, registry: NodeRegistry,
                   credential_exists: Callable[[str], bool] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(code: str, message: str, **kw) -> None:
        issues.append(ValidationIssue(code=code, message=message, **kw))

    if graph.schema_version != SCHEMA_VERSION:
        add("schema_version", f"неподдерживаемая версия схемы графа {graph.schema_version}")

    counts = Counter(n.id for n in graph.nodes)
    for nid, c in counts.items():
        if c > 1:
            add("duplicate_node", f"идентификатор ноды «{nid}» повторяется", node_id=nid)

    node_cls = {}
    for n in graph.nodes:
        cls = registry.get(n.type)
        if cls is None:
            add("unknown_type", f"неизвестный тип ноды «{n.type}»", node_id=n.id)
            continue
        node_cls[n.id] = cls

    if not any(cls.category == "trigger" for cls in node_cls.values()):
        add("no_trigger", "в сценарии нет ни одного триггера")

    seen_edges: set[tuple] = set()
    per_input: Counter = Counter()
    for e in graph.edges:
        src, dst = graph.node(e.source), graph.node(e.target)
        if src is None or dst is None:
            add("unknown_node", f"связь {e.id} ссылается на несуществующую ноду", edge_id=e.id)
            continue
        if e.source == e.target:
            add("self_loop", "нода не может быть соединена сама с собой", edge_id=e.id, node_id=e.source)
            continue
        key = (e.source, e.source_port, e.target, e.target_port)
        if key in seen_edges:
            add("duplicate_edge", "такая связь уже существует", edge_id=e.id, node_id=e.target)
            continue
        seen_edges.add(key)
        scls, tcls = node_cls.get(e.source), node_cls.get(e.target)
        if scls is None or tcls is None:
            continue
        out_p, in_p = scls.output_port(e.source_port), tcls.input_port(e.target_port)
        if out_p is None:
            add("unknown_port", f"у ноды нет выхода «{e.source_port}»", edge_id=e.id, node_id=e.source)
            continue
        if in_p is None:
            add("unknown_port", f"у ноды нет входа «{e.target_port}»", edge_id=e.id, node_id=e.target)
            continue
        if not ports_compatible(out_p.type, in_p.type):
            add("incompatible_ports", f"выход типа «{out_p.type}» нельзя подать на вход типа «{in_p.type}»",
                edge_id=e.id, node_id=e.target)
            continue
        per_input[(e.target, e.target_port)] += 1

    for (nid, port), c in per_input.items():
        p = node_cls[nid].input_port(port)
        if p is not None and not p.multiple and c > 1:
            add("too_many_inputs", f"вход «{port}» принимает только одну связь", node_id=nid, field=port)

    if topological_order(graph) is None:
        add("cycle", "сценарий содержит цикл")

    for n in graph.nodes:
        cls = node_cls.get(n.id)
        if cls is None:
            continue
        for p in cls.inputs:
            if p.required and per_input[(n.id, p.name)] == 0:
                add("input_not_connected", f"обязательный вход «{p.name}» не подключён", node_id=n.id, field=p.name)
        for field, msg in _schema_errors(cls.config_schema, n.config):
            add("invalid_config", msg, node_id=n.id, field=field)
        for msg in cls.validate_config(n.config):
            add("invalid_config", msg, node_id=n.id)
        for field in cls.credential_fields():
            ref = n.config.get(field)
            if ref in (None, ""):
                continue
            if not isinstance(ref, str) or credential_exists is None or not credential_exists(ref):
                add("unknown_credential", f"поле «{field}»: ссылка на несуществующий секрет хранилища",
                    node_id=n.id, field=field)
        if cls.branch_outputs and not any(e.source == n.id and e.source_port in cls.branch_outputs
                                          for e in graph.edges):
            add("branch_not_connected", "ни одна ветка условия не подключена", node_id=n.id)
    return issues
