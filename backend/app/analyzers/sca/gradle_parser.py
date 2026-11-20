"""Gradle build file parser.

Kotlin DSL (`*.gradle.kts`) is parsed with tree-sitter-kotlin; only calls inside `dependencies { }` blocks are
treated as declarations. Supported forms: `conf("g:a:v")`, `conf("g:a:$v")`, `add("conf", "g:a:v")`
(multi-line, trailing comma), `conf(group = .., name = .., version = ..)`, `platform(..)`/`enforcedPlatform(..)`,
`kotlin("x")`, `libs.<alias>` (version catalog). Versions are resolved from file-level `val`, `extra[..]`,
`val x: String by project`, `providers.gradleProperty(..)`, `project.property(..)`/`findProperty(..)` and
`gradle.properties`. Groovy `build.gradle` gets regex-based basic support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.common.files import safe_file
from app.analyzers.common.finding import Location
from app.analyzers.common.kotlin_ast import (
    KotlinFile,
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
from app.analyzers.sca.gradle_props import read_properties
from app.analyzers.sca.version_catalog import VersionCatalog, load_catalog

TEST_CONFIG_HINT = ("test", "Test")
KNOWN_CONFIGS = {
    "implementation", "api", "compileOnly", "runtimeOnly", "compile", "runtime", "testImplementation",
    "testCompileOnly", "testRuntimeOnly", "androidTestImplementation", "kapt", "ksp", "annotationProcessor",
    "developmentOnly", "compileOnlyApi", "testFixturesImplementation", "testFixturesApi",
    "integrationTestImplementation",
}
_CONFIG_SUFFIX = re.compile(r"^[a-z][A-Za-z0-9]*(Implementation|Api|CompileOnly|RuntimeOnly|AnnotationProcessor)$")
_PLATFORM = {"platform", "enforcedPlatform"}


def is_configuration(name: str) -> bool:
    return name in KNOWN_CONFIGS or bool(_CONFIG_SUFFIX.match(name))


@dataclass
class Dependency:
    group: str
    artifact: str
    declared_version: str | None
    configuration: str
    path: str
    line: int
    end_line: int
    version_source: str = "literal"
    alternate_locations: list[Location] = field(default_factory=list)
    is_platform: bool = False

    @property
    def is_test(self) -> bool:
        return self.configuration.startswith("test") or "Test" in self.configuration


@dataclass
class _Val:
    value: str
    alts: list[Location] = field(default_factory=list)
    source: str = "literal"


class _KtsEvaluator:
    def __init__(self, kf: KotlinFile, rel: str, props: dict[str, tuple[str, int]], props_rel: str):
        self.kf = kf
        self.rel = rel
        self.props = props
        self.props_rel = props_rel
        self.extra: dict[str, tuple[Node, int]] = {}
        for n in iter_nodes(kf.root):
            if n.type == "assignment":
                left = n.child_by_field_name("left")
                right = n.child_by_field_name("right")
                key = self._index_key(left)
                if key is not None and right is not None:
                    self.extra[key] = (right, node_line(n))
            elif n.type == "call_expression":
                callee = named(n)[0]
                if callee.type == "navigation_expression" and callee.text.decode().endswith(("extra.set", "ext.set")):
                    args = self._args(n)
                    if len(args) == 2:
                        k = self._plain(args[0])
                        if k:
                            self.extra[k] = (args[1], node_line(n))

    @staticmethod
    def _args(call: Node) -> list[Node]:
        va = first_child(call, "value_arguments")
        if va is None:
            return []
        return [named(a)[-1] for a in va.children if a.type == "value_argument" and named(a)]

    def _plain(self, node: Node | None) -> str | None:
        if node is None or node.type not in ("string_literal", "multiline_string_literal"):
            return None
        parts = decode_string_literal(node, self.kf.src)
        if any(k == "expr" for k, _ in parts):
            return None
        return "".join(v for _, v in parts)

    def _index_key(self, node: Node | None) -> str | None:
        if node is None or node.type != "index_expression":
            return None
        ch = named(node)
        if len(ch) == 2 and ch[0].text.decode() in ("extra", "ext", "rootProject.extra", "project.extra"):
            return self._plain(ch[1])
        return None

    def _prop(self, key: str, source: str) -> _Val | None:
        if key in self.props:
            v, line = self.props[key]
            return _Val(v, [Location(path=self.props_rel, line=line, end_line=line)], f"{source}:{key}")
        return None

    def _top_decl(self, name: str) -> Node | None:
        for p in self.kf.top_level_properties():
            if property_name(p) == name:
                return p
        for n in iter_nodes(self.kf.root):
            if n.type == "property_declaration" and property_name(n) == name:
                return n
        return None

    def evaluate_name(self, name: str, depth: int) -> _Val | None:
        decl = self._top_decl(name)
        if decl is None:
            return self._prop(name, "gradle.properties")
        line = node_line(decl)
        delegate = first_child(decl, "property_delegate")
        if delegate is not None:
            dtext = delegate.text.decode()
            if "project" in dtext or "extra" in dtext or "settings" in dtext:
                v = self._prop(name, "gradle.properties")
                if v is not None:
                    v.alts.insert(0, Location(path=self.rel, line=line, end_line=line))
                return v
            return None
        init = property_initializer(decl)
        v = self.evaluate(init, depth + 1)
        if v is None:
            return None
        v.alts.insert(0, Location(path=self.rel, line=line, end_line=line))
        if v.source == "literal":
            v.source = f"variable:{name}"
        return v

    def evaluate(self, node: Node | None, depth: int = 0) -> _Val | None:
        if node is None or depth > 10:
            return None
        t = node.type
        if t in ("string_literal", "multiline_string_literal"):
            parts = decode_string_literal(node, self.kf.src)
            interps = [c for c in node.children if c.type == "interpolation"]
            out, alts, source, ii = [], [], "literal", 0
            for kind, text in parts:
                if kind == "text":
                    out.append(text)
                    continue
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
                    sub = self.evaluate_name(text, depth + 1)
                    if ii < len(interps) and interps[ii].text.decode().strip("${} ") == text:
                        ii += 1
                else:
                    sub = self.evaluate(named(interps[ii])[0], depth + 1) if ii < len(interps) and named(interps[ii]) else None
                    ii += 1
                if sub is None:
                    return None
                out.append(sub.value)
                alts.extend(sub.alts)
                source = sub.source
            return _Val("".join(out), alts, source)
        if t == "identifier":
            return self.evaluate_name(node.text.decode(), depth + 1)
        if t == "parenthesized_expression":
            ch = named(node)
            return self.evaluate(ch[0], depth + 1) if ch else None
        if t == "index_expression":
            key = self._index_key(node)
            if key is None:
                return None
            if key in self.extra:
                right, line = self.extra[key]
                v = self.evaluate(right, depth + 1)
                if v is not None:
                    v.alts.insert(0, Location(path=self.rel, line=line, end_line=line))
                    v.source = f"extra:{key}"
                return v
            return self._prop(key, "gradle.properties")
        if t == "binary_expression" and binary_operator(node) == "+":
            a = self.evaluate(node.child_by_field_name("left"), depth + 1)
            b = self.evaluate(node.child_by_field_name("right"), depth + 1)
            if a is None or b is None:
                return None
            return _Val(a.value + b.value, a.alts + b.alts, b.source if b.source != "literal" else a.source)
        if t in ("navigation_expression", "call_expression"):
            return self._eval_property_call(node, depth)
        return None

    def _eval_property_call(self, node: Node, depth: int) -> _Val | None:
        text = node.text.decode()
        m = re.search(r"(?:gradleProperty|property|findProperty|getProperty)\(\s*\"([^\"]+)\"\s*\)", text)
        if m and ("providers" in text or "property(" in text.lower()):
            return self._prop(m.group(1), "gradle.properties")
        # `x.get()`, `x.orNull`, `x.toString()` around a resolvable identifier
        if node.type == "navigation_expression":
            ch = named(node)
            if len(ch) == 2 and ch[1].text.decode() in ("orNull", "get"):
                return self.evaluate(ch[0], depth + 1)
        if node.type == "call_expression":
            callee = named(node)[0]
            if callee.type == "navigation_expression":
                ch = named(callee)
                if len(ch) == 2 and ch[1].text.decode() in ("get", "toString", "orNull"):
                    return self.evaluate(ch[0], depth + 1)
        return None


def _split_coords(s: str) -> tuple[str, str, str | None] | None:
    parts = s.split(":")
    if len(parts) < 2 or not parts[0] or not parts[1] or any(" " in p for p in parts):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", parts[0]) or not re.fullmatch(r"[A-Za-z0-9_.\-]+", parts[1]):
        return None
    version = parts[2] if len(parts) >= 3 and parts[2] else None
    if version and "@" in version:
        version = version.split("@", 1)[0]
    return parts[0], parts[1], version


def _dependency_blocks(kf: KotlinFile) -> list[Node]:
    blocks = []
    for n in iter_nodes(kf.root):
        if n.type == "call_expression":
            callee = named(n)[0]
            if callee.type == "identifier" and callee.text.decode() == "dependencies":
                lam = first_child(n, "annotated_lambda")
                if lam is not None:
                    blocks.append(lam)
    return blocks


def _parse_kts(root: Path, rel: str, catalog: VersionCatalog | None) -> list[Dependency]:
    path = safe_file(root, rel)
    if path is None:
        return []
    kf = KotlinFile.parse(rel, path.read_bytes())
    module_dir = Path(rel).parent
    props_rel_candidates = [module_dir / "gradle.properties", Path("gradle.properties")]
    props: dict[str, tuple[str, int]] = {}
    props_rel = "gradle.properties"
    for cand in reversed(props_rel_candidates):
        p = read_properties(safe_file(root, cand))
        if p:
            props.update(p)
            props_rel = str(cand).replace("\\", "/")
    ev = _KtsEvaluator(kf, rel, props, props_rel)
    deps: list[Dependency] = []
    seen: set[int] = set()
    for block in _dependency_blocks(kf):
        for call in iter_nodes(block):
            if call.type != "call_expression" or call.id in seen:
                continue
            callee = named(call)[0]
            if callee.type != "identifier":
                continue
            name = callee.text.decode()
            args = ev._args(call)
            if name == "add" and len(args) >= 2:
                conf = ev._plain(args[0])
                if conf is None:
                    continue
                dep_args, named_args = args[1:2], {}
            elif is_configuration(name):
                conf = name
                dep_args, named_args = args, _named_args(call)
            else:
                continue
            seen.add(call.id)
            for inner in iter_nodes(call):
                if inner.type == "call_expression" and inner is not call:
                    seen.add(inner.id)
            dep = _dependency_from_args(ev, kf, rel, conf, call, dep_args, named_args, catalog)
            if dep is not None:
                deps.append(dep)
    return deps


def _named_args(call: Node) -> dict[str, Node]:
    out: dict[str, Node] = {}
    va = first_child(call, "value_arguments")
    for a in va.children if va is not None else []:
        if a.type == "value_argument":
            ch = named(a)
            if len(ch) == 2 and ch[0].type == "identifier":
                out[ch[0].text.decode()] = ch[1]
    return out


def _dependency_from_args(ev: _KtsEvaluator, kf: KotlinFile, rel: str, conf: str, call: Node, args: list[Node],
                          named_args: dict[str, Node], catalog: VersionCatalog | None) -> Dependency | None:
    line, end_line = node_line(call), call.end_point[0] + 1
    if {"group", "name"} <= named_args.keys():
        g, a = ev.evaluate(named_args["group"]), ev.evaluate(named_args["name"])
        if g is None or a is None:
            return None
        v = ev.evaluate(named_args["version"]) if "version" in named_args else None
        return Dependency(g.value, a.value, v.value if v else None, conf, rel, line, end_line,
                          v.source if v else "none", v.alts if v else [])
    if not args:
        return None
    target = args[0]
    is_platform = False
    if target.type == "call_expression":
        c = named(target)[0]
        cname = c.text.decode()
        inner = ev._args(target)
        if cname in _PLATFORM and inner:
            is_platform, target = True, inner[0]
        elif cname == "kotlin" and inner:
            mod = ev._plain(inner[0])
            if mod is None:
                return None
            ver = ev.evaluate(inner[1]) if len(inner) > 1 else None
            return Dependency("org.jetbrains.kotlin", f"kotlin-{mod}", ver.value if ver else None, conf, rel,
                              node_line(target), node_line(target), ver.source if ver else "none",
                              ver.alts if ver else [])
        elif cname in ("project", "files", "fileTree", "gradleApi", "localGroovy"):
            return None
    if target.type == "navigation_expression" and target.text.decode().startswith("libs."):
        if catalog is None:
            return None
        lib = catalog.by_accessor(target.text.decode()[len("libs."):])
        if lib is None:
            return None
        version, source, alts = lib.version, "catalog", [Location(path=catalog.path, line=lib.line, end_line=lib.line)]
        if lib.version_ref and lib.version_ref in catalog.versions:
            version, vline = catalog.versions[lib.version_ref]
            source = f"catalog:{lib.version_ref}"
            alts.append(Location(path=catalog.path, line=vline, end_line=vline))
        return Dependency(lib.group, lib.artifact, version, conf, rel, node_line(target), node_line(target), source,
                          alts, is_platform)
    val = ev.evaluate(target)
    if val is None and target.type in ("string_literal", "multiline_string_literal"):
        # coordinates with an unresolvable version expression: keep the dependency visible (note, no finding)
        parts = decode_string_literal(target, kf.src)
        if parts and parts[0][0] == "text":
            head = parts[0][1].split(":")
            if len(head) == 3 and head[0] and head[1] and head[2] == "":
                line_no = node_line(target)
                return Dependency(head[0], head[1], None, conf, rel, line_no, line_no, "unresolved", [], is_platform)
    if val is None:
        return None
    coords = _split_coords(val.value)
    if coords is None:
        return None
    g, a, v = coords
    tline = node_line(target)
    return Dependency(g, a, v, conf, rel, tline, tline, val.source if v else "none", val.alts if v else [], is_platform)


# ---------------------------------------------------------------------------------------------------------
# Groovy (basic)
# ---------------------------------------------------------------------------------------------------------

_G_DEF = re.compile(r"^\s*(?:def|String|ext\.)\s*([A-Za-z_][\w]*)\s*=\s*['\"]([^'\"]+)['\"]", re.M)
_G_EXT_BLOCK_VAR = re.compile(r"^\s*([A-Za-z_][\w]*)\s*=\s*['\"]([^'\"]+)['\"]\s*$", re.M)
_G_CALL = re.compile(r"^\s*([A-Za-z][\w]*)\s*\(?\s*(.+?)\s*\)?\s*$")


def _parse_groovy(root: Path, rel: str) -> list[Dependency]:
    path = safe_file(root, rel)
    if path is None:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    vars_: dict[str, tuple[str, int]] = {}
    for m in _G_DEF.finditer(text):
        vars_[m.group(1)] = (m.group(2), text.count("\n", 0, m.start()) + 1)
    for m in _G_EXT_BLOCK_VAR.finditer(text):
        vars_.setdefault(m.group(1), (m.group(2), text.count("\n", 0, m.start()) + 1))
    props = read_properties(safe_file(root, "gradle.properties"))

    def resolve(expr: str) -> tuple[str, list[Location]] | None:
        out, alts = [], []
        for tok in re.split(r"\s*\+\s*", expr.strip()):
            tok = tok.strip()
            if len(tok) >= 2 and tok[0] in "'\"" and tok[-1] == tok[0]:
                body = tok[1:-1]
                if tok[0] == '"':
                    def sub(m):
                        name = m.group(1) or m.group(2)
                        if name in vars_:
                            alts.append(Location(path=rel, line=vars_[name][1], end_line=vars_[name][1]))
                            return vars_[name][0]
                        if name in props:
                            alts.append(Location(path="gradle.properties", line=props[name][1], end_line=props[name][1]))
                            return props[name][0]
                        raise KeyError(name)
                    try:
                        body = re.sub(r"\$\{([\w.]+)\}|\$([A-Za-z_]\w*)", sub, body)
                    except KeyError:
                        return None
                out.append(body)
            elif tok in vars_:
                alts.append(Location(path=rel, line=vars_[tok][1], end_line=vars_[tok][1]))
                out.append(vars_[tok][0])
            elif tok in props:
                out.append(props[tok][0])
            else:
                return None
        return "".join(out), alts

    deps: list[Dependency] = []
    depth, in_deps = 0, False
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_deps and re.match(r"^dependencies\s*\{", stripped):
            in_deps, depth = True, 0
        if in_deps:
            depth += line.count("{") - line.count("}")
            m = _G_CALL.match(stripped)
            if m and is_configuration(m.group(1)):
                conf, rest = m.group(1), m.group(2)
                named_m = dict(re.findall(r"(group|name|version)\s*:\s*(['\"][^'\"]+['\"]|\w+)", rest))
                if "group" in named_m and "name" in named_m:
                    g, a = resolve(named_m["group"]), resolve(named_m["name"])
                    v = resolve(named_m["version"]) if "version" in named_m else None
                    if g and a:
                        deps.append(Dependency(g[0], a[0], v[0] if v else None, conf, rel, i, i,
                                               "groovy", v[1] if v else []))
                else:
                    r = resolve(rest)
                    coords = _split_coords(r[0]) if r else None
                    if coords:
                        deps.append(Dependency(coords[0], coords[1], coords[2], conf, rel, i, i, "groovy",
                                               r[1] if r else []))
            if depth <= 0 and "}" in line:
                in_deps = False
    return deps


def parse_build_file(root: Path, rel: str, catalog: VersionCatalog | None = None) -> list[Dependency]:
    root = Path(root)
    if catalog is None:
        catalog = load_catalog(root)
    if safe_file(root, rel) is None:
        return []
    if rel.endswith(".kts"):
        return _parse_kts(root, rel, catalog)
    return _parse_groovy(root, rel)


def module_build_files(root: Path) -> list[str]:
    """Root build file plus modules listed by `include(...)` in settings.gradle(.kts)."""
    root = Path(root)
    out: list[str] = []
    for name in ("build.gradle.kts", "build.gradle"):
        if safe_file(root, name) is not None:
            out.append(name)
            break
    for settings in ("settings.gradle.kts", "settings.gradle"):
        sp = safe_file(root, settings)
        if sp is None:
            continue
        text = sp.read_text(encoding="utf-8", errors="replace")
        for call in re.finditer(r"include\s*\(?([^)\n]+)\)?", text):
            for mod in re.findall(r"['\"]:?([\w\-.:]+)['\"]", call.group(1)):
                mdir = mod.strip(":").replace(":", "/")
                if not mdir or ".." in mdir.split("/") or "" in mdir.split("/"):
                    continue
                for name in ("build.gradle.kts", "build.gradle"):
                    if safe_file(root, f"{mdir}/{name}") is not None:
                        out.append(f"{mdir}/{name}")
                        break
    return out
