"""Kotlin secret analysis over the AST: name context, auth sinks, fallbacks and constant folding."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.analyzers.common.kotlin_ast import (
    KotlinFile,
    Node,
    ProjectIndex,
    Resolved,
    binary_operator,
    decode_string_literal,
    first_child,
    is_string_literal,
    iter_nodes,
    named,
    node_line,
    plain_string_value,
    property_initializer,
    property_name,
)
from app.analyzers.secrets.rules import (
    ENV_NAME,
    is_placeholder,
    looks_like_secret,
    name_semantics,
    strip_auth_scheme,
)


@dataclass
class Candidate:
    cls: str
    rule_id: str
    line: int
    end_line: int
    value: str
    confidence: float
    context: str
    title: str
    detail: str
    fragments: list[str] = field(default_factory=list)


_HTTP_HEADER_CONSTS = {"AUTHORIZATION": "Authorization", "PROXY_AUTHORIZATION": "Proxy-Authorization", "COOKIE": "Cookie"}
_HEADER_METHODS = {"header", "setHeader", "addHeader", "set", "add", "put", "append", "addRequestProperty",
                   "setRequestProperty", "headers"}
_AUTH_METHODS_LAST_ARG = {"setBearerAuth": "token", "bearerAuth": "token", "setBasicAuth": "password",
                          "basicAuth": "password", "withToken": "token", "bearerToken": "token", "oauthToken": "token",
                          "credentials": "password", "basic": "password"}
_AUTH_CTORS = {"UsernamePasswordCredentials": "password", "PasswordAuthentication": "password",
               "BasicAuthenticationInterceptor": "password", "UsernamePasswordAuthenticationToken": "password"}
_CONFIG_READ = re.compile(
    r"getenv|getProperty|environment|\benv\b|\benv\.|properties|props\b|settings|config|\bconf\b|secrets?\b|vault|"
    r"System\.|property\(|getString\(|getValue\(|\.get\(|dotenv|\[\s*\"", re.I)
_FALLBACK_METHODS = {"getProperty", "getOrDefault", "getenvOrDefault", "getString", "getValue", "getOrElse"}


def semantic_to_class(sem: str, in_code: bool = True) -> str:
    if sem == "password":
        return "password"
    if sem == "api-key":
        return "api-key"
    return "api-key" if in_code else "configuration-token"


class KotlinSecretAnalyzer:
    def __init__(self, kf: KotlinFile, project: ProjectIndex | None = None):
        self.kf = kf
        self.project = project
        self.out: list[Candidate] = []
        self._elvis_ids: set[int] = set()

    # ------------------------------------------------------------------------------------------------------
    def run(self) -> list[Candidate]:
        self._fallbacks()
        self._value_annotations()
        self._names()
        self._sinks()
        return self.out

    def _resolver(self, node: Node):
        return self.kf.resolver_for(self.kf.function_at(node), self.project)

    def _resolve(self, node: Node) -> Resolved | None:
        return self._resolver(node).resolve(node)

    def _string_of(self, node: Node | None) -> str | None:
        if node is None:
            return None
        if node.type == "navigation_expression":
            parts = named(node)
            if len(parts) == 2 and parts[0].text.decode() == "HttpHeaders":
                return _HTTP_HEADER_CONSTS.get(parts[1].text.decode(), parts[1].text.decode())
        r = self._resolve(node)
        return r.value if r else None

    @staticmethod
    def _args(call: Node) -> list[Node]:
        va = first_child(call, "value_arguments")
        if va is None:
            return []
        return [named(a)[-1] for a in va.children if a.type == "value_argument" and named(a)]

    # -- layer 4: fallbacks ---------------------------------------------------------------------------------
    def _add_fallback(self, value_node: Node, key_hint: str | None, var_hint: str | None, line_node: Node) -> None:
        r = self._resolve(value_node)
        if r is None:
            return
        _, value = strip_auth_scheme(r.value)
        if not looks_like_secret(value):
            return
        sem = name_semantics(key_hint or "") or name_semantics(var_hint or "")
        strong_value = len(value) >= 12 and re.search(r"\d", value) and re.search(r"[A-Za-z]", value)
        if sem is None and not strong_value:
            return
        line = min(r.literal_lines) if r.literal_lines else node_line(line_node)
        self.out.append(Candidate(
            "secret-fallback", "SEC-FALLBACK", line, line, r.value, 0.9 if sem else 0.75,
            key_hint or var_hint or f"line{line}",
            "Встроенный секрет используется по умолчанию",
            f"Если настройка «{key_hint or var_hint or 'окружения'}» не задана, используется значение, записанное в коде",
            fragments=[x for x in r.literals if x],
        ))

    def _enclosing_name(self, node: Node) -> str | None:
        p = node.parent
        while p is not None and p.type not in ("property_declaration", "assignment", "value_argument", "class_parameter"):
            if p.type in ("function_body", "class_body", "source_file"):
                return None
            p = p.parent
        if p is None:
            return None
        if p.type == "property_declaration":
            return property_name(p)
        if p.type == "assignment":
            left = p.child_by_field_name("left")
            return left.text.decode().split(".")[-1] if left is not None else None
        if p.type == "value_argument":
            ch = named(p)
            return ch[0].text.decode() if len(ch) == 2 and ch[0].type == "identifier" else None
        ident = first_child(p, "identifier")
        return ident.text.decode() if ident is not None else None

    def _key_hint(self, node: Node) -> str | None:
        """Configuration key referenced in an expression: first string literal or last navigation member."""
        for n in iter_nodes(node):
            if is_string_literal(n):
                v = plain_string_value(n, self.kf.src)
                if v:
                    return v
        if node.type == "navigation_expression":
            return named(node)[-1].text.decode()
        for n in iter_nodes(node):
            if n.type == "navigation_expression":
                return named(n)[-1].text.decode()
        return None

    def _fallbacks(self) -> None:
        for n in iter_nodes(self.kf.root):
            if n.type == "binary_expression" and binary_operator(n) == "?:":
                left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
                if left is None or right is None or not _CONFIG_READ.search(left.text.decode()):
                    continue
                self._elvis_ids.add(n.id)
                self._add_fallback(right, self._key_hint(left), self._enclosing_name(n), n)
            elif n.type == "call_expression":
                callee = named(n)[0]
                if callee.type != "navigation_expression":
                    continue
                method = named(callee)[-1].text.decode()
                args = self._args(n)
                recv_text = named(callee)[0].text.decode()
                if method in _FALLBACK_METHODS and len(args) == 2:
                    self._add_fallback(args[1], self._string_of(args[0]), self._enclosing_name(n), n)
                elif method in ("orElse", "orElseGet", "getOrElse", "ifEmpty", "ifBlank") and _CONFIG_READ.search(recv_text):
                    target = args[0] if args else None
                    if target is None:
                        lam = first_child(n, "annotated_lambda")
                        lits = [x for x in iter_nodes(lam)] if lam is not None else []
                        target = next((x for x in lits if is_string_literal(x)), None)
                    if target is not None:
                        self._add_fallback(target, self._key_hint(named(callee)[0]), self._enclosing_name(n), n)

    def _value_annotations(self) -> None:
        for ann in self.kf.find_all("annotation"):
            if "Value" not in ann.text.decode():
                continue
            for lit in iter_nodes(ann):
                if not is_string_literal(lit):
                    continue
                raw = "".join(v for _, v in decode_string_literal(lit, self.kf.src))
                text = lit.text.decode()
                m = re.search(r"\$\{([^:}]+):([^}]+)\}", raw) or re.search(r"\\?\$\{([^:}]+):([^}]+)\}", text)
                if not m:
                    continue
                key, default = m.group(1).strip(), m.group(2).strip()
                if not looks_like_secret(default):
                    continue
                sem = name_semantics(key)
                if sem is None and not (len(default) >= 12 and re.search(r"\d", default)):
                    continue
                line = node_line(lit)
                self.out.append(Candidate("secret-fallback", "SEC-FALLBACK-VALUE", line, line, default, 0.9, key,
                                          "Встроенный секрет используется по умолчанию",
                                          f"Аннотация @Value подставляет встроенное значение, если «{key}» не задано"))

    # -- layer 2/3: names -----------------------------------------------------------------------------------
    def _report_value(self, sem: str, r: Resolved, context: str, use_line: int, rule: str, conf: float,
                      via: str) -> None:
        scheme, value = strip_auth_scheme(r.value)
        if not looks_like_secret(value):
            return
        if r.fragments >= 2 or r.transformed:
            start = min(r.literal_lines) if r.literal_lines else use_line
            end = max(use_line, max(r.literal_lines) if r.literal_lines else use_line)
            if end - start > 14:
                start = end - 14
            self.out.append(Candidate("recoverable-token", rule + "-RECOVER", start, end, r.value, conf, context,
                                      "Секрет восстанавливается из фрагментов исходников",
                                      f"Значение собирается из {max(r.fragments, 1)} строковых фрагментов/преобразований "
                                      f"и используется как {via}", fragments=[x for x in r.literals if x]))
            return
        line = min(r.literal_lines) if r.literal_lines else use_line
        cls = semantic_to_class(sem)
        title = {"password": "Встроенный пароль", "api-key": "Встроенный ключ/токен API"}.get(cls, "Встроенный секрет")
        self.out.append(Candidate(cls, rule, line, line, r.value, conf, context, title,
                                  f"Строковый литерал используется как {via}", fragments=[x for x in r.literals if x]))

    def _names(self) -> None:
        for n in iter_nodes(self.kf.root):
            if n.type == "property_declaration":
                name = property_name(n)
                init = property_initializer(n)
            elif n.type == "class_parameter":
                ident = first_child(n, "identifier")
                name = ident.text.decode() if ident is not None else None
                init = property_initializer(n)
            elif n.type == "value_argument":
                ch = named(n)
                if len(ch) != 2 or ch[0].type != "identifier":
                    continue
                name, init = ch[0].text.decode(), ch[1]
            elif n.type == "assignment":
                left, init = n.child_by_field_name("left"), n.child_by_field_name("right")
                if left is None or left.type == "index_expression":
                    continue
                name = left.text.decode().split(".")[-1]
            else:
                continue
            if not name or init is None:
                continue
            if init.type == "binary_expression" and binary_operator(init) == "?:":
                continue
            sem = name_semantics(name)
            if sem is None:
                continue
            r = self._resolve(init)
            if r is None:
                continue
            self._report_value(sem, r, name, node_line(n), "SEC-NAME", 0.9, f"значение «{name}»")

    # -- sinks ---------------------------------------------------------------------------------------------
    def _sink_value(self, sem: str, value_node: Node, sink_node: Node, via: str) -> None:
        if value_node.type == "binary_expression" and binary_operator(value_node) == "?:":
            return
        r = self._resolve(value_node)
        if r is None:
            return
        self._report_value(sem, r, via, node_line(sink_node), "SEC-SINK", 0.92, via)

    def _sinks(self) -> None:
        for n in iter_nodes(self.kf.root):
            if n.type == "call_expression":
                callee = named(n)[0]
                args = self._args(n)
                if callee.type == "navigation_expression":
                    method = named(callee)[-1].text.decode()
                elif callee.type == "identifier":
                    method = callee.text.decode()
                else:
                    continue
                if method in _HEADER_METHODS and len(args) == 2:
                    hname = self._string_of(args[0])
                    sem = name_semantics(hname or "") if hname else None
                    if sem:
                        self._sink_value(sem, args[1], n, f"заголовок «{hname}»")
                elif method in _AUTH_METHODS_LAST_ARG and args:
                    self._sink_value(_AUTH_METHODS_LAST_ARG[method], args[-1], n, f"аргумент {method}()")
                elif method in _AUTH_CTORS and len(args) >= 2:
                    self._sink_value(_AUTH_CTORS[method], args[1], n, f"аргумент {method}()")
                elif callee.type == "navigation_expression" and len(args) == 1 and name_semantics(method) and \
                        not method.startswith(("get", "is", "has", "find", "load", "read", "resolve", "with", "to")):
                    sem = name_semantics(method)
                    assert sem is not None
                    self._sink_value(sem, args[0], n, f"аргумент .{method}()")
            elif n.type == "infix_expression":
                ch = named(n)
                if len(ch) == 3 and ch[1].text.decode() == "to":
                    key = self._string_of(ch[0]) if is_string_literal(ch[0]) or ch[0].type == "navigation_expression" else None
                    sem = name_semantics(key or "") if key else None
                    if sem and not ENV_NAME.match(key or ""):
                        self._sink_value(sem, ch[2], n, f"заголовок/параметр «{key}»")
            elif n.type == "assignment":
                left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
                if left is not None and right is not None and left.type == "index_expression":
                    ch = named(left)
                    key = self._string_of(ch[1]) if len(ch) == 2 else None
                    sem = name_semantics(key or "") if key else None
                    if sem:
                        self._sink_value(sem, right, n, f"заголовок/параметр «{key}»")


def is_placeholder_value(v: str) -> bool:
    return is_placeholder(v)
