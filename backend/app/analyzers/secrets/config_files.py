"""Secret detection in configuration files: YAML (key paths), .properties, .env, JSON, XML, TOML, generic text."""

from __future__ import annotations

import re

import yaml

from app.analyzers.secrets.kotlin_consts import Candidate
from app.analyzers.secrets.rules import is_placeholder, looks_like_secret, name_semantics, strip_auth_scheme

_ENV_DEFAULT = re.compile(r"\$\{([A-Za-z0-9_.\-]+):([^}]*)\}")
_GENERIC_KV = re.compile(
    r"""(?P<key>[A-Za-z_][\w.\-]*)["']?\s*(?:=|:|=>)\s*(?P<q>["'`]?)(?P<val>[^\s"'`,;]+)(?P=q)""")


def classify_config_value(key: str, value: str, line: int, in_docs: bool) -> Candidate | None:
    value = value.strip()
    if not value:
        return None
    conf_mul = 0.55 if in_docs else 1.0
    m = _ENV_DEFAULT.search(value)
    if m:
        var, default = m.group(1), m.group(2).strip()
        _, inner = strip_auth_scheme(default)
        if not looks_like_secret(inner):
            return None
        sem = name_semantics(key) or name_semantics(var)
        if sem is None and not (len(inner) >= 12 and re.search(r"\d", inner)):
            return None
        return Candidate("secret-fallback", "SEC-CONF-FALLBACK", line, line, default, 0.9 * conf_mul, key,
                         "Встроенный секрет используется по умолчанию",
                         f"Свойство «{key}» берёт значение из окружения ({var}), но содержит встроенное значение по умолчанию")
    if is_placeholder(value):
        return None
    scheme, inner = strip_auth_scheme(value)
    sem = name_semantics(key)
    if scheme and looks_like_secret(inner):
        return Candidate("configuration-token", "SEC-CONF-AUTH", line, line, value, 0.92 * conf_mul, key,
                         "Токен авторизации в конфигурации",
                         f"Свойство «{key}» содержит готовое значение заголовка авторизации ({scheme} …)")
    if sem is None or not looks_like_secret(value):
        return None
    cls = {"password": "password", "api-key": "api-key"}.get(sem, "configuration-token")
    title = {"password": "Пароль в конфигурации", "api-key": "Ключ API в конфигурации"}.get(cls, "Токен в конфигурации")
    return Candidate(cls, "SEC-CONF-NAME", line, line, value, 0.88 * conf_mul, key, title,
                     f"Свойство «{key}» хранит секрет открытым текстом")


def scan_yaml(text: str, in_docs: bool = False) -> list[Candidate]:
    out: list[Candidate] = []
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return scan_generic(text, in_docs)

    def walk(node, path: list[str]):
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                key = str(k.value) if isinstance(k, yaml.ScalarNode) else "?"
                walk(v, [*path, key])
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                walk(item, [*path, str(i)])
        elif isinstance(node, yaml.ScalarNode) and path:
            key_path = ".".join(path)
            leaf = next((p for p in reversed(path) if not p.isdigit()), path[-1])
            cand = classify_config_value(leaf, str(node.value), node.start_mark.line + 1, in_docs)
            if cand is not None:
                cand.context = key_path
                out.append(cand)

    for d in docs:
        if d is not None:
            walk(d, [])
    return out


def scan_properties(text: str, in_docs: bool = False) -> list[Candidate]:
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if line.startswith("export "):
            line = line[7:]
        m = re.match(r"^([^=:\s]+)\s*[=:]\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip().strip("'\"")
        cand = classify_config_value(key, value, i, in_docs)
        if cand is not None:
            out.append(cand)
    return out


def scan_json(text: str, in_docs: bool = False) -> list[Candidate]:
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        for m in re.finditer(r'"([^"\\]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', raw):
            cand = classify_config_value(m.group(1), m.group(2), i, in_docs)
            if cand is not None:
                out.append(cand)
    return out


def scan_xml(text: str, in_docs: bool = False) -> list[Candidate]:
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        for m in re.finditer(r"<([A-Za-z_][\w.\-:]*)[^>]*>([^<]+)</\1>", raw):
            cand = classify_config_value(m.group(1), m.group(2), i, in_docs)
            if cand is not None:
                out.append(cand)
        for m in re.finditer(r'([A-Za-z_][\w.\-:]*)\s*=\s*"([^"]*)"', raw):
            if m.group(1) in ("name", "key") or m.group(1).startswith("xmlns"):
                continue
            cand = classify_config_value(m.group(1), m.group(2), i, in_docs)
            if cand is not None:
                out.append(cand)
        nv = re.search(r'name\s*=\s*"([^"]+)"[^>]*value\s*=\s*"([^"]*)"', raw)
        if nv:
            cand = classify_config_value(nv.group(1), nv.group(2), i, in_docs)
            if cand is not None:
                out.append(cand)
    return out


def scan_generic(text: str, in_docs: bool = False) -> list[Candidate]:
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        seen: set[int] = set()
        # overlapping matches: `old: apiKey = "…"` must yield the pair (apiKey, …)
        for start in (m.start() for m in re.finditer(r"[A-Za-z_]", raw)):
            if start > 0 and (raw[start - 1].isalnum() or raw[start - 1] in "_.-"):
                continue
            m = _GENERIC_KV.match(raw, start)
            if not m or m.start("val") in seen:
                continue
            seen.add(m.start("val"))
            cand = classify_config_value(m.group("key"), m.group("val"), i, in_docs)
            if cand is not None:
                out.append(cand)
    return out
