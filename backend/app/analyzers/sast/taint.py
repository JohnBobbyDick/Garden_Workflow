"""Interprocedural taint analysis: request data from Spring handlers flowing through calls into sinks.

Sources: handler parameters bound from the request (`@RequestParam`, `@PathVariable`, `@RequestBody`,
`@RequestHeader`, `@CookieValue`, `@ModelAttribute` or unannotated parameters of controller methods) and
`HttpServletRequest.getParameter/getHeader/...`. Parameters of numeric/boolean/UUID/enum types cannot carry
injection payloads and are never tainted. Taint propagates through locals, templates, concatenation,
`format`, `StringBuilder`, `joinToString`, transforms on tainted receivers and through call arguments
into callee parameters (fixpoint over the call graph).
"""

from __future__ import annotations

from app.analyzers.common.kotlin_ast import (
    KFunction,
    Node,
    binary_operator,
    decode_string_literal,
    first_child,
    iter_nodes,
    named,
    node_line,
    property_initializer,
    property_name,
)
from app.analyzers.sast.callgraph import CallGraph
from app.analyzers.sast.spring_security import Route

SAFE_TYPES = {"Long", "Int", "Short", "Byte", "Double", "Float", "Boolean", "UUID", "LocalDate", "LocalDateTime",
              "Instant", "BigDecimal", "BigInteger", "Principal", "Authentication", "HttpServletResponse", "Model",
              "Pageable", "Sort", "BindingResult", "ModelMap", "RedirectAttributes", "HttpSession", "Locale",
              "ZonedDateTime", "OffsetDateTime", "Char", "UserDetails", "Jwt", "OAuth2User", "HttpServletRequest",
              "ServerHttpRequest", "WebRequest", "Errors", "UriComponentsBuilder", "HttpHeaders"}
SOURCE_ANNOTATIONS = {"RequestParam", "PathVariable", "RequestBody", "RequestHeader", "CookieValue", "ModelAttribute",
                      "MatrixVariable", "RequestPart"}
REQUEST_SOURCE_METHODS = {"getParameter", "getHeader", "getQueryString", "getParameterValues", "getCookies",
                          "getInputStream", "getReader", "getRequestURI", "getPathInfo", "getParameterMap",
                          "parameter", "header", "queryParam"}
REQUEST_SOURCE_PROPS = {"queryString", "requestURI", "pathInfo", "inputStream", "reader", "parameterMap", "cookies"}
SANITIZERS = {"toLong", "toInt", "toIntOrNull", "toLongOrNull", "toDouble", "toBoolean", "toShort", "length", "size",
              "isEmpty", "isBlank", "isNotBlank", "hashCode", "count", "matches", "equals", "contains", "startsWith",
              "endsWith", "escapeSql", "quote", "sanitize", "encode", "escape", "escapeHtml", "toUUID", "valueOf"}
PROPAGATING_METHODS = {"trim", "lowercase", "uppercase", "toLowerCase", "toUpperCase", "toString", "plus", "format",
                       "replace", "substring", "take", "drop", "removePrefix", "removeSuffix", "trimEnd", "trimStart",
                       "orEmpty", "let", "also", "apply", "run", "joinToString", "append", "concat", "padStart", "padEnd",
                       "get", "first", "firstOrNull", "last", "single", "split", "decodeToString", "readText", "orElse",
                       "getOrDefault", "getOrElse", "ifEmpty", "ifBlank", "reversed", "repeat", "filter", "map"}


class Taint:
    def __init__(self, cg: CallGraph, routes: list[Route], enums: set[str]):
        self.cg = cg
        self.routes = routes
        self.enums = enums
        self.tainted_params: dict[int, set[str]] = {}
        self.handler_ids = {r.handler.node.id for r in routes}
        self._fixpoint()

    # -- sources ------------------------------------------------------------------------------------------
    def param_taintable(self, type_name: str) -> bool:
        return type_name not in SAFE_TYPES and type_name not in self.enums

    def _handler_sources(self, fn: KFunction) -> set[str]:
        out = set()
        for p in fn.params:
            if p.has_annotation("AuthenticationPrincipal", "CurrentSecurityContext"):
                continue
            if not self.param_taintable(p.type_name):
                continue
            if p.has_annotation(*SOURCE_ANNOTATIONS) or not p.annotations:
                out.add(p.name)
        return out

    def _fixpoint(self) -> None:
        work: list[KFunction] = []
        seen_handlers = set()
        for r in self.routes:
            if r.handler.node.id in seen_handlers:
                continue
            seen_handlers.add(r.handler.node.id)
            src = self._handler_sources(r.handler)
            self.tainted_params[r.handler.node.id] = src
            work.append(r.handler)
        # functions that read the servlet request directly are entry points too
        for fn in self.cg.all_functions:
            if fn.node.id not in self.tainted_params and fn.body is not None and self._reads_request(fn):
                self.tainted_params[fn.node.id] = set()
                work.append(fn)
        iterations = 0
        while work and iterations < 5000:
            iterations += 1
            fn = work.pop()
            tainted = self.tainted_params.get(fn.node.id, set())
            for site in self.cg.sites(fn):
                for target in site.targets:
                    mapping = CallGraph.map_args(site, target)
                    new = {pname for pname, arg in mapping.items()
                           if self.param_taintable(target.param(pname).type_name if target.param(pname) else "")
                           and self.expr_tainted(arg, fn, tainted)}
                    cur = self.tainted_params.setdefault(target.node.id, set())
                    if not new <= cur:
                        cur |= new
                        work.append(target)
                    elif target.node.id not in self.tainted_params:
                        work.append(target)

    def _reads_request(self, fn: KFunction) -> bool:
        for n in iter_nodes(fn.body):
            if n.type == "navigation_expression":
                member = named(n)[-1].text.decode()
                if member in REQUEST_SOURCE_METHODS or member in REQUEST_SOURCE_PROPS:
                    recv = named(n)[0].text.decode().lower()
                    if "request" in recv or recv in ("req", "httpreq", "servletrequest"):
                        return True
        return False

    def reachable(self, fn: KFunction) -> bool:
        return fn.node.id in self.tainted_params

    def params_of(self, fn: KFunction) -> set[str]:
        return self.tainted_params.get(fn.node.id, set())

    # -- expressions --------------------------------------------------------------------------------------
    def _local_inits(self, fn: KFunction, name: str, before: int | None) -> list[Node]:
        out = []
        if fn.body is None:
            return out
        for n in iter_nodes(fn.body):
            if n.type == "property_declaration" and property_name(n) == name:
                if before is None or node_line(n) <= before:
                    init = property_initializer(n)
                    if init is not None:
                        out.append(init)
            elif n.type == "assignment":
                left = n.child_by_field_name("left")
                if left is not None and left.text.decode() == name and (before is None or node_line(n) <= before):
                    right = n.child_by_field_name("right")
                    if right is not None:
                        out.append(right)
            elif n.type == "call_expression" and (before is None or node_line(n) <= before):
                callee = named(n)[0]
                if callee.type == "navigation_expression":
                    parts = named(callee)
                    if parts[0].text.decode() == name and parts[-1].text.decode() in ("append", "add", "put", "plusAssign", "insert"):
                        out.append(n)
        return out

    def expr_tainted(self, node: Node | None, fn: KFunction, tainted: set[str], _seen: set | None = None) -> bool:
        if node is None:
            return False
        seen = _seen if _seen is not None else set()
        key = (node.id, fn.node.id)
        if key in seen:
            return False
        seen.add(key)
        t = node.type
        if t == "identifier":
            name = node.text.decode()
            if name in tainted:
                return True
            return any(self.expr_tainted(i, fn, tainted, seen) for i in self._local_inits(fn, name, node_line(node)))
        if t in ("string_literal", "multiline_string_literal"):
            for c in node.children:
                if c.type == "interpolation" and any(self.expr_tainted(x, fn, tainted, seen) for x in named(c)):
                    return True
            for kind, text in decode_string_literal(node, fn.file.src):
                if kind == "expr" and text.isidentifier():
                    if text in tainted or any(self.expr_tainted(i, fn, tainted, seen)
                                              for i in self._local_inits(fn, text, node_line(node))):
                        return True
            return False
        if t == "binary_expression":
            op = binary_operator(node)
            if op in ("+", "?:"):
                return any(self.expr_tainted(c, fn, tainted, seen) for c in named(node))
            return False
        if t in ("parenthesized_expression", "annotated_lambda", "lambda_literal", "statements", "value_argument",
                 "value_arguments", "spread_expression", "as_expression", "not_null_assertion"):
            return any(self.expr_tainted(c, fn, tainted, seen) for c in named(node))
        if t == "navigation_expression":
            parts = named(node)
            member = parts[-1].text.decode()
            recv = parts[0]
            if member in REQUEST_SOURCE_PROPS and "request" in recv.text.decode().lower():
                return True
            if member in SANITIZERS:
                return False
            return self.expr_tainted(recv, fn, tainted, seen)
        if t == "index_expression":
            return any(self.expr_tainted(c, fn, tainted, seen) for c in named(node))
        if t == "call_expression":
            callee = named(node)[0]
            va = first_child(node, "value_arguments")
            lam = first_child(node, "annotated_lambda")
            args = [c for c in ([va] if va is not None else []) + ([lam] if lam is not None else [])]
            if callee.type == "navigation_expression":
                parts = named(callee)
                method = parts[-1].text.decode()
                recv = parts[0]
                if method in REQUEST_SOURCE_METHODS and "req" in recv.text.decode().lower():
                    return True
                if method in SANITIZERS:
                    return False
                if method in PROPAGATING_METHODS:
                    return self.expr_tainted(recv, fn, tainted, seen) or any(self.expr_tainted(a, fn, tainted, seen) for a in args)
                # call into project code: tainted return if the callee returns a tainted parameter expression
                return self.expr_tainted(recv, fn, tainted, seen) and method not in ("size", "length")
            name = callee.text.decode()
            if name in SANITIZERS:
                return False
            if name in ("String", "StringBuilder", "buildString", "listOf", "arrayOf", "mutableListOf", "setOf"):
                return any(self.expr_tainted(a, fn, tainted, seen) for a in args)
            return False
        return False

    def tainted_identifiers_in(self, node: Node, fn: KFunction, tainted: set[str]) -> bool:
        return self.expr_tainted(node, fn, tainted)
