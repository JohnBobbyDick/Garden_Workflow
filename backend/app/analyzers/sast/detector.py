"""SAST detector: Spring-aware rules over the Kotlin IR (taint, call graph, security chain model)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.analyzers.common.files import ProjectFile, walk_project
from app.analyzers.common.finding import Finding, Location, dedupe_findings
from app.analyzers.common.kotlin_ast import (
    KFunction,
    KotlinFile,
    Node,
    ProjectIndex,
    first_child,
    is_string_literal,
    iter_nodes,
    named,
    node_end_line,
    node_line,
    plain_string_value,
    property_initializer,
    property_name,
)
from app.analyzers.common.masking import mask_in_text
from app.analyzers.common.severity import sast_severity
from app.analyzers.sast.callgraph import CallGraph, call_args
from app.analyzers.sast.spring_security import (
    Route,
    SecurityRule,
    collect_routes,
    collect_security_rules,
    pattern_covers,
    route_access,
    rule_matches,
)
from app.analyzers.sast.taint import Taint
from app.analyzers.secrets.rules import is_placeholder, name_semantics

ALL_RULES = ("sql-injection", "tls-verification", "credentialed-cors", "route-authorization", "object-authorization",
             "hardcoded-credentials", "unsafe-deserialization", "path-traversal", "weak-crypto",
             "missing-input-validation", "insecure-endpoint", "csrf-disabled")

CWE = {"sql-injection": "CWE-89", "tls-verification": "CWE-295", "credentialed-cors": "CWE-942",
       "route-authorization": "CWE-862", "object-authorization": "CWE-639", "hardcoded-credentials": "CWE-798",
       "unsafe-deserialization": "CWE-502", "path-traversal": "CWE-22", "weak-crypto": "CWE-327",
       "missing-input-validation": "CWE-20", "insecure-endpoint": "CWE-16", "csrf-disabled": "CWE-352"}

TITLES = {"sql-injection": "Внедрение SQL", "tls-verification": "Отключена проверка TLS",
          "credentialed-cors": "CORS с любым источником и учётными данными",
          "route-authorization": "Маршрут доступен без требуемой роли",
          "object-authorization": "Доступ к объекту без проверки владельца (IDOR)",
          "hardcoded-credentials": "Учётные данные пользователей в коде",
          "unsafe-deserialization": "Небезопасная десериализация", "path-traversal": "Обход пути (path traversal)",
          "weak-crypto": "Слабая криптография", "missing-input-validation": "Нет валидации входных данных",
          "insecure-endpoint": "Небезопасный эндпоинт или настройка", "csrf-disabled": "CSRF-защита отключена"}

REMEDIATION = {
    "sql-injection": "Использовать параметризованный запрос (`?` или именованные параметры) и передавать значение "
                     "отдельным аргументом; не встраивать данные запроса в текст SQL.",
    "tls-verification": "Удалить собственный HostnameVerifier/TrustManager и использовать стандартную проверку. Для "
                        "внутреннего УЦ добавить его сертификат в truststore.",
    "credentialed-cors": "Перечислить доверенные источники явно (`allowedOrigins = listOf(\"https://app.example\")`) "
                         "или отключить `allowCredentials`.",
    "route-authorization": "Убрать исключение `permitAll()` для служебного маршрута, чтобы сработало общее правило "
                           "с ролью, или защитить обработчик `@PreAuthorize`.",
    "object-authorization": "Проверять владельца объекта: искать запись по идентификатору и владельцу из Principal "
                            "(`WHERE id = ? AND owner_id = ?`) или сравнивать владельца после загрузки.",
    "hardcoded-credentials": "Загружать учётные записи из хранилища пользователей; пароли брать из секретов и хранить "
                             "только хеши (BCrypt/Argon2).",
    "unsafe-deserialization": "Не десериализовать недоверенные данные нативными механизмами; использовать JSON с "
                              "явными DTO, SafeConstructor для YAML или фильтр классов (ObjectInputFilter).",
    "path-traversal": "Нормализовать путь (`base.resolve(name).normalize()`) и проверять `startsWith(base)`, либо "
                      "принимать только имя файла из белого списка.",
    "weak-crypto": "Использовать SHA-256+/bcrypt/Argon2 для хешей, AES-GCM для шифрования и SecureRandom для "
                   "секретных значений.",
    "missing-input-validation": "Добавить `@Valid` к параметру `@RequestBody`, чтобы применялись ограничения DTO.",
    "insecure-endpoint": "Ограничить экспонирование эндпоинтов (`health,info`), отключить отладочные консоли и не "
                         "менять состояние в GET-обработчиках.",
    "csrf-disabled": "Не отключать CSRF при сессионной/форменной аутентификации либо перейти на stateless-токены.",
}

AUTOFIX = {"sql-injection": "llm", "tls-verification": "deterministic", "credentialed-cors": "deterministic",
           "route-authorization": "llm", "object-authorization": "llm", "hardcoded-credentials": "llm",
           "unsafe-deserialization": "llm", "path-traversal": "llm", "weak-crypto": "deterministic",
           "missing-input-validation": "deterministic", "insecure-endpoint": "deterministic",
           "csrf-disabled": "deterministic"}

DB_TYPES = {"JdbcTemplate", "NamedParameterJdbcTemplate", "JdbcOperations", "NamedParameterJdbcOperations",
            "EntityManager", "Statement", "PreparedStatement", "Connection", "JdbcClient", "DSLContext", "Session",
            "SqlSession", "DatabaseClient", "DataSource"}
DB_NAME_HINT = re.compile(r"(jdbc|template|entitymanager|^em$|stmt|statement|^conn|connection|session|^db$|dsl)", re.I)
SQL_METHODS = {"query", "queryForList", "queryForObject", "queryForMap", "queryForRowSet", "queryForStream", "update",
               "execute", "batchUpdate", "createQuery", "createNativeQuery", "executeQuery", "executeUpdate",
               "prepareStatement", "prepareCall", "addBatch", "sql", "fetch", "resultQuery"}
REPO_BY_ID = re.compile(r"^(findById|getById|getReferenceById|getOne|findOne|deleteById|findBy\w*Id|getBy\w*Id|"
                        r"loadBy\w*Id|readBy\w*Id)$")
OWNER_WORDS = re.compile(r"(owner|user|customer|tenant|account|member|client|principal|created_?by|author|patient|"
                         r"subscriber|holder)", re.I)
PER_USER_SEGMENTS = {"customer", "customers", "user", "users", "me", "my", "account", "accounts", "client", "clients",
                     "member", "members", "profile", "profiles", "tenant", "patient", "patients", "owner"}
SECURITY_PARAM_TYPES = {"Principal", "Authentication", "UserDetails", "Jwt", "OAuth2User", "OidcUser",
                        "JwtAuthenticationToken", "UsernamePasswordAuthenticationToken"}
OWNERSHIP_CALL = re.compile(r"^(check|assert|verify|ensure|require)\w*(Owner|Access|Permission|Allowed)\w*$|^(isOwner|"
                            r"canAccess|canRead|authorize\w*)$")
STATE_CHANGING = re.compile(r"^(delete|remove|update|save|insert|create|drop|reset|cancel|approve|transfer)\w*$")


@dataclass
class SastConfig:
    include: list[str] | None = None
    exclude: list[str] | None = None
    disabled_rules: list[str] = field(default_factory=list)
    min_confidence: float = 0.0
    max_file_size: int = 1_000_000


@dataclass
class Hit:
    cls: str
    rule_id: str
    file: KotlinFile | None
    path: str
    line: int
    end_line: int
    confidence: float
    detail: str
    context: str
    alternates: list[Location] = field(default_factory=list)
    unauthenticated: bool | None = None
    mask: list[str] = field(default_factory=list)
    snippet_text: str | None = None


# ------------------------------------------------------------------------------------------------- helpers


def callee_parts(call: Node) -> tuple[Node | None, str]:
    callee = named(call)[0] if named(call) else call
    if callee.type == "navigation_expression":
        parts = named(callee)
        return parts[0], parts[-1].text.decode()
    return None, callee.text.decode()


def call_line(call: Node) -> int:
    """Line of the called method's name (chained calls all start at the chain's receiver)."""
    callee = named(call)[0] if named(call) else call
    if callee.type == "navigation_expression":
        return node_line(named(callee)[-1])
    return node_line(call)


def root_identifier(node: Node) -> str | None:
    while node.type in ("navigation_expression", "call_expression") and named(node):
        node = named(node)[0]
    return node.text.decode() if node.type == "identifier" else None


def lambda_const_true(node: Node | None) -> bool:
    if node is None:
        return False
    lam = node if node.type == "lambda_literal" else next((n for n in iter_nodes(node) if n.type == "lambda_literal"), None)
    if lam is None:
        return False
    body = lam.text.decode().strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    if "->" in body:
        body = body.rsplit("->", 1)[1]
    return body.strip() == "true"


def is_expression_body(fn: KFunction) -> bool:
    body = fn.body
    return body is not None and not any(c.type == "block" for c in body.children)


def anchored_range(fn: KFunction | None, start: int, end: int) -> tuple[int, int]:
    """Expression-bodied functions are reported from the declaration line through the sink."""
    if fn is not None and is_expression_body(fn) and start - fn.name_line <= 14 and end - fn.name_line <= 14:
        start = min(start, fn.name_line)
    end = max(end, start)
    if end - start > 14:
        end = start + 14
    return start, end


def identifiers_in(node: Node) -> set[str]:
    return {n.text.decode() for n in iter_nodes(node) if n.type == "identifier"}


class Ctx:
    def __init__(self, files: list[KotlinFile]):
        self.files = files
        self.project = ProjectIndex(files)
        self.cg = CallGraph(files, self.project)
        self.routes = collect_routes(files)
        self.rules = collect_security_rules(files, self.project)
        self.enums = {c.name for kf in files for c in kf.classes()
                      if first_child(c.node, "modifiers") is not None and "enum" in first_child(c.node, "modifiers").text.decode()}
        self.taint = Taint(self.cg, self.routes, self.enums)

    def resolve(self, fn: KFunction | None, file: KotlinFile, node: Node | None) -> str | None:
        if node is None:
            return None
        r = file.resolver_for(fn, self.project).resolve(node)
        return r.value if r is not None else None

    def is_db_receiver(self, fn: KFunction, recv: Node | None) -> bool:
        if recv is None:
            return False
        text = recv.text.decode().removeprefix("this.")
        name = text.split(".")[-1]
        t = self.cg.field_type(fn, name)
        if t in DB_TYPES:
            return True
        if t is None and DB_NAME_HINT.search(name):
            return True
        if text.startswith(("DriverManager", "dataSource.connection", "connection")):
            return True
        return False

    def is_repo_receiver(self, fn: KFunction, recv: Node | None) -> bool:
        if recv is None:
            return False
        name = recv.text.decode().removeprefix("this.").split(".")[-1]
        t = self.cg.field_type(fn, name)
        if t is None:
            return False
        if self.cg.is_spring_data_repo(t):
            return True
        return t.endswith(("Repository", "Repo")) and not any(
            f.body is not None for c in self.project.classes.get(t, []) for f in c.functions)

    def accesses_data(self, fn: KFunction, depth: int = 0, seen: set | None = None) -> bool:
        seen = seen if seen is not None else set()
        if fn.node.id in seen or depth > 6:
            return False
        seen.add(fn.node.id)
        for site in self.cg.sites(fn):
            recv, method = callee_parts(site.node)
            if method in SQL_METHODS and self.is_db_receiver(fn, recv):
                return True
            if self.is_repo_receiver(fn, recv):
                return True
            if method == "find" and recv is not None and self.is_db_receiver(fn, recv):
                return True
            if any(self.accesses_data(t, depth + 1, seen) for t in site.targets):
                return True
        return False


# ------------------------------------------------------------------------------------------------- rules


def rule_sql_injection(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for fn in ctx.cg.all_functions:
        if not ctx.taint.reachable(fn) or fn.body is None:
            continue
        tainted = ctx.taint.params_of(fn)
        for call in iter_nodes(fn.body):
            if call.type != "call_expression":
                continue
            recv, method = callee_parts(call)
            if method not in SQL_METHODS or not ctx.is_db_receiver(fn, recv):
                continue
            pos, kw = call_args(call)
            sql_arg = kw.get("sql") or (pos[0] if pos else None)
            if sql_arg is None or sql_arg.type == "annotated_lambda":
                continue
            if not ctx.taint.expr_tainted(sql_arg, fn, tainted):
                continue
            start = call_line(call)
            base = root_identifier(sql_arg)
            if base is not None:
                decl = _local_decl(fn, base, start)
                if decl is not None and start - node_line(decl) <= 14:
                    start = min(start, node_line(decl))
            end = max(node_line(sql_arg), call_line(call))
            line, end = anchored_range(fn, start, end)
            hits.append(Hit("sql-injection", "SAST-SQLI", fn.file, fn.file.path, line, end, 0.9,
                            f"Данные HTTP-запроса попадают в текст SQL, передаваемый в `{method}`",
                            f"{fn.qualified}:{method}"))
    return hits


def _local_decl(fn: KFunction, name: str, before: int) -> Node | None:
    best = None
    for n in iter_nodes(fn.body):
        if n.type == "property_declaration" and property_name(n) == name and node_line(n) <= before:
            best = n
    return best


HOSTNAME_SETTERS = {"hostnameVerifier", "setHostnameVerifier", "setDefaultHostnameVerifier", "setSSLHostnameVerifier",
                    "HostnameVerifier", "sslHostnameVerifier"}
NOOP_VERIFIERS = re.compile(r"(NoopHostnameVerifier|ALLOW_ALL_HOSTNAME_VERIFIER|AllowAllHostnameVerifier|"
                            r"InsecureTrustManagerFactory|TrustAllStrategy|TrustSelfSignedStrategy)")


def rule_tls(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for kf in ctx.files:
        seen_lines: set[int] = set()
        for n in iter_nodes(kf.root):
            line = None
            if n.type == "assignment":
                left = n.child_by_field_name("left") or named(n)[0]
                right = n.child_by_field_name("right") or named(n)[-1]
                if left.text.decode().split(".")[-1] in ("hostnameVerifier", "defaultHostnameVerifier"):
                    if lambda_const_true(right) or NOOP_VERIFIERS.search(right.text.decode()) or _object_verify_true(right):
                        line = node_line(n)
            elif n.type == "call_expression":
                _, method = callee_parts(n)
                if method in HOSTNAME_SETTERS:
                    if lambda_const_true(first_child(n, "annotated_lambda")) or any(
                            lambda_const_true(a) or NOOP_VERIFIERS.search(a.text.decode()) or _object_verify_true(a)
                            for a in call_args(n)[0]):
                        line = call_line(n)
                elif method in ("loadTrustMaterial", "trustManager", "sslSocketFactory", "init"):
                    if any(NOOP_VERIFIERS.search(a.text.decode()) or lambda_const_true(a) and method == "loadTrustMaterial"
                           for a in call_args(n)[0]):
                        line = node_line(n)
            if line is not None and line not in seen_lines:
                seen_lines.add(line)
                hits.append(Hit("tls-verification", "SAST-TLS-HOSTNAME", kf, kf.path, line, line, 0.92,
                                "Проверка имени хоста/сертификата заменена на всегда успешную", f"{kf.path}:{line}"))
        # trust managers that accept every server certificate
        for cls in kf.classes():
            if not ({"X509TrustManager", "X509ExtendedTrustManager", "TrustManager"} & set(cls.supertypes)):
                continue
            for f in cls.functions:
                if f.name == "checkServerTrusted" and _empty_body(f):
                    hits.append(Hit("tls-verification", "SAST-TLS-TRUSTALL", kf, kf.path, f.name_line, f.name_line, 0.93,
                                    "TrustManager принимает любой сертификат сервера (пустой checkServerTrusted)",
                                    f"{cls.name}.checkServerTrusted"))
        for obj in kf.find_all("object_literal"):
            if "TrustManager" not in obj.text.decode().split("{", 1)[0]:
                continue
            for fd in iter_nodes(obj):
                if fd.type == "function_declaration":
                    nm = fd.child_by_field_name("name")
                    if nm is not None and nm.text.decode() == "checkServerTrusted":
                        body = first_child(fd, "function_body")
                        if body is not None and re.fullmatch(r"\{\s*\}", body.text.decode()):
                            hits.append(Hit("tls-verification", "SAST-TLS-TRUSTALL", kf, kf.path, node_line(nm),
                                            node_line(nm), 0.93, "Анонимный TrustManager принимает любой сертификат",
                                            f"{kf.path}:{node_line(nm)}"))
    return hits


def _object_verify_true(node: Node) -> bool:
    for obj in iter_nodes(node):
        if obj.type == "object_literal" and "HostnameVerifier" in obj.text.decode().split("{", 1)[0]:
            for fd in iter_nodes(obj):
                if fd.type == "function_declaration":
                    body = first_child(fd, "function_body")
                    if body is not None and re.fullmatch(r"(=\s*true|\{\s*return\s+true\s*\})", body.text.decode().strip()):
                        return True
    return False


def _empty_body(fn: KFunction) -> bool:
    body = fn.body
    if body is None:
        return False
    return bool(re.fullmatch(r"\{\s*\}|=\s*Unit", body.text.decode().strip()))


ORIGIN_SETTERS = {"allowedOrigins", "allowedOriginPatterns", "addAllowedOrigin", "addAllowedOriginPattern",
                  "setAllowedOrigins", "setAllowedOriginPatterns"}
CRED_SETTERS = {"allowCredentials", "setAllowCredentials"}


def rule_cors(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for kf in ctx.files:
        groups: dict[int, dict[str, list[int]]] = {}
        for n in iter_nodes(kf.root):
            name, value_nodes = None, []
            if n.type == "assignment":
                left = n.child_by_field_name("left") or named(n)[0]
                name = left.text.decode().split(".")[-1]
                value_nodes = [n.child_by_field_name("right") or named(n)[-1]]
            elif n.type == "call_expression":
                _, name = callee_parts(n)
                value_nodes = call_args(n)[0]
                if name in ("setHeader", "addHeader", "header") and len(value_nodes) >= 2:
                    hname = plain_string_value(value_nodes[0], kf.src) if is_string_literal(value_nodes[0]) else None
                    fn = kf.function_at(n)
                    g = groups.setdefault(_cors_scope(n, fn), {"origin": [], "cred": [], "fn": fn})
                    val = value_nodes[1]
                    if (hname or "").lower() == "access-control-allow-origin" and (
                            _has_wildcard(ctx, fn, kf, val) or re.search(r"\b(getHeader|header)\(\s*\"Origin\"", val.text.decode())
                            or val.text.decode().endswith(".origin")):
                        g["origin"].append(call_line(n))
                    elif (hname or "").lower() == "access-control-allow-credentials" and \
                            val.text.decode().strip().strip('"') == "true":
                        g["cred"].append(call_line(n))
                    continue
            if name not in ORIGIN_SETTERS and name not in CRED_SETTERS:
                continue
            fn = kf.function_at(n)
            scope = _cors_scope(n, fn)
            g = groups.setdefault(scope, {"origin": [], "cred": [], "fn": fn})
            at = call_line(n) if n.type == "call_expression" else node_line(n)
            if name in ORIGIN_SETTERS:
                if any(_has_wildcard(ctx, fn, kf, v) for v in value_nodes):
                    g["origin"].append(at)
            elif any(v.text.decode().strip() == "true" for v in value_nodes):
                g["cred"].append(at)
        ordinals: dict[str, int] = {}
        for g in groups.values():
            if g["origin"] and g["cred"]:
                lines = sorted(g["origin"] + g["cred"])
                start, end = lines[0], lines[-1]
                if end - start > 14:
                    continue
                # stable id key: enclosing function + ordinal (tree-sitter node ids are memory addresses)
                fn = g["fn"]
                qual = f"{fn.cls.name}.{fn.name}" if fn is not None and fn.cls is not None else                     (fn.name if fn is not None else "file")
                ordinals[qual] = ordinals.get(qual, 0) + 1
                hits.append(Hit("credentialed-cors", "SAST-CORS-CREDS", kf, kf.path, start, end, 0.9,
                                "Разрешён любой Origin (`*`) одновременно с передачей учётных данных",
                                f"{kf.path}:{qual}#{ordinals[qual]}"))
        for cls in kf.classes():
            for owner in [cls, *cls.functions]:
                ann = owner.annotation("CrossOrigin")
                if ann is None:
                    continue
                txt = ann.text
                if re.search(r'allowCredentials\s*=\s*"true"', txt) and re.search(r'(origins|originPatterns|value)\s*=\s*\[?\s*"\*"', txt):
                    line = node_line(ann.node)
                    hits.append(Hit("credentialed-cors", "SAST-CORS-ANNOTATION", kf, kf.path, line, line, 0.88,
                                    "@CrossOrigin разрешает любой Origin с учётными данными", f"{kf.path}:ann{line}"))
    return hits


def _cors_scope(n: Node, fn: KFunction | None) -> int:
    p = n.parent
    while p is not None:
        if p.type == "lambda_literal":
            return p.id
        if fn is not None and p.id == fn.node.id:
            return p.id
        p = p.parent
    return 0


def _has_wildcard(ctx: Ctx, fn: KFunction | None, kf: KotlinFile, node: Node) -> bool:
    for s in iter_nodes(node):
        if is_string_literal(s) and plain_string_value(s, kf.src) in ("*", "http://*", "https://*", "**"):
            return True
        if s.type == "identifier" and s.text.decode() not in ("listOf", "arrayOf", "mutableListOf", "setOf"):
            v = ctx.resolve(fn, kf, s)
            if v in ("*",):
                return True
    return False


def rule_route_authorization(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    rules = sorted(ctx.rules, key=lambda r: r.order)
    for i, rule in enumerate(rules):
        if rule.decision != "public" or rule.any_request:
            continue
        stricter = [r for r in rules[i + 1:] if r.decision in ("role", "authenticated", "denied") and not r.any_request
                    and r.file is rule.file
                    and any(pattern_covers(g, s) for g in r.patterns for s in rule.patterns)]
        if not stricter:
            continue
        routes = [rt for rt in ctx.routes if rule_matches(rule, rt)
                  and next((r for r in rules if rule_matches(r, rt)), None) is rule]
        sensitive = [rt for rt in routes if not rt.method_secured and ctx.accesses_data(rt.handler)]
        if not sensitive:
            continue
        broad = stricter[0]
        alts = [Location(path=rt.file.path, line=rt.handler.name_line,
                         end_line=min(rt.handler.end_line, rt.handler.name_line + 14)) for rt in sensitive]
        need = "роль " + ", ".join(broad.roles) if broad.roles else broad.decision_name
        hits.append(Hit("route-authorization", "SAST-ROUTE-PERMITALL", rule.file, rule.file.path, rule.line, rule.line,
                        0.88,
                        f"`permitAll()` для {', '.join(rule.patterns)} стоит раньше общего правила "
                        f"{', '.join(broad.patterns)} ({need}) и открывает обработчик с доступом к данным",
                        f"{rule.file.path}:{','.join(rule.patterns)}", alts, unauthenticated=True))
    return hits


def _uses_security_context(ctx: Ctx, fn: KFunction) -> bool:
    if fn.body is None:
        return False
    sec_params = {p.name for p in fn.params
                  if p.type_name in SECURITY_PARAM_TYPES or p.has_annotation("AuthenticationPrincipal", "CurrentSecurityContext")}
    for n in iter_nodes(fn.body):
        if n.type == "identifier" and n.text.decode() in sec_params and not _inside_logging(n, fn.body):
            return True
    text = fn.body.text.decode()
    if "SecurityContextHolder" in text:
        return True
    for site in ctx.cg.sites(fn):
        if OWNERSHIP_CALL.match(site.method):
            return True
    return False


LOG_RECEIVERS = re.compile(r"^(log|logger|LOG|LOGGER|_log|this\.log|this\.logger)$")
LOG_METHODS = {"info", "debug", "warn", "error", "trace", "println", "print", "atInfo", "atDebug"}


def _inside_logging(n: Node, stop: Node) -> bool:
    """True if the identifier only feeds a log statement (logging the principal is not an authorization check)."""
    p = n.parent
    while p is not None and p.id != stop.id:
        if p.type == "call_expression":
            recv, method = callee_parts(p)
            if method in LOG_METHODS and (recv is None or LOG_RECEIVERS.match(recv.text.decode())):
                return True
        p = p.parent
    return False


def rule_object_authorization(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    done: set[int] = set()
    for rt in ctx.routes:
        h = rt.handler
        if h.node.id in done or "{" not in rt.path or rt.method_secured:
            continue
        done.add(h.node.id)
        if any(a.name == "PostAuthorize" for a in h.annotations):
            continue
        ids = {p.name for p in h.params if p.has_annotation("PathVariable")
               and re.search(r"(^id$|Id$|_id$|Uuid$|Code$|Number$|Key$)", p.name)}
        if not ids or _uses_security_context(ctx, h):
            continue
        segments = {s.lower() for s in re.split(r"[/{}]", rt.path) if s}
        per_user_route = bool(segments & PER_USER_SEGMENTS)
        found = _track_id(ctx, h, ids, 0, set(), [])
        for fn, call, sql, chain in found:
            if any(_uses_security_context(ctx, f) for f in chain):
                continue
            if sql:
                low = sql.lower()
                where = low.split(" where ", 1)[1] if " where " in low else (low.split("where", 1)[1] if "where" in low else "")
                if OWNER_WORDS.search(re.sub(r"\b(order by|group by)\b.*", "", where)):
                    continue
                per_user_data = bool(OWNER_WORDS.search(low.split(" from ", 1)[0]))
            else:
                _, method = callee_parts(call)
                if OWNER_WORDS.search(method):
                    continue
                per_user_data = _entity_has_owner(ctx, fn, call)
            if not (per_user_route or per_user_data):
                continue
            first = node_line(call)
            last = first
            pos, kw = call_args(call)
            if sql and pos:
                last = node_end_line(pos[0]) if node_end_line(pos[0]) - first <= 14 else first
            line, end = anchored_range(fn, first, last)
            alts = []
            if fn is not h:
                hline = h.name_line
                hend = min(h.end_line, hline + 14)
                site_lines = [node_line(s.node) for s in ctx.cg.sites(h) if s.targets or s.method]
                if is_expression_body(h) and site_lines:
                    hend = min(max(site_lines), hline + 14)
                alts.append(Location(path=h.file.path, line=hline, end_line=hend))
            hits.append(Hit("object-authorization", "SAST-IDOR", fn.file, fn.file.path, line, end, 0.82,
                            f"Обработчик `{rt.path}` загружает объект по идентификатору из пути без проверки, что он "
                            f"принадлежит текущему пользователю",
                            f"{fn.qualified}:{rt.path}", alts))
    return hits


def _entity_has_owner(ctx: Ctx, fn: KFunction, call: Node) -> bool:
    recv, _ = callee_parts(call)
    if recv is None:
        return False
    t = ctx.cg.field_type(fn, recv.text.decode().removeprefix("this.").split(".")[-1])
    for c in ctx.project.classes.get(t or "", []):
        for d in iter_nodes(c.node):
            if d.type == "type_arguments":
                ent = named(d)[0].text.decode() if named(d) else ""
                for e in ctx.project.classes.get(ent, []):
                    if any(OWNER_WORDS.search(f) for f in e.constructor_fields):
                        return True
                break
    return False


CARRIER_BUILDERS = {"mapOf", "mutableMapOf", "hashMapOf", "listOf", "arrayOf", "setOf", "mutableListOf", "Pair"}


def _value_carrier(init: Node) -> bool:
    """Expressions that carry the id unchanged: plain expressions, constructors and collection/param builders.
    Results of arbitrary method calls (e.g. a loaded entity) are not the id any more."""
    if init.type != "call_expression":
        return True
    root = init
    while root.type in ("call_expression", "navigation_expression") and named(root):
        root = named(root)[0]
    name = root.text.decode() if root.type == "identifier" else ""
    return bool(name) and (name[0].isupper() or name in CARRIER_BUILDERS)


def _track_id(ctx: Ctx, fn: KFunction, tracked: set[str], depth: int, seen: set,
              chain: list[KFunction]) -> list[tuple[KFunction, Node, str | None, list[KFunction]]]:
    out: list[tuple[KFunction, Node, str | None, list[KFunction]]] = []
    if depth > 6 or fn.node.id in seen or fn.body is None:
        return out
    seen.add(fn.node.id)
    chain = chain + [fn]
    # locals derived from tracked values
    for n in iter_nodes(fn.body):
        if n.type == "property_declaration":
            init = property_initializer(n)
            nm = property_name(n)
            if init is not None and nm and identifiers_in(init) & tracked and _value_carrier(init):
                tracked = tracked | {nm}
    for site in ctx.cg.sites(fn):
        arg_hit = [a for a in site.args if identifiers_in(a) & tracked] + \
                  [a for a in site.named_args.values() if identifiers_in(a) & tracked]
        if not arg_hit:
            continue
        recv, method = callee_parts(site.node)
        if site.targets:
            for t in site.targets:
                mapping = CallGraph.map_args(site, t)
                nt = {p for p, a in mapping.items() if identifiers_in(a) & tracked}
                if nt:
                    out += _track_id(ctx, t, nt, depth + 1, seen, chain)
            continue
        if method in SQL_METHODS and ctx.is_db_receiver(fn, recv):
            pos, kw = call_args(site.node)
            sql_node = kw.get("sql") or (pos[0] if pos else None)
            if sql_node is None or identifiers_in(sql_node) & tracked:
                continue  # id concatenated into SQL is the injection rule's business
            sql = ctx.resolve(fn, fn.file, sql_node)
            if sql and re.search(r"\b(select|update|delete)\b", sql, re.I):
                out.append((fn, site.node, sql, chain))
        elif ctx.is_repo_receiver(fn, recv) and REPO_BY_ID.match(method):
            out.append((fn, site.node, None, chain))
        elif method == "find" and ctx.is_db_receiver(fn, recv):
            out.append((fn, site.node, None, chain))
    return out


def rule_hardcoded_credentials(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for kf in ctx.files:
        for call in kf.find_all("call_expression"):
            recv, method = callee_parts(call)
            if method not in ("password", "setPassword") or recv is None:
                continue
            chain = recv.text.decode()
            if not re.search(r"(withUsername|withUser|User\.builder|username\(|withDefaultPasswordEncoder|"
                             r"DataSourceBuilder|inMemoryAuthentication)", chain):
                continue
            pos, _ = call_args(call)
            if not pos or not is_string_literal(pos[0]):
                continue
            v = plain_string_value(pos[0], kf.src)
            bare = re.sub(r"^\{[a-z0-9]+\}", "", v or "")
            if not bare or is_placeholder(bare) or bare.startswith("$2"):
                continue
            line = node_line(pos[0])
            hits.append(Hit("hardcoded-credentials", "SAST-HARDCODED-USER", kf, kf.path, line, line, 0.85,
                            "Пароль пользователя приложения задан литералом в коде", f"{kf.path}:{line}",
                            mask=[v or "", bare]))
        for call in kf.find_all("call_expression"):
            recv, method = callee_parts(call)
            if method == "getConnection" and recv is not None and recv.text.decode() == "DriverManager":
                pos, _ = call_args(call)
                if len(pos) >= 3 and is_string_literal(pos[2]):
                    v = plain_string_value(pos[2], kf.src) or ""
                    if v and not is_placeholder(v):
                        line = node_line(pos[2])
                        hits.append(Hit("hardcoded-credentials", "SAST-HARDCODED-DB", kf, kf.path, line, line, 0.85,
                                        "Пароль подключения к БД задан литералом", f"{kf.path}:{line}", mask=[v]))
    return hits


def rule_unsafe_deserialization(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for kf in ctx.files:
        file_text = kf.src.decode(errors="replace")
        for call in kf.find_all("call_expression"):
            recv, method = callee_parts(call)
            line = node_line(call)
            detail = None
            if method in ("readObject", "readUnshared") and recv is not None:
                fn = kf.function_at(call)
                src = recv.text.decode()
                if recv.type == "identifier" and fn is not None and fn.body is not None:
                    d = _local_decl(fn, src, line)
                    if d is not None and property_initializer(d) is not None:
                        src = property_initializer(d).text.decode()
                    elif fn.param(src) is not None:
                        src = fn.param(src).type_name
                if re.match(r"^(ObjectInputStream|XMLDecoder)\b", src) and "ObjectInputFilter" not in file_text:
                    detail = "Нативная десериализация Java (ObjectInputStream/XMLDecoder) без фильтра классов"
            elif method in ("load", "loadAll", "loadAs") and recv is not None:
                if re.fullmatch(r"Yaml\(\s*\)", recv.text.decode()):
                    detail = "SnakeYAML без SafeConstructor создаёт произвольные объекты"
                elif recv.type == "identifier":
                    fn = kf.function_at(call)
                    d = _local_decl(fn, recv.text.decode(), line) if fn is not None and fn.body is not None else None
                    if d is not None and property_initializer(d) is not None and \
                            re.fullmatch(r"Yaml\(\s*\)", property_initializer(d).text.decode()):
                        detail = "SnakeYAML без SafeConstructor создаёт произвольные объекты"
            elif method == "fromXML" and "XStream" in file_text and not re.search(r"allowTypes|addPermission", file_text):
                detail = "XStream без белого списка типов"
            elif method in ("enableDefaultTyping", "activateDefaultTyping") and (
                    method == "enableDefaultTyping" or "LaissezFaire" in call.text.decode()):
                detail = "Jackson с полиморфной типизацией по умолчанию"
            if detail:
                hits.append(Hit("unsafe-deserialization", "SAST-DESERIALIZATION", kf, kf.path, line, line, 0.85,
                                detail, f"{kf.path}:{line}"))
    return hits


FILE_SINK_CTORS = {"File", "FileInputStream", "FileOutputStream", "FileReader", "FileWriter", "RandomAccessFile",
                   "FileSystemResource", "PrintWriter"}
FILES_METHODS = {"readString", "readAllBytes", "readAllLines", "newInputStream", "newOutputStream", "write",
                 "writeString", "delete", "deleteIfExists", "copy", "move", "lines", "newBufferedReader",
                 "newBufferedWriter", "get", "of"}


def rule_path_traversal(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for fn in ctx.cg.all_functions:
        if not ctx.taint.reachable(fn) or fn.body is None:
            continue
        body_text = fn.body.text.decode()
        if ("normalize()" in body_text and "startsWith(" in body_text) or re.search(
                r"(FilenameUtils\.getName|\.fileName\b|\.name\b.*matches|isValidFileName|sanitizeFileName)", body_text):
            continue
        tainted = ctx.taint.params_of(fn)
        for call in iter_nodes(fn.body):
            if call.type != "call_expression":
                continue
            recv, method = callee_parts(call)
            is_sink = (recv is None and method in FILE_SINK_CTORS) or (
                recv is not None and recv.text.decode() in ("Files", "Paths", "Path") and method in FILES_METHODS) or (
                recv is not None and method == "resolve" and recv.text.decode() not in ("uri", "URI"))
            if not is_sink:
                continue
            pos, _ = call_args(call)
            if any(ctx.taint.expr_tainted(a, fn, tainted) for a in pos):
                line = node_line(call)
                hits.append(Hit("path-traversal", "SAST-PATH", fn.file, fn.file.path, line, line, 0.85,
                                f"Путь к файлу строится из данных запроса без нормализации и проверки (`{method}`)",
                                f"{fn.qualified}:{line}"))
                break
    return hits


WEAK_DIGESTS = {"MD5", "MD2", "MD4", "SHA1", "SHA-1", "SHA"}
WEAK_CIPHER = re.compile(r"(^DES|DESede|TripleDES|RC4|RC2|ARCFOUR|Blowfish|/ECB/|^AES$)", re.I)
WEAK_ENCODERS = re.compile(r"\b(NoOpPasswordEncoder|Md5PasswordEncoder|ShaPasswordEncoder|StandardPasswordEncoder|"
                           r"MessageDigestPasswordEncoder|LdapShaPasswordEncoder)\b")
INSECURE_RANDOM = re.compile(r"(?<!Secure)\bRandom\(\s*\)|Math\.random\(|ThreadLocalRandom\.current\(\)|"
                             r"\bkotlin\.random\.Random\b|\bRandom\.next")


def rule_weak_crypto(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for kf in ctx.files:
        for call in kf.find_all("call_expression"):
            recv, method = callee_parts(call)
            if method != "getInstance" or recv is None:
                continue
            pos, _ = call_args(call)
            if not pos:
                continue
            fn = kf.function_at(call)
            alg = ctx.resolve(fn, kf, pos[0])
            if alg is None:
                continue
            r = recv.text.decode().split(".")[-1]
            weak = (r == "MessageDigest" and alg.upper() in WEAK_DIGESTS) or (
                r == "Cipher" and WEAK_CIPHER.search(alg)) or (r in ("KeyGenerator", "SecretKeyFactory") and
                                                               re.match(r"(DES|RC4|RC2)", alg, re.I))
            if weak:
                line = node_line(call)
                hits.append(Hit("weak-crypto", "SAST-WEAK-ALG", kf, kf.path, line, line, 0.85,
                                f"Используется слабый алгоритм `{alg}` ({r})", f"{kf.path}:{line}"))
        for n in kf.find_all("identifier"):
            if WEAK_ENCODERS.fullmatch(n.text.decode()) and n.parent is not None and n.parent.type != "import_header" \
                    and "import" not in kf.line_text(node_line(n)):
                line = node_line(n)
                hits.append(Hit("weak-crypto", "SAST-WEAK-PWD-ENCODER", kf, kf.path, line, line, 0.85,
                                f"Слабый кодировщик паролей `{n.text.decode()}`", f"{kf.path}:enc{line}"))
        for prop in kf.find_all("property_declaration"):
            nm = property_name(prop) or ""
            init = property_initializer(prop)
            if init is None:
                continue
            sem = name_semantics(nm) or (re.search(r"(nonce|salt|otp|session|csrf|reset|secret|token)", nm, re.I) and "x")
            if sem and INSECURE_RANDOM.search(init.text.decode()):
                line = node_line(prop)
                hits.append(Hit("weak-crypto", "SAST-INSECURE-RANDOM", kf, kf.path, line, line, 0.8,
                                f"Секретное значение `{nm}` генерируется предсказуемым генератором (не SecureRandom)",
                                f"{kf.path}:rnd{line}"))
    return hits


VALIDATION_ANNOTATIONS = re.compile(r"@(field:|get:|param:)?(NotNull|NotBlank|NotEmpty|Size|Min|Max|Pattern|Email|"
                                    r"Positive|PositiveOrZero|Negative|DecimalMin|DecimalMax|Past|Future|Digits|Valid)\b")


def rule_missing_validation(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[int] = set()
    for rt in ctx.routes:
        h = rt.handler
        if h.node.id in seen:
            continue
        seen.add(h.node.id)
        if rt.controller.annotation("Validated"):
            continue
        for p in h.params:
            if not p.has_annotation("RequestBody") or p.has_annotation("Valid", "Validated"):
                continue
            for c in ctx.project.classes.get(p.type_name, []):
                if VALIDATION_ANNOTATIONS.search(c.node.text.decode()):
                    line = node_line(p.node)
                    hits.append(Hit("missing-input-validation", "SAST-NO-VALID", h.file, h.file.path, line, line, 0.8,
                                    f"DTO `{p.type_name}` содержит ограничения, но параметр без `@Valid` — они не "
                                    f"проверяются", f"{h.qualified}:{p.name}"))
                    break
    return hits


def rule_insecure_endpoint_code(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[int] = set()
    for rt in ctx.routes:
        h = rt.handler
        if h.node.id in seen or rt.methods != {"GET"}:
            continue
        seen.add(h.node.id)
        for site in ctx.cg.sites(h):
            if STATE_CHANGING.match(site.method) and site.receiver and (
                    site.targets or ctx.is_repo_receiver(h, callee_parts(site.node)[0])
                    or ctx.is_db_receiver(h, callee_parts(site.node)[0])):
                line = h.name_line
                hits.append(Hit("insecure-endpoint", "SAST-GET-STATE-CHANGE", h.file, h.file.path, line,
                                min(node_line(site.node), line + 14), 0.75,
                                f"GET-обработчик `{rt.path}` меняет состояние (`{site.method}`) — уязвим к CSRF и "
                                f"предзагрузке ссылок", f"{h.qualified}:get-state"))
                break
    return hits


def rule_csrf(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for kf in ctx.files:
        text = kf.src.decode(errors="replace")
        if "STATELESS" in text or not re.search(r"(formLogin|httpBasic|sessionManagement|rememberMe)", text):
            continue
        for call in kf.find_all("call_expression"):
            recv, method = callee_parts(call)
            t = call.text.decode()
            if (method == "disable" and recv is not None and re.search(r"csrf\(\)\s*$", recv.text.decode())) or (
                    method == "csrf" and re.search(r"\b(it\.)?disable\(\)", t)):
                line = node_line(call) if method == "csrf" else node_line(named(named(call)[0])[-1])
                hits.append(Hit("csrf-disabled", "SAST-CSRF", kf, kf.path, line, line, 0.75,
                                "CSRF-защита отключена при сессионной аутентификации", f"{kf.path}:csrf"))
                break
    return hits


INSECURE_CONFIG = [
    (re.compile(r"^management\.endpoints\.web\.exposure\.include$"), lambda v: "*" in v,
     "Экспонированы все эндпоинты Actuator (`*`)"),
    (re.compile(r"^spring\.h2\.console\.enabled$"), lambda v: v.lower() == "true", "Включена веб-консоль H2"),
    (re.compile(r"^spring\.h2\.console\.settings\.web-allow-others$"), lambda v: v.lower() == "true",
     "Консоль H2 доступна с внешних адресов"),
    (re.compile(r"^server\.error\.include-stacktrace$"), lambda v: v.lower() == "always",
     "Стек-трейсы ошибок отдаются клиенту"),
    (re.compile(r"^management\.endpoint\.env\.show-values$"), lambda v: v.lower() == "always",
     "Actuator /env показывает значения переменных"),
    (re.compile(r"^management\.security\.enabled$"), lambda v: v.lower() == "false", "Отключена защита Actuator"),
]


def _config_entries(f: ProjectFile) -> list[tuple[str, str, int]]:
    text = f.read_text()
    out: list[tuple[str, str, int]] = []
    if f.suffix == ".properties":
        for i, raw in enumerate(text.splitlines(), start=1):
            s = raw.strip()
            if not s or s.startswith(("#", "!")) or ("=" not in s and ":" not in s):
                continue
            k, _, v = s.partition("=") if "=" in s else s.partition(":")
            out.append((k.strip(), v.strip(), i))
    else:
        try:
            docs = list(yaml.compose_all(text))
        except yaml.YAMLError:
            return out

        def walk(node, path):
            if isinstance(node, yaml.MappingNode):
                for k, v in node.value:
                    walk(v, path + [str(k.value)])
            elif isinstance(node, yaml.SequenceNode):
                vals = [str(x.value) for x in node.value if isinstance(x, yaml.ScalarNode)]
                out.append((".".join(path), ",".join(vals), node.start_mark.line + 1))
            elif isinstance(node, yaml.ScalarNode):
                out.append((".".join(path), str(node.value), node.start_mark.line + 1))

        for d in docs:
            if d is not None:
                walk(d, [])
    return out


def rule_insecure_config(files: list[ProjectFile]) -> list[Hit]:
    hits: list[Hit] = []
    for f in files:
        if f.suffix not in (".properties", ".yml", ".yaml") or "/test/" in f"/{f.rel}":
            continue
        for key, value, line in _config_entries(f):
            for pat, check, detail in INSECURE_CONFIG:
                if pat.match(key) and check(value):
                    hits.append(Hit("insecure-endpoint", "SAST-CONFIG", None, f.rel, line, line, 0.85, detail,
                                    f"{f.rel}:{key}", snippet_text=f.read_text().splitlines()[line - 1]))
    return hits


# ------------------------------------------------------------------------------------------------- driver

KOTLIN_RULES = {
    "sql-injection": rule_sql_injection,
    "tls-verification": rule_tls,
    "credentialed-cors": rule_cors,
    "route-authorization": rule_route_authorization,
    "object-authorization": rule_object_authorization,
    "hardcoded-credentials": rule_hardcoded_credentials,
    "unsafe-deserialization": rule_unsafe_deserialization,
    "path-traversal": rule_path_traversal,
    "weak-crypto": rule_weak_crypto,
    "missing-input-validation": rule_missing_validation,
    "insecure-endpoint": rule_insecure_endpoint_code,
    "csrf-disabled": rule_csrf,
}


def _to_finding(h: Hit) -> Finding:
    sev, reason = sast_severity(h.cls, h.unauthenticated)
    if h.snippet_text is not None:
        snippet = h.snippet_text
    elif h.file is not None:
        snippet = h.file.snippet(h.line, h.end_line)
    else:
        snippet = ""
    if h.mask:
        snippet = mask_in_text(snippet, [m for m in h.mask if m])
    return Finding(
        category="SAST", cls=h.cls, rule_id=h.rule_id, title=TITLES[h.cls],
        description=f"{TITLES[h.cls]}: {h.detail}. Файл {h.path}, строки {h.line}–{h.end_line}.",
        remediation=REMEDIATION[h.cls], severity=sev, severity_reason=reason, confidence=round(h.confidence, 2),
        path=h.path, line=h.line, end_line=h.end_line, snippet=snippet, cwe=CWE[h.cls],
        alternate_locations=h.alternates, context_key=h.context, autofix=AUTOFIX[h.cls],  # type: ignore[arg-type]
    )


def scan_sast(root: str | Path, config: SastConfig | None = None) -> list[Finding]:
    config = config or SastConfig()
    root = Path(root)
    files = walk_project(root, config.include, config.exclude, config.max_file_size)
    kfiles = [KotlinFile.parse(f.rel, f.read_bytes()) for f in files if f.suffix == ".kt"]
    hits: list[Hit] = []
    if kfiles:
        ctx = Ctx(kfiles)
        for name, rule in KOTLIN_RULES.items():
            if name not in config.disabled_rules:
                hits.extend(rule(ctx))
    if "insecure-endpoint" not in config.disabled_rules:
        hits.extend(rule_insecure_config(files))
    findings = [_to_finding(h) for h in hits if h.confidence >= config.min_confidence]
    return dedupe_findings(findings)


__all__ = ["ALL_RULES", "SastConfig", "scan_sast", "Route", "SecurityRule", "route_access"]
