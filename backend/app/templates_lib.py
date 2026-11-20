"""Template publishing: strip secrets/credential refs/repository URLs/chat ids into declared parameters, and the
reverse substitution when a template is used."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from app.nodes.base import NodeRegistry

PARAM_RE = re.compile(r"^\{\{param:([A-Za-z0-9_.\-]+)\}\}$")
# fields that identify a concrete repository/project even when not marked as user input
SOURCE_FIELDS = {"git_url", "path", "upload_id", "repo_url"}


def placeholder(name: str) -> str:
    return "{{param:" + name + "}}"


def _param_type(prop: dict) -> str:
    if prop.get("credential_ref"):
        return "credential"
    t = prop.get("type")
    return "array" if t == "array" else "string"


def sanitize_graph(graph: dict, registry: NodeRegistry) -> tuple[dict, list[dict]]:
    g = copy.deepcopy(graph)
    params: list[dict] = []
    for node in g.get("nodes", []):
        cls = registry.get(node.get("type", ""))
        if cls is None:
            continue
        props = cls.config_schema.get("properties", {})
        cfg = node.setdefault("config", {})
        for key, prop in props.items():
            value = cfg.get(key)
            name = f"{node['id']}.{key}"
            if isinstance(value, str) and PARAM_RE.match(value):
                continue
            if prop.get("x-widget") == "keyvalue-credential" and isinstance(value, dict):
                for hk in list(value):
                    pname = f"{name}.{hk}"
                    value[hk] = placeholder(pname)
                    params.append({"name": pname, "type": "credential", "kind": "webhook_secret", "required": True,
                                   "description": f"{prop.get('title', key)}: {hk}", "default": None})
                continue
            sensitive = prop.get("credential_ref") or prop.get("x-required-user-input") or key in SOURCE_FIELDS
            if not sensitive or value in (None, "", []):
                if prop.get("x-required-user-input") and value in (None, "", []):
                    cfg[key] = placeholder(name)
                    params.append({"name": name, "type": _param_type(prop), "kind": prop.get("x-credential-kind"),
                                   "required": True, "description": prop.get("title", key), "default": None})
                continue
            cfg[key] = placeholder(name)
            params.append({"name": name, "type": _param_type(prop), "kind": prop.get("x-credential-kind"),
                           "required": True, "description": prop.get("title", key), "default": None})
    return g, params


class TemplateParamError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def apply_parameters(graph: dict, parameters: list[dict], values: dict[str, Any],
                     credential_ok: Callable[[str], bool]) -> dict:
    g = copy.deepcopy(graph)
    declared = {p["name"]: p for p in parameters}
    errors: list[str] = []

    def resolve(v: Any) -> tuple[bool, Any]:
        m = PARAM_RE.match(v) if isinstance(v, str) else None
        if not m:
            return False, v
        name = m.group(1)
        p = declared.get(name, {"name": name, "type": "string", "required": True})
        val = values.get(name, p.get("default"))
        if val in (None, "", []):
            if p.get("required", True):
                errors.append(f"не задан параметр «{name}»")
            return True, None
        if p.get("type") == "credential" and (not isinstance(val, str) or not credential_ok(val)):
            errors.append(f"параметр «{name}»: секрет не найден в хранилище этого рабочего пространства")
        if p.get("type") == "array" and isinstance(val, str):
            val = [x.strip() for x in val.split(",") if x.strip()]
        return True, val

    for node in g.get("nodes", []):
        cfg = node.get("config", {})
        for key in list(cfg):
            v = cfg[key]
            if isinstance(v, dict):
                for hk in list(v):
                    hit, nv = resolve(v[hk])
                    if hit:
                        if nv is None:
                            del v[hk]
                        else:
                            v[hk] = nv
                continue
            hit, nv = resolve(v)
            if hit:
                if nv is None:
                    del cfg[key]
                else:
                    cfg[key] = nv
    if errors:
        raise TemplateParamError(errors)
    return g
