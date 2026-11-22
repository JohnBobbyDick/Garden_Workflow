"""AI generation of workflow graphs from natural language, and chat operations over an existing graph.

The node catalog (types, ports, config schema) comes from the live registry, every proposal is checked by the same
``engine.validator`` as manual graphs, with up to 3 repair rounds; secret values are never accepted as literals."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from app.ai.providers.base import LLMProvider
from app.ai.validator import AIFormatError, parse_json, schema_errors
from app.core.masking import Masker
from app.engine.graph import Graph
from app.engine.validator import validate_graph
from app.nodes.base import NodeRegistry

MAX_ATTEMPTS = 3

GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "type": {"type": "string"}, "config": {"type": "object"},
            "label": {"type": "string"}}, "required": ["id", "type"]}},
        "edges": {"type": "array", "items": {"type": "object", "properties": {
            "source": {"type": "string"}, "source_port": {"type": "string"}, "target": {"type": "string"},
            "target_port": {"type": "string"}}, "required": ["source", "target"]}},
    },
    "required": ["nodes", "edges"],
}

OPS_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "operations": {"type": "array", "items": {"type": "object", "properties": {
            "op": {"enum": ["add_node", "update_node", "remove_node", "connect", "disconnect", "set_schedule"]},
            "node_id": {"type": "string"}, "type": {"type": "string"}, "config": {"type": "object"},
            "label": {"type": "string"}, "source": {"type": "string"}, "source_port": {"type": "string"},
            "target": {"type": "string"}, "target_port": {"type": "string"}, "cron": {"type": "string"}},
            "required": ["op"]}},
    },
    "required": ["operations"],
}

RULES = """Правила графа:
- ровно один триггер (category=trigger) в начале; рёбра соединяют выход (source_port) с входом (target_port);
- тип выхода должен совпадать с типом входа или один из них — any; вход без multiple принимает одну связь;
- без циклов; у logic.if_else подключите хотя бы одну ветку (true/false);
- в config возвращайте только конкретные JSON-значения из config_fields выбранного типа ноды.
  Пропускайте поля с подходящим default и неизвестные параметры подключения. Для SMTP без реквизитов верните config: {}.
- пропускайте поля с credential_ref — пользователь выберет секрет из хранилища;
  для SMTP это только password; host, username, from_addr и to вводятся в настройках ноды;
  для Telegram это только bot_token; chat_id задаёт пользователь. В update_node указывайте только изменяемые поля;
  никогда не пишите значения секретов, chat_id, адреса почты или URL репозиториев, которых нет в запросе;
- расписание — cron из 5 полей (например «0 14 * * *» — каждый день в 14:00);
- source.repo по умолчанию mode=project; несколько сканеров объединяйте через logic.merge;
- готовый отчёт передавайте из output.report_export.out на вход in выбранной ноды уведомления;
  notify.telegram отправляет сводку и report.md при send_document=true (по умолчанию);
- в шаблонах уведомлений используйте {{findings.count}}, {{score.value}}, {{score.delta}}, {{ai.summary}}, {{run.url}};
  ссылки вида {{имя_ноды.out.поле}} не поддерживаются. Если нужна оценка, подключите выход оценки к уведомлению;
- условие IF пишите на языке выражений: findings.count, severity.max, category, new_findings.count, verdict, score.value,
  score.delta, сравнения и and/or/not, например «severity.max >= HIGH»."""


def catalog_for_prompt(registry: NodeRegistry) -> list[dict]:
    out = []
    for cls in registry.all():
        props = cls.config_schema.get("properties", {})
        cfg = {}
        for k, p in props.items():
            item = {"type": p.get("type")}
            for key in ("enum", "default"):
                if key in p:
                    item[key] = p[key]
            if p.get("credential_ref"):
                item["credential_ref"] = True
            item["title"] = p.get("title", k)
            cfg[k] = item
        out.append({"type": cls.type, "category": cls.category, "title": cls.title["ru"],
                    "description": cls.description["ru"],
                    "inputs": [{"name": p.name, "type": p.type, "required": p.required, "multiple": p.multiple}
                               for p in cls.inputs],
                    "outputs": [{"name": p.name, "type": p.type} for p in cls.outputs],
                    "branch_outputs": list(cls.branch_outputs), "config_fields": cfg,
                    "required_config": cls.config_schema.get("required", [])})
    return out


def system_prompt(registry: NodeRegistry, task: str) -> str:
    return (f"Ты проектируешь сценарии (workflow) платформы AI Security Workflow. {task}\n\n{RULES}\n\n"
            "Каталог доступных нод (JSON):\n" + json.dumps(catalog_for_prompt(registry), ensure_ascii=False))


@dataclass
class GenResult:
    graph: dict
    issues: list[dict]
    needs_input: list[dict]
    attempts: int
    valid: bool
    usage: dict[str, int] = field(default_factory=dict)


def _config_values(node_type: str, config: dict, registry: NodeRegistry, existing: dict | None = None) -> dict:
    """Merge concrete AI values and retain only fields supported by the destination node."""
    cls = registry.get(node_type)
    schema = cls.config_schema if cls else {}
    properties = schema.get("properties", {})
    values = dict(existing or {})
    for key, value in config.items():
        prop = properties.get(key, {})
        # Models often express omitted connection details as empty values in a repair.
        if (key in schema.get("required", ()) and (prop.get("credential_ref") or prop.get("x-required-user-input"))
                and value in (None, "", []) and values.get(key)):
            continue
        if (isinstance(value, dict) and "type" in value and value["type"] == prop.get("type")
                and prop.get("type") in ("string", "integer", "number", "boolean", "array")
                and value.keys() <= {"type", "title", "default", "enum", "credential_ref"}):
            continue
        values[key] = value
    if schema.get("additionalProperties") is False:
        return {key: value for key, value in values.items() if key in properties}
    return values


def normalize_graph(raw: dict, registry: NodeRegistry) -> dict:
    nodes, edges = [], []
    for i, n in enumerate(raw.get("nodes", [])):
        nodes.append({"id": str(n.get("id") or f"n{i + 1}")[:64], "type": str(n.get("type", "")),
                      "position": n.get("position") or {"x": 0, "y": 0},
                      "config": _config_values(n.get("type", ""), n.get("config") or {}, registry),
                      **({"label": n["label"]} if n.get("label") else {})})
    for i, e in enumerate(raw.get("edges", [])):
        edges.append({"id": str(e.get("id") or f"e{i + 1}")[:64], "source": str(e.get("source")),
                      "source_port": str(e.get("source_port") or "out"), "target": str(e.get("target")),
                      "target_port": str(e.get("target_port") or "in")})
    return {"schema_version": 1, "nodes": nodes, "edges": edges}


def strip_secrets(graph: dict, registry: NodeRegistry, credential_exists: Callable[[str], bool]) -> list[dict]:
    """Credential fields may only reference existing vault items; literals are removed. Returns needs-input list."""
    needs: list[dict] = []
    probe = Masker()
    for node in graph["nodes"]:
        cls = registry.get(node["type"])
        if cls is None:
            continue
        cfg = node["config"]
        for key, prop in cls.config_schema.get("properties", {}).items():
            value = cfg.get(key)
            if prop.get("credential_ref"):
                if value and not (isinstance(value, str) and credential_exists(value)):
                    cfg.pop(key, None)
                if not cfg.get(key):
                    needs.append({"node_id": node["id"], "field": key, "title": prop.get("title", key), "kind": "credential"})
            elif prop.get("x-required-user-input") and value in (None, "", []):
                needs.append({"node_id": node["id"], "field": key, "title": prop.get("title", key), "kind": "value"})
            elif isinstance(value, str) and probe.mask(value) != value:
                cfg.pop(key, None)  # a token-shaped literal in a plain field is not accepted either
                needs.append({"node_id": node["id"], "field": key, "title": prop.get("title", key), "kind": "value"})
    return needs


def blocking_issues(graph: dict, registry: NodeRegistry, credential_exists: Callable[[str], bool],
                    needs: list[dict]) -> tuple[list[dict], list[dict]]:
    """All validator issues, and those that block (missing user-only values are expected and not blocking)."""
    try:
        g = Graph.model_validate(graph)
    except ValueError as exc:
        issue = {"code": "invalid_graph_format", "message": str(exc)[:500], "node_id": None, "field": None}
        return [issue], [issue]
    issues = [i.model_dump() for i in validate_graph(g, registry, credential_exists)]
    waived = {(n["node_id"], n["field"]) for n in needs}
    blocking = [i for i in issues if not (i["code"] in ("invalid_config", "unknown_credential")
                                          and (i["node_id"], i["field"]) in waived)]
    return issues, blocking


def _register_model_credentials(data: dict, registry: NodeRegistry, credential_exists: Callable[[str], bool],
                                masker: Masker) -> None:
    fields = {name for cls in registry.all() for name, prop in cls.config_schema.get("properties", {}).items()
              if prop.get("credential_ref")}
    for collection in ("nodes", "operations"):
        entries = data.get(collection)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            config = entry.get("config") if isinstance(entry, dict) else None
            if isinstance(config, dict):
                for key in fields.intersection(config):
                    value = config[key]
                    if isinstance(value, str) and value and not credential_exists(value):
                        masker.register(value)


async def _ask(provider: LLMProvider, messages: list[dict], schema: dict, usage: dict, masker: Masker,
               registry: NodeRegistry, credential_exists: Callable[[str], bool]) -> dict:
    res = await provider.chat([{"role": m["role"], "content": masker.mask(m["content"])} for m in messages],
                              response_schema=schema, temperature=0.1, max_tokens=4096)
    for k, v in res.usage.items():
        usage[k] = usage.get(k, 0) + v
    data = parse_json(res.content)
    _register_model_credentials(data, registry, credential_exists, masker)
    errs = schema_errors(data, schema)
    if errs:
        raise AIFormatError(masker.mask("; ".join(errs[:5])))
    return data


async def generate_graph(provider: LLMProvider, prompt: str, registry: NodeRegistry,
                         credential_exists: Callable[[str], bool], masker: Masker) -> GenResult:
    messages = [{"role": "system", "content": system_prompt(
                    registry, "Построй граф по описанию пользователя и верни JSON {nodes, edges}.")},
                {"role": "user", "content": f"Описание сценария: {prompt}"}]
    usage: dict[str, int] = {}
    graph: dict = {"schema_version": 1, "nodes": [], "edges": []}
    issues: list[dict] = []
    needs: list[dict] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = await _ask(provider, messages, GRAPH_SCHEMA, usage, masker, registry, credential_exists)
        except AIFormatError as exc:
            issues = [{"code": "invalid_json", "message": str(exc), "node_id": None, "field": None}]
            messages += [{"role": "user", "content": f"Ответ не прошёл проверку формата: {exc}. Верни JSON {{nodes, edges}}."}]
            continue
        graph = normalize_graph(raw, registry)
        needs = strip_secrets(graph, registry, credential_exists)
        issues, blocking = blocking_issues(graph, registry, credential_exists, needs)
        if not blocking:
            return GenResult(graph, issues, needs, attempt, True, usage)
        messages += [{"role": "assistant", "content": json.dumps(masker.mask_obj(raw), ensure_ascii=False)[:6000]},
                     {"role": "user", "content": "Граф не прошёл проверку валидатора, исправь и верни весь граф целиком:\n"
                                                 + "\n".join(f"- [{i['code']}] node={i['node_id']}: {i['message']}"
                                                             for i in blocking)}]
    return GenResult(graph, issues, needs, MAX_ATTEMPTS, False, usage)


class OpError(ValueError):
    pass


def apply_operations(graph: dict, ops: list[dict], registry: NodeRegistry) -> dict:
    g = copy.deepcopy(graph)
    nodes = {n["id"]: n for n in g["nodes"]}
    for op in ops:
        kind = op.get("op")
        if kind == "add_node":
            nid = op.get("node_id") or f"{(op.get('type') or 'node').split('.')[-1]}_{len(nodes) + 1}"
            if nid in nodes:
                raise OpError(f"нода {nid} уже существует")
            if registry.get(op.get("type", "")) is None:
                raise OpError(f"неизвестный тип ноды {op.get('type')}")
            node = {"id": nid, "type": op["type"], "position": {"x": 0, "y": 0},
                    "config": _config_values(op["type"], op.get("config") or {}, registry)}
            if op.get("label"):
                node["label"] = op["label"]
            g["nodes"].append(node)
            nodes[nid] = node
        elif kind == "update_node":
            node = nodes.get(op.get("node_id", ""))
            if node is None:
                raise OpError(f"нода {op.get('node_id')} не найдена")
            if op.get("type"):
                node["type"] = op["type"]
            node["config"] = _config_values(node["type"], op.get("config") or {}, registry, node.get("config"))
            if op.get("label"):
                node["label"] = op["label"]
        elif kind == "remove_node":
            nid = op.get("node_id", "")
            if nid not in nodes:
                raise OpError(f"нода {nid} не найдена")
            g["nodes"] = [n for n in g["nodes"] if n["id"] != nid]
            g["edges"] = [e for e in g["edges"] if nid not in (e["source"], e["target"])]
            nodes.pop(nid)
        elif kind == "connect":
            e = {"id": f"e_{op.get('source')}_{op.get('target')}_{len(g['edges']) + 1}", "source": op.get("source"),
                 "source_port": op.get("source_port") or "out", "target": op.get("target"),
                 "target_port": op.get("target_port") or "in"}
            g["edges"].append(e)
        elif kind == "disconnect":
            g["edges"] = [e for e in g["edges"] if not (e["source"] == op.get("source") and e["target"] == op.get("target")
                                                        and (not op.get("source_port") or e["source_port"] == op["source_port"])
                                                        and (not op.get("target_port") or e["target_port"] == op["target_port"]))]
        elif kind == "set_schedule":
            trig = next((n for n in g["nodes"] if n["type"] == "trigger.schedule"), None) or \
                next((n for n in g["nodes"] if registry.get(n["type"]) and registry.get(n["type"]).category == "trigger"), None)
            if trig is None:
                raise OpError("в сценарии нет триггера")
            trig["type"] = "trigger.schedule"
            trig["config"] = {"cron": op.get("cron") or "0 14 * * *"}
        else:
            raise OpError(f"неизвестная операция {kind}")
    return g


def graph_diff(old: dict, new: dict) -> dict:
    on = {n["id"]: n for n in old.get("nodes", [])}
    nn = {n["id"]: n for n in new.get("nodes", [])}
    key = lambda e: (e["source"], e.get("source_port"), e["target"], e.get("target_port"))  # noqa: E731
    oe = {key(e) for e in old.get("edges", [])}
    ne = {key(e) for e in new.get("edges", [])}
    return {"added_nodes": [i for i in nn if i not in on], "removed_nodes": [i for i in on if i not in nn],
            "changed_nodes": [i for i in nn if i in on and (nn[i].get("config") != on[i].get("config")
                                                           or nn[i]["type"] != on[i]["type"] or nn[i].get("label") != on[i].get("label"))],
            "added_edges": [list(k) for k in ne - oe], "removed_edges": [list(k) for k in oe - ne]}


async def propose_operations(provider: LLMProvider, graph: dict, message: str, registry: NodeRegistry,
                             credential_exists: Callable[[str], bool], masker: Masker, *,
                             selected_node_id: str | None = None, history: list[dict] | None = None
                             ) -> tuple[GenResult, list, str]:
    usage: dict[str, int] = {}
    context = {
        "nodes": [{k: n[k] for k in ("id", "type", "config", "label", "disabled") if k in n}
                  for n in graph.get("nodes", [])],
        "edges": graph.get("edges", []),
        "selected_node_id": selected_node_id,
        "history": [{"role": m["role"], "status": m["status"], "content": masker.mask(m["content"])[:1200]}
                    for m in (history or [])[-6:]],
    }
    messages = [{"role": "system", "content": system_prompt(
                    registry, "Пользователь редактирует существующий сценарий. Верни JSON {explanation, operations}: "
                              "список операций add_node, update_node, remove_node, connect, disconnect, set_schedule. "
                              "«Эта нода» означает selected_node_id. История помогает понять уточнения. "
                              "Состояние графа определяют nodes и edges. Выполни только последний запрос.")},
                {"role": "user", "content": "Текущий граф (JSON):\n"
                                            + json.dumps(context, ensure_ascii=False)
                                            + f"\n\nЗапрос: {message}"}]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        data = None
        try:
            data = await _ask(provider, messages, OPS_SCHEMA, usage, masker, registry, credential_exists)
            ops = data["operations"]
            candidate = apply_operations(graph, ops, registry)
            needs = strip_secrets(candidate, registry, credential_exists)
            issues, blocking = blocking_issues(candidate, registry, credential_exists, needs)
            if not blocking:
                if not any(graph_diff(graph, candidate).values()):
                    raise OpError("операции не изменяют граф")
                return GenResult(candidate, issues, needs, attempt, True, usage), ops, data.get("explanation", "")
        except (AIFormatError, OpError) as exc:
            blocking = [{"code": "invalid_json" if isinstance(exc, AIFormatError) else "bad_operation",
                         "message": masker.mask(str(exc)), "node_id": None, "field": None}]
        feedback = json.dumps(masker.mask_obj(blocking), ensure_ascii=False)
        if attempt < MAX_ATTEMPTS:
            if data is not None:
                messages.append({"role": "assistant", "content": json.dumps(masker.mask_obj(data), ensure_ascii=False)[:6000]})
            messages.append({"role": "user", "content": "Исправь ошибки и верни весь список операций для исходного графа.\n"
                                                         + feedback[:3000]})
    return (GenResult(graph, blocking, [], MAX_ATTEMPTS, False, usage), [],
            "Не удалось подготовить применимые изменения за три попытки.")
