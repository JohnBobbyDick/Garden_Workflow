"""Spring model: controller routes and the SecurityFilterChain authorization rules (first match wins)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.analyzers.common.kotlin_ast import (
    Annotation,
    KClass,
    KFunction,
    KotlinFile,
    Node,
    ProjectIndex,
    first_child,
    is_string_literal,
    iter_nodes,
    named,
    node_line,
)

MAPPINGS = {"GetMapping": {"GET"}, "PostMapping": {"POST"}, "PutMapping": {"PUT"}, "DeleteMapping": {"DELETE"},
            "PatchMapping": {"PATCH"}, "RequestMapping": set()}
HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
DECISIONS = {"permitAll": "public", "anonymous": "public", "authenticated": "authenticated",
             "fullyAuthenticated": "authenticated", "rememberMe": "authenticated", "hasRole": "role",
             "hasAnyRole": "role", "hasAuthority": "role", "hasAnyAuthority": "role", "access": "role",
             "hasIpAddress": "role", "denyAll": "denied"}
MATCHERS = {"requestMatchers", "antMatchers", "mvcMatchers", "regexMatchers", "anyRequest", "dispatcherTypeMatchers"}
METHOD_SECURITY = {"PreAuthorize", "PostAuthorize", "Secured", "RolesAllowed"}


@dataclass
class Route:
    methods: set[str]
    path: str
    handler: KFunction
    controller: KClass
    file: KotlinFile

    def matches_method(self, method: str | None) -> bool:
        return method is None or not self.methods or method in self.methods

    @property
    def method_secured(self) -> bool:
        return any(a.name in METHOD_SECURITY for a in self.handler.annotations + self.controller.annotations)


@dataclass
class SecurityRule:
    order: int
    method: str | None
    patterns: list[str]
    decision: str
    decision_name: str
    line: int
    node: Node
    file: KotlinFile
    any_request: bool = False
    roles: list[str] = field(default_factory=list)


def _join(prefix: str, path: str) -> str:
    p = "/" + "/".join(x for x in (prefix.strip("/"), path.strip("/")) if x)
    return p if p != "" else "/"


def _mapping_paths(ann: Annotation) -> list[str]:
    for key in ("value", "path"):
        node = ann.named_arg(key)
        if node is not None:
            vals = [ann_str for ann_str in _strings_in(node, ann.src)]
            if vals:
                return vals
    positional = [a for a in ann.args if ann.arg_name(a) is None]
    if positional:
        vals = _strings_in(positional[0], ann.src)
        if vals:
            return vals
    return [""]


def _strings_in(node: Node, src: bytes) -> list[str]:
    from app.analyzers.common.kotlin_ast import plain_string_value

    out = []
    for n in iter_nodes(node):
        if is_string_literal(n):
            v = plain_string_value(n, src)
            if v is not None:
                out.append(v)
    return out


def _mapping_methods(ann: Annotation) -> set[str]:
    base = set(MAPPINGS.get(ann.name, set()))
    if ann.name == "RequestMapping":
        node = ann.named_arg("method")
        if node is not None:
            base |= {m for m in HTTP_METHODS if re.search(rf"\b{m}\b", node.text.decode())}
    return base


def collect_routes(files: list[KotlinFile]) -> list[Route]:
    routes: list[Route] = []
    for kf in files:
        for cls in kf.classes():
            if not cls.annotation("RestController", "Controller"):
                continue
            prefixes = [""]
            cm = cls.annotation("RequestMapping")
            if cm is not None:
                prefixes = _mapping_paths(cm)
            for fn in cls.functions:
                for ann in fn.annotations:
                    if ann.name not in MAPPINGS:
                        continue
                    for prefix in prefixes:
                        for p in _mapping_paths(ann):
                            routes.append(Route(_mapping_methods(ann), _join(prefix, p), fn, cls, kf))
    return routes


def ant_to_regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("/**", i):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "{":
            j = pattern.find("}", i)
            out.append("[^/]+")
            i = j + 1 if j > 0 else i + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "/?$")


def path_matches(pattern: str, path: str) -> bool:
    concrete = re.sub(r"\{[^}]+\}", "x1", path)
    return bool(ant_to_regex(pattern).match(concrete))


def pattern_covers(general: str, specific: str) -> bool:
    """`/api/pickup/**` covers `/api/pickup/export`."""
    return general != specific and path_matches(general, specific)


def _http_method_of(node: Node) -> str | None:
    t = node.text.decode()
    for m in HTTP_METHODS:
        if t == m or t.endswith(f".{m}"):
            return m
    return None


def collect_security_rules(files: list[KotlinFile], project: ProjectIndex | None = None) -> list[SecurityRule]:
    found: list[tuple[str, int, SecurityRule]] = []
    order = 0
    for kf in files:
        nodes = [n for n in iter_nodes(kf.root) if n.type == "call_expression"]
        for call in nodes:
            callee = named(call)[0]
            if callee.type == "navigation_expression":
                parts = named(callee)
                decision_name = parts[-1].text.decode()
                if decision_name not in DECISIONS:
                    continue
                matcher_call = parts[0]
                if matcher_call.type != "call_expression":
                    continue
                mcallee = named(matcher_call)[0]
                mname = named(mcallee)[-1].text.decode() if mcallee.type == "navigation_expression" else mcallee.text.decode()
                if mname not in MATCHERS:
                    continue
                va = first_child(matcher_call, "value_arguments")
                args = [named(a)[-1] for a in va.children if a.type == "value_argument" and named(a)] if va is not None else []
                method, patterns = None, []
                resolver = kf.resolver_for(kf.function_at(call), project)
                for a in args:
                    m = _http_method_of(a)
                    if m is not None:
                        method = m
                        continue
                    r = resolver.resolve(a)
                    if r is not None:
                        patterns.append(r.value)
                roles = []
                dva = first_child(call, "value_arguments")
                if dva is not None:
                    roles = _strings_in(dva, kf.src)
                # a chain's calls all start at the receiver: order by the decision identifier position
                found.append((kf.path, parts[-1].start_byte, SecurityRule(
                    0, method, patterns, DECISIONS[decision_name], decision_name, node_line(parts[-1]), call, kf,
                    any_request=mname == "anyRequest", roles=roles)))
            elif callee.type == "identifier" and callee.text.decode() == "authorize":
                va = first_child(call, "value_arguments")
                args = [named(a)[-1] for a in va.children if a.type == "value_argument" and named(a)] if va is not None else []
                if not args:
                    continue
                method, patterns, decision_name = None, [], None
                for a in args:
                    m = _http_method_of(a)
                    txt = a.text.decode()
                    if m is not None:
                        method = m
                    elif is_string_literal(a):
                        patterns.extend(_strings_in(a, kf.src))
                    elif txt.split("(")[0] in DECISIONS:
                        decision_name = txt.split("(")[0]
                    elif txt == "anyRequest":
                        patterns = []
                if decision_name is None:
                    continue
                found.append((kf.path, call.start_byte, SecurityRule(
                    0, method, patterns, DECISIONS[decision_name], decision_name, node_line(call), call, kf,
                    any_request=not patterns)))
    rules: list[SecurityRule] = []
    for _, _, rule in sorted(found, key=lambda x: (x[0], x[1])):
        order += 1
        rule.order = order
        rules.append(rule)
    return rules


def rule_matches(rule: SecurityRule, route: Route) -> bool:
    if rule.method is not None and not route.matches_method(rule.method):
        return False
    if rule.any_request:
        return True
    return any(path_matches(p, route.path) for p in rule.patterns)


def route_access(route: Route, rules: list[SecurityRule]) -> str:
    """public | authenticated | role | denied | unknown (no SecurityFilterChain rules)."""
    if not rules:
        return "unknown"
    for r in sorted(rules, key=lambda x: x.order):
        if rule_matches(r, route):
            return r.decision
    return "authenticated"
