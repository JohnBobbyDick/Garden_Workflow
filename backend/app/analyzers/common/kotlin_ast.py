"""Kotlin source model on top of tree-sitter-kotlin.

Provides a light IR (classes, functions, parameters with annotations, constructor fields) and a constant
resolver able to fold string expressions built from literals: concatenation, templates, ``format``,
``joinToString``, ``StringBuilder.append``/``buildString``, Base64 decoding and simple transforms
(``reversed``, ``trim``, ``lowercase``...). The resolver never executes code from the scanned project.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from functools import lru_cache

import tree_sitter as ts
import tree_sitter_kotlin as tsk

Node = ts.Node


@lru_cache(maxsize=1)
def _parser() -> ts.Parser:
    return ts.Parser(ts.Language(tsk.language()))


def node_line(node: Node) -> int:
    return node.start_point[0] + 1


def node_end_line(node: Node) -> int:
    return node.end_point[0] + 1


def iter_nodes(node: Node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def named(node: Node) -> list[Node]:
    return [c for c in node.children if c.is_named]


def first_child(node: Node, type_: str) -> Node | None:
    for c in node.children:
        if c.type == type_:
            return c
    return None


def children_of(node: Node, type_: str) -> list[Node]:
    return [c for c in node.children if c.type == type_]


# ---------------------------------------------------------------------------------------------------------
# string literals
# ---------------------------------------------------------------------------------------------------------

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "\\": "\\", '"': '"', "'": "'", "$": "$"}
_IDENT_START = re.compile(r"[A-Za-z_]")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _decode_raw(raw: str, multiline: bool) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    buf: list[str] = []
    i, n = 0, len(raw)

    def flush():
        if buf:
            parts.append(("text", "".join(buf)))
            buf.clear()

    while i < n:
        ch = raw[i]
        if ch == "\\" and not multiline and i + 1 < n:
            nxt = raw[i + 1]
            if nxt == "u" and i + 5 < n:
                try:
                    buf.append(chr(int(raw[i + 2 : i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            buf.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        if ch == "$" and i + 1 < n:
            if raw[i + 1] == "{":
                depth, j = 1, i + 2
                while j < n and depth:
                    if raw[j] == "{":
                        depth += 1
                    elif raw[j] == "}":
                        depth -= 1
                    j += 1
                flush()
                parts.append(("expr", raw[i + 2 : j - 1].strip()))
                i = j
                continue
            if _IDENT_START.match(raw[i + 1]):
                m = _IDENT.match(raw, i + 1)
                assert m is not None
                flush()
                parts.append(("expr", m.group(0)))
                i = m.end()
                continue
        buf.append(ch)
        i += 1
    flush()
    return parts


def literal_raw(node: Node, src: bytes) -> tuple[str, bool]:
    text = src[node.start_byte : node.end_byte].decode("utf-8", "replace")
    if node.type == "multiline_string_literal" or text.startswith('"""'):
        return text[3:-3], True
    return text[1:-1], False


def decode_string_literal(node: Node, src: bytes) -> list[tuple[str, str]]:
    raw, multiline = literal_raw(node, src)
    return _decode_raw(raw, multiline)


def is_string_literal(node: Node | None) -> bool:
    return node is not None and node.type in ("string_literal", "multiline_string_literal")


def plain_string_value(node: Node | None, src: bytes) -> str | None:
    """Value of a literal without templates, else None."""
    if not is_string_literal(node):
        return None
    parts = decode_string_literal(node, src)
    if any(k == "expr" for k, _ in parts):
        return None
    return "".join(v for _, v in parts)


# ---------------------------------------------------------------------------------------------------------
# IR
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Annotation:
    name: str
    node: Node
    src: bytes

    @property
    def args(self) -> list[Node]:
        inv = first_child(self.node, "constructor_invocation")
        if inv is None:
            return []
        va = first_child(inv, "value_arguments")
        return children_of(va, "value_argument") if va is not None else []

    def arg_value_node(self, arg: Node) -> Node | None:
        ch = named(arg)
        return ch[-1] if ch else None

    def arg_name(self, arg: Node) -> str | None:
        ch = named(arg)
        if len(ch) >= 2 and ch[0].type == "identifier":
            return ch[0].text.decode()
        return None

    def string_args(self) -> list[str]:
        out: list[str] = []
        for a in self.args:
            v = self.arg_value_node(a)
            for n in iter_nodes(v) if v is not None else []:
                if is_string_literal(n):
                    s = plain_string_value(n, self.src)
                    if s is not None:
                        out.append(s)
        return out

    def first_string_arg(self) -> str | None:
        vals = self.string_args()
        return vals[0] if vals else None

    def named_arg(self, name: str) -> Node | None:
        for a in self.args:
            if self.arg_name(a) == name:
                return self.arg_value_node(a)
        return None

    @property
    def text(self) -> str:
        return self.node.text.decode("utf-8", "replace")


def _annotation_name(ann: Node) -> str:
    target = first_child(ann, "constructor_invocation") or ann
    ut = first_child(target, "user_type")
    if ut is None:
        for c in iter_nodes(ann):
            if c.type == "user_type":
                ut = c
                break
    if ut is None:
        return ""
    ids = [c.text.decode() for c in ut.children if c.type == "identifier"]
    return ids[-1] if ids else ""


def annotations_of(modifiers: Node | None, src: bytes) -> list[Annotation]:
    if modifiers is None:
        return []
    return [Annotation(_annotation_name(a), a, src) for a in modifiers.children if a.type == "annotation"]


def type_name(node: Node | None) -> str:
    if node is None:
        return ""
    if node.type == "nullable_type":
        inner = named(node)
        return type_name(inner[0]) if inner else ""
    if node.type == "user_type":
        ids = [c.text.decode() for c in node.children if c.type == "identifier"]
        return ids[-1] if ids else node.text.decode()
    return node.text.decode()


@dataclass
class KParam:
    name: str
    type_name: str
    annotations: list[Annotation]
    node: Node

    def has_annotation(self, *names: str) -> bool:
        return any(a.name in names for a in self.annotations)


@dataclass
class KFunction:
    name: str
    node: Node
    annotations: list[Annotation]
    params: list[KParam]
    cls: KClass | None
    file: KotlinFile

    @property
    def body(self) -> Node | None:
        return first_child(self.node, "function_body")

    @property
    def line(self) -> int:
        return node_line(self.node)

    @property
    def name_line(self) -> int:
        for c in self.node.children:
            if c.type == "identifier":
                return node_line(c)
        return self.line

    @property
    def end_line(self) -> int:
        return node_end_line(self.node)

    def annotation(self, *names: str) -> Annotation | None:
        for a in self.annotations:
            if a.name in names:
                return a
        return None

    def param(self, name: str) -> KParam | None:
        for p in self.params:
            if p.name == name:
                return p
        return None

    @property
    def qualified(self) -> str:
        return f"{self.cls.name}.{self.name}" if self.cls else self.name


@dataclass
class KClass:
    name: str
    node: Node
    annotations: list[Annotation]
    constructor_fields: dict[str, str]
    functions: list[KFunction] = field(default_factory=list)
    properties: list[Node] = field(default_factory=list)
    supertypes: list[str] = field(default_factory=list)
    is_object: bool = False
    file: KotlinFile | None = None

    def annotation(self, *names: str) -> Annotation | None:
        for a in self.annotations:
            if a.name in names:
                return a
        return None

    def field_types(self) -> dict[str, str]:
        """Constructor fields + class-level properties with an explicit type or constructor call."""
        out = dict(self.constructor_fields)
        assert self.file is not None
        for p in self.properties:
            vd = first_child(p, "variable_declaration")
            if vd is None:
                continue
            ident = first_child(vd, "identifier")
            if ident is None:
                continue
            t = None
            for c in vd.children:
                if c.type in ("user_type", "nullable_type"):
                    t = type_name(c)
            if t is None:
                init = property_initializer(p)
                if init is not None and init.type == "call_expression" and named(init)[0].type == "identifier":
                    t = named(init)[0].text.decode()
            if t:
                out[ident.text.decode()] = t
        return out


def property_name(prop: Node) -> str | None:
    vd = first_child(prop, "variable_declaration")
    if vd is None:
        return None
    ident = first_child(vd, "identifier")
    return ident.text.decode() if ident is not None else None


def property_initializer(prop: Node) -> Node | None:
    """Expression after `=` in a property declaration (skipping delegates/getters)."""
    seen_eq = False
    for c in prop.children:
        if c.type == "=":
            seen_eq = True
            continue
        if seen_eq and c.is_named:
            return c
    return None


def binary_operator(node: Node) -> str:
    for c in node.children:
        if not c.is_named:
            return c.type
    return ""


# ---------------------------------------------------------------------------------------------------------
# constant resolution
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Resolved:
    value: str
    literal_lines: set[int] = field(default_factory=set)
    fragments: int = 0
    transformed: bool = False
    is_bytes: bool = False
    # raw text of every contributing string literal (needed to mask fragments in snippets)
    literals: list[str] = field(default_factory=list)

    def merge(self, other: Resolved, value: str) -> Resolved:
        if len(value) > ConstantResolver.MAX_VALUE:
            raise _ValueTooLarge()
        return Resolved(
            value,
            self.literal_lines | other.literal_lines,
            self.fragments + other.fragments,
            True,
            literals=self.literals + other.literals,
        )


class _ValueTooLarge(Exception):
    pass


@dataclass
class _Budget:
    evals: int = 0


_IDENTITY_TRANSFORMS = {"toString", "intern"}
_UNARY_TRANSFORMS = {
    "reversed": lambda s: s[::-1],
    "trim": str.strip,
    "trimEnd": str.rstrip,
    "trimStart": str.lstrip,
    "lowercase": str.lower,
    "uppercase": str.upper,
    "toLowerCase": str.lower,
    "toUpperCase": str.upper,
}
_FORMAT_SPEC = re.compile(r"%(?:\d+\$)?[-#+ 0,(]*\d*(?:\.\d+)?([sdSf%n])")


def _kotlin_format(fmt: str, args: list[str]) -> str | None:
    out: list[str] = []
    pos, idx = 0, 0
    if len(fmt) + sum(len(a) for a in args) > ConstantResolver.MAX_VALUE:
        return None
    for m in _FORMAT_SPEC.finditer(fmt):
        out.append(fmt[pos : m.start()])
        conv = m.group(1)
        if conv == "%":
            out.append("%")
        elif conv == "n":
            out.append("\n")
        else:
            explicit = re.match(r"%(\d+)\$", m.group(0))
            k = int(explicit.group(1)) - 1 if explicit else idx
            if not explicit:
                idx += 1
            if k >= len(args):
                return None
            out.append(args[k].upper() if conv == "S" else args[k])
        pos = m.end()
    out.append(fmt[pos:])
    return "".join(out)


class ConstantResolver:
    MAX_DEPTH = 48
    MAX_EVALS = 2000  # per top-level resolution: bounds total work on adversarial sources
    MAX_VALUE = 65536

    def __init__(self, file: KotlinFile, fn: KFunction | None, project: ProjectIndex | None = None,
                 budget: _Budget | None = None):
        self.file = file
        self.fn = fn
        self.project = project
        self.src = file.src
        self.budget = budget or _Budget()

    def _sub(self, file: KotlinFile, fn: KFunction | None = None) -> ConstantResolver:
        return ConstantResolver(file, fn, self.project, self.budget)

    # -- scopes -------------------------------------------------------------------------------------------
    def _local_decls(self) -> list[Node]:
        if self.fn is None or self.fn.body is None:
            return []
        return [n for n in iter_nodes(self.fn.body) if n.type == "property_declaration"]

    def _lookup_decl(self, name: str, before_line: int | None) -> Node | None:
        best = None
        for d in self._local_decls():
            if property_name(d) == name and (before_line is None or node_line(d) <= before_line):
                if best is None or node_line(d) >= node_line(best):
                    best = d
        if best is not None:
            return best
        cls = self.fn.cls if self.fn else None
        while cls is not None:
            for p in cls.properties:
                if property_name(p) == name:
                    return p
            cls = self.file.enclosing_class(cls)
        for p in self.file.top_level_properties():
            if property_name(p) == name:
                return p
        if self.project is not None:
            hit = self.project.lookup(name, self.file)
            if hit is not None:
                return hit[1]
        return None

    def _tick(self, depth: int) -> bool:
        if depth == 0:
            self.budget.evals = 0
        self.budget.evals += 1
        return self.budget.evals <= self.MAX_EVALS and depth <= self.MAX_DEPTH

    def resolve_name(self, name: str, before_line: int | None = None, depth: int = 0) -> Resolved | None:
        if not self._tick(depth):
            return None
        try:
            return self._resolve_name_inner(name, before_line, depth)
        except _ValueTooLarge:
            if depth == 0:
                return None
            raise

    def _resolve_name_inner(self, name: str, before_line: int | None, depth: int) -> Resolved | None:
        decl = self._lookup_decl(name, before_line)
        if decl is None:
            return None
        init = property_initializer(decl)
        if init is None:
            return None
        decl_file = self.file
        if self.project is not None and decl.id not in self.file.node_ids:
            owner = self.project.file_of(decl)
            if owner is not None and owner is not self.file:
                return self._sub(owner).resolve(init, depth + 1)
        res = self.resolve(init, depth + 1)
        if res is not None and self._is_builder(init):
            res = self._apply_builder_mutations(name, decl, res, before_line, depth)
        _ = decl_file
        return res

    @staticmethod
    def _is_builder(init: Node) -> bool:
        return init.type == "call_expression" and named(init)[0].text.decode() == "StringBuilder"

    def _apply_builder_mutations(self, name: str, decl: Node, res: Resolved, before_line, depth) -> Resolved | None:
        if self.fn is None or self.fn.body is None:
            return res
        start = node_end_line(decl)
        for n in iter_nodes(self.fn.body):
            if n.type != "call_expression" or node_line(n) <= start:
                continue
            if before_line is not None and node_line(n) > before_line:
                continue
            callee = named(n)[0]
            if callee.type == "navigation_expression":
                parts = named(callee)
                if len(parts) == 2 and parts[0].text.decode() == name and parts[1].text.decode() == "append":
                    arg = self._call_args(n)
                    if len(arg) != 1:
                        return None
                    r = self.resolve(arg[0], depth + 1)
                    if r is None:
                        return None
                    res = res.merge(r, res.value + r.value)
        return res

    # -- expressions -------------------------------------------------------------------------------------
    def _call_args(self, call: Node) -> list[Node]:
        va = first_child(call, "value_arguments")
        if va is None:
            return []
        out = []
        for a in children_of(va, "value_argument"):
            ch = named(a)
            if ch:
                out.append(ch[-1])
        return out

    def _lambda_statements(self, call: Node) -> list[Node]:
        al = first_child(call, "annotated_lambda")
        if al is None:
            return []
        lam = first_child(al, "lambda_literal")
        if lam is None:
            return []
        stmts = first_child(lam, "statements")
        return named(stmts) if stmts is not None else [c for c in named(lam) if c.type != "lambda_parameters"]

    def resolve(self, node: Node | None, depth: int = 0) -> Resolved | None:
        if node is None or not self._tick(depth):
            return None
        try:
            res = self._resolve_inner(node, depth)
        except _ValueTooLarge:
            if depth == 0:
                return None
            raise
        if res is not None and len(res.value) > self.MAX_VALUE:
            if depth == 0:
                return None
            raise _ValueTooLarge()
        return res

    def _resolve_inner(self, node: Node, depth: int) -> Resolved | None:
        t = node.type
        if t in ("string_literal", "multiline_string_literal"):
            return self._resolve_literal(node, depth)
        if t == "parenthesized_expression":
            inner = named(node)
            return self.resolve(inner[0], depth + 1) if inner else None
        if t == "identifier":
            return self.resolve_name(node.text.decode(), node_line(node), depth + 1)
        if t == "navigation_expression":
            return self._resolve_navigation(node, depth)
        if t == "binary_expression":
            if binary_operator(node) != "+":
                return None
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            a, b = self.resolve(left, depth + 1), self.resolve(right, depth + 1)
            if a is None or b is None or a.is_bytes or b.is_bytes:
                return None
            return a.merge(b, a.value + b.value)
        if t == "call_expression":
            return self._resolve_call(node, depth)
        return None

    def _resolve_literal(self, node: Node, depth: int) -> Resolved | None:
        parts = decode_string_literal(node, self.src)
        interps = [c for c in node.children if c.type == "interpolation"]
        value: list[str] = []
        raw_segments = [seg for seg in re.split(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*", literal_raw(node, self.src)[0]) if seg]
        res = Resolved("", {node_line(node)}, 1, False,
                       literals=[t for k, t in parts if k == "text" and t] + raw_segments)
        ii = 0
        for kind, text in parts:
            if kind == "text":
                value.append(text)
                continue
            sub: Resolved | None
            if _IDENT.fullmatch(text):
                sub = self.resolve_name(text, node_line(node), depth + 1)
                # `${name}` also produces an interpolation node; keep counters aligned
                if ii < len(interps) and interps[ii].text.decode().strip("${} ") == text:
                    ii += 1
            else:
                sub = self.resolve(named(interps[ii])[0], depth + 1) if ii < len(interps) and named(interps[ii]) else None
                ii += 1
            if sub is None or sub.is_bytes:
                return None
            value.append(sub.value)
            res = res.merge(sub, "")
        res.value = "".join(value)
        if len(res.value) > self.MAX_VALUE:
            raise _ValueTooLarge()
        return res

    def _resolve_navigation(self, node: Node, depth: int) -> Resolved | None:
        parts = named(node)
        if len(parts) != 2:
            return None
        recv, member = parts
        name = member.text.decode()
        if recv.type == "this_expression":
            return self.resolve_name(name, None, depth + 1)
        if recv.type == "identifier" and self.project is not None:
            hit = self.project.lookup(f"{recv.text.decode()}.{name}", self.file)
            if hit is not None:
                owner, decl = hit
                init = property_initializer(decl)
                return self._sub(owner).resolve(init, depth + 1)
        if recv.type == "identifier":
            for cls in self.file.classes():
                if cls.name == recv.text.decode() or (cls.is_object and cls.name == recv.text.decode()):
                    for p in cls.properties:
                        if property_name(p) == name:
                            return self._sub(self.file).resolve(property_initializer(p), depth + 1)
        return None

    def _resolve_call(self, node: Node, depth: int) -> Resolved | None:
        callee = named(node)[0]
        args = self._call_args(node)
        if callee.type == "identifier":
            fname = callee.text.decode()
            if fname == "String" and args:
                inner = self.resolve(args[0], depth + 1)
                if inner is None:
                    return None
                return Resolved(inner.value, inner.literal_lines, inner.fragments, True, False, inner.literals)
            if fname == "StringBuilder":
                if not args:
                    return Resolved("", set(), 0, True)
                return self.resolve(args[0], depth + 1)
            if fname == "buildString":
                res = Resolved("", set(), 0, True)
                for st in self._lambda_statements(node):
                    if st.type != "call_expression":
                        return None
                    c = named(st)[0]
                    if c.text.decode() != "append":
                        return None
                    a = self._call_args(st)
                    if len(a) != 1:
                        return None
                    r = self.resolve(a[0], depth + 1)
                    if r is None:
                        return None
                    res = res.merge(r, res.value + r.value)
                return res
            return None
        if callee.type != "navigation_expression":
            return None
        parts = named(callee)
        if len(parts) != 2:
            return None
        recv, member = parts
        method = member.text.decode()
        if method in _IDENTITY_TRANSFORMS and not args:
            r = self.resolve(recv, depth + 1)
            if r is not None:
                r = Resolved(r.value, r.literal_lines, r.fragments, True, r.is_bytes, r.literals)
            return r
        if method in _UNARY_TRANSFORMS and not args:
            r = self.resolve(recv, depth + 1)
            if r is None or r.is_bytes:
                return None
            return Resolved(_UNARY_TRANSFORMS[method](r.value), r.literal_lines, r.fragments, True, literals=r.literals)
        if method in ("append", "plus", "concat") and len(args) == 1:
            a, b = self.resolve(recv, depth + 1), self.resolve(args[0], depth + 1)
            if a is None or b is None:
                return None
            return a.merge(b, a.value + b.value)
        if method == "format":
            if recv.type == "identifier" and recv.text.decode() == "String":
                if not args:
                    return None
                fmt_node, rest = args[0], args[1:]
            else:
                fmt_node, rest = recv, args
            fmt = self.resolve(fmt_node, depth + 1)
            vals = [self.resolve(a, depth + 1) for a in rest]
            if fmt is None or any(v is None for v in vals):
                return None
            out = _kotlin_format(fmt.value, [v.value for v in vals])  # type: ignore[union-attr]
            if out is None:
                return None
            res = fmt
            for v in vals:
                res = res.merge(v, "")  # type: ignore[arg-type]
            res.value = out
            res.transformed = True
            return res
        if method == "joinToString":
            sep = ", "
            if args:
                s = self.resolve(args[0], depth + 1)
                if s is None:
                    return None
                sep = s.value
            if recv.type != "call_expression":
                return None
            rc = named(recv)[0]
            if rc.type != "identifier" or rc.text.decode() not in ("listOf", "arrayOf", "mutableListOf", "setOf"):
                return None
            items = [self.resolve(a, depth + 1) for a in self._call_args(recv)]
            if not items or any(i is None for i in items):
                return None
            if sum(len(i.value) for i in items) + len(sep) * len(items) > self.MAX_VALUE:  # type: ignore[union-attr]
                raise _ValueTooLarge()
            res = Resolved("", set(), 0, True)
            for it in items:
                res = res.merge(it, "")  # type: ignore[arg-type]
            res.value = sep.join(i.value for i in items)  # type: ignore[union-attr]
            return res
        if method == "decode" and len(args) == 1:
            if "Decoder" not in recv.text.decode() or "Base64" not in recv.text.decode():
                return None
            r = self.resolve(args[0], depth + 1)
            if r is None:
                return None
            try:
                url = "Url" in recv.text.decode()
                raw = (base64.urlsafe_b64decode if url else base64.b64decode)(r.value + "=" * (-len(r.value) % 4))
                decoded = raw.decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return None
            return Resolved(decoded, r.literal_lines, r.fragments, True, True, r.literals)
        if method in ("decodeToString",) and not args:
            r = self.resolve(recv, depth + 1)
            if r is None:
                return None
            return Resolved(r.value, r.literal_lines, r.fragments, True, False, r.literals)
        return None


# ---------------------------------------------------------------------------------------------------------
# file / project
# ---------------------------------------------------------------------------------------------------------


class KotlinFile:
    def __init__(self, path: str, src: bytes, tree: ts.Tree):
        self.path = path
        self.src = src
        self.tree = tree
        self.root = tree.root_node
        self.lines = src.decode("utf-8", "replace").splitlines()
        self._classes: list[KClass] | None = None
        self._functions: list[KFunction] | None = None
        self._node_ids: set[int] | None = None

    @classmethod
    def parse(cls, path: str, src: str | bytes) -> KotlinFile:
        data = src.encode("utf-8") if isinstance(src, str) else src
        return cls(path, data, _parser().parse(data))

    @property
    def has_error(self) -> bool:
        return self.root.has_error

    @property
    def node_ids(self) -> set[int]:
        if self._node_ids is None:
            self._node_ids = {n.id for n in iter_nodes(self.root)}
        return self._node_ids

    def text(self, node: Node) -> str:
        return self.src[node.start_byte : node.end_byte].decode("utf-8", "replace")

    def line_text(self, line: int) -> str:
        return self.lines[line - 1] if 0 < line <= len(self.lines) else ""

    def snippet(self, line: int, end_line: int) -> str:
        return "\n".join(self.lines[line - 1 : end_line])

    def find_all(self, type_: str, root: Node | None = None) -> list[Node]:
        return [n for n in iter_nodes(root or self.root) if n.type == type_]

    @property
    def package(self) -> str:
        ph = first_child(self.root, "package_header")
        if ph is None:
            return ""
        q = first_child(ph, "qualified_identifier") or first_child(ph, "identifier")
        return q.text.decode() if q is not None else ""

    def top_level_properties(self) -> list[Node]:
        return [c for c in self.root.children if c.type == "property_declaration"]

    def _build(self) -> None:
        classes: list[KClass] = []
        functions: list[KFunction] = []

        def visit(node: Node, owner: KClass | None):
            for c in node.children:
                if c.type in ("class_declaration", "object_declaration", "companion_object"):
                    k = self._make_class(c, owner)
                    classes.append(k)
                    body = first_child(c, "class_body") or first_child(c, "enum_class_body")
                    if body is not None:
                        visit(body, k)
                elif c.type == "function_declaration":
                    f = self._make_function(c, owner)
                    functions.append(f)
                    if owner is not None:
                        owner.functions.append(f)
                elif c.type == "property_declaration" and owner is not None:
                    owner.properties.append(c)
                elif c.type in ("class_body", "enum_class_body", "statements"):
                    visit(c, owner)

        visit(self.root, None)
        self._classes = classes
        self._functions = functions

    def _make_class(self, node: Node, owner: KClass | None) -> KClass:
        name_node = node.child_by_field_name("name") or first_child(node, "identifier")
        name = name_node.text.decode() if name_node is not None else ("Companion" if node.type == "companion_object" else "")
        anns = annotations_of(first_child(node, "modifiers"), self.src)
        fields: dict[str, str] = {}
        pc = first_child(node, "primary_constructor")
        if pc is not None:
            cp = first_child(pc, "class_parameters")
            for p in children_of(cp, "class_parameter") if cp is not None else []:
                ident = first_child(p, "identifier")
                tnode = next((c for c in p.children if c.type in ("user_type", "nullable_type")), None)
                if ident is not None:
                    fields[ident.text.decode()] = type_name(tnode)
        supers: list[str] = []
        for c in node.children:
            if c.type == "delegation_specifiers":
                for ut in iter_nodes(c):
                    if ut.type == "user_type":
                        supers.append(type_name(ut))
                        break
            if c.type == "delegation_specifier":
                for ut in iter_nodes(c):
                    if ut.type == "user_type":
                        supers.append(type_name(ut))
                        break
        k = KClass(name, node, anns, fields, supertypes=supers,
                   is_object=node.type in ("object_declaration", "companion_object"), file=self)
        k._owner = owner  # type: ignore[attr-defined]
        return k

    def _make_function(self, node: Node, owner: KClass | None) -> KFunction:
        name_node = node.child_by_field_name("name") or first_child(node, "identifier")
        anns = annotations_of(first_child(node, "modifiers"), self.src)
        params: list[KParam] = []
        fvp = first_child(node, "function_value_parameters")
        pending: list[Annotation] = []
        for c in fvp.children if fvp is not None else []:
            if c.type == "parameter_modifiers":
                pending.extend(annotations_of(c, self.src))
            elif c.type == "parameter":
                ident = first_child(c, "identifier")
                tnode = next((x for x in c.children if x.type in ("user_type", "nullable_type", "function_type")), None)
                params.append(KParam(ident.text.decode() if ident is not None else "", type_name(tnode), pending, c))
                pending = []
        return KFunction(name_node.text.decode() if name_node is not None else "", node, anns, params, owner, self)

    def classes(self) -> list[KClass]:
        if self._classes is None:
            self._build()
        return self._classes  # type: ignore[return-value]

    def functions(self) -> list[KFunction]:
        if self._functions is None:
            self._build()
        return self._functions  # type: ignore[return-value]

    def enclosing_class(self, cls: KClass) -> KClass | None:
        return getattr(cls, "_owner", None)

    def function_at(self, node: Node) -> KFunction | None:
        best = None
        for f in self.functions():
            if f.node.start_byte <= node.start_byte and node.end_byte <= f.node.end_byte:
                if best is None or f.node.start_byte >= best.node.start_byte:
                    best = f
        return best

    def class_at(self, node: Node) -> KClass | None:
        best = None
        for c in self.classes():
            if c.node.start_byte <= node.start_byte and node.end_byte <= c.node.end_byte:
                if best is None or c.node.start_byte >= best.node.start_byte:
                    best = c
        return best

    def resolver_for(self, fn: KFunction | None, project: ProjectIndex | None = None) -> ConstantResolver:
        return ConstantResolver(self, fn, project)


class ProjectIndex:
    """Cross-file index of constants (top-level, `object` and companion properties) and classes."""

    def __init__(self, files: list[KotlinFile]):
        self.files = files
        self._consts: dict[str, list[tuple[KotlinFile, Node]]] = {}
        self._owner_by_node: dict[int, KotlinFile] = {}
        self.classes: dict[str, list[KClass]] = {}
        for f in files:
            for p in f.top_level_properties():
                n = property_name(p)
                if n:
                    self._consts.setdefault(n, []).append((f, p))
                    self._owner_by_node[p.id] = f
            for c in f.classes():
                self.classes.setdefault(c.name, []).append(c)
                if c.is_object:
                    owner = f.enclosing_class(c)
                    qual = owner.name if (c.node.type == "companion_object" and owner) else c.name
                    for p in c.properties:
                        n = property_name(p)
                        if n:
                            self._consts.setdefault(f"{qual}.{n}", []).append((f, p))
                            self._owner_by_node[p.id] = f

    def lookup(self, name: str, origin: KotlinFile) -> tuple[KotlinFile, Node] | None:
        hits = self._consts.get(name, [])
        if not hits:
            return None
        same_pkg = [h for h in hits if h[0].package == origin.package]
        cands = same_pkg or hits
        return cands[0] if len(cands) == 1 else None

    def file_of(self, node: Node) -> KotlinFile | None:
        return self._owner_by_node.get(node.id)

    def class_named(self, name: str) -> KClass | None:
        cands = self.classes.get(name, [])
        return cands[0] if len(cands) == 1 else None
