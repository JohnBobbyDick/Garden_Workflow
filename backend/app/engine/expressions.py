"""Safe expression language for ``logic.if_else`` (no ``eval``; values come only from a dict context).

Grammar::

    expr    := or
    or      := and ("or" and)*
    and     := not ("and" not)*
    not     := "not" not | cmp
    cmp     := atom (("=="|"!="|">"|">="|"<"|"<="|"in"|"contains") atom)?
    atom    := NUMBER | STRING | true | false | null | PATH | "(" expr ")"

``PATH`` is a dotted name looked up in the context (``findings.count``, ``severity.max``…). An unknown
upper-case bare name (``HIGH``, ``CRITICAL``, ``PASS``) is a string constant. Severity strings compare by rank
(``LOW < MEDIUM < HIGH < CRITICAL``). ``list == x`` means "x is in the list" (``category == 'SECRET'``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.analyzers.common.finding import SEVERITY_ORDER

MAX_LEN = 2000
MAX_DEPTH = 40

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<op>==|!=|>=|<=|>|<)
  | (?P<lp>\()
  | (?P<rp>\))
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
""", re.VERBOSE)
KEYWORDS = {"and", "or", "not", "in", "contains", "true", "false", "null"}


class ExpressionError(ValueError):
    pass


@dataclass
class Tok:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> list[Tok]:
    if len(text) > MAX_LEN:
        raise ExpressionError(f"выражение длиннее {MAX_LEN} символов")
    out: list[Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ExpressionError(f"недопустимый символ «{text[pos]}» в позиции {pos + 1}")
        kind = m.lastgroup or ""
        val = m.group(0)
        if kind != "ws":
            if kind == "name" and val in KEYWORDS:
                kind = "kw"
            out.append(Tok(kind, val, pos))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, toks: list[Tok]) -> None:
        self.toks = toks
        self.i = 0
        self.depth = 0

    def peek(self) -> Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> Tok:
        t = self.peek()
        if t is None:
            raise ExpressionError("неожиданный конец выражения")
        self.i += 1
        return t

    def is_kw(self, word: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == "kw" and t.value == word

    def parse(self) -> tuple:
        if not self.toks:
            raise ExpressionError("пустое выражение")
        node = self.or_()
        t = self.peek()
        if t is not None:
            raise ExpressionError(f"лишний фрагмент «{t.value}» в позиции {t.pos + 1}")
        return node

    def or_(self) -> tuple:
        node = self.and_()
        while self.is_kw("or"):
            self.take()
            node = ("or", node, self.and_())
        return node

    def and_(self) -> tuple:
        node = self.not_()
        while self.is_kw("and"):
            self.take()
            node = ("and", node, self.not_())
        return node

    def not_(self) -> tuple:
        if self.is_kw("not"):
            self.take()
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise ExpressionError("слишком глубокая вложенность")
            node = ("not", self.not_())
            self.depth -= 1
            return node
        return self.cmp()

    def cmp(self) -> tuple:
        left = self.atom()
        t = self.peek()
        if t is not None and (t.kind == "op" or (t.kind == "kw" and t.value in ("in", "contains"))):
            self.take()
            return ("cmp", t.value, left, self.atom())
        return left

    def atom(self) -> tuple:
        t = self.take()
        if t.kind == "num":
            return ("lit", float(t.value) if "." in t.value else int(t.value))
        if t.kind == "str":
            body = t.value[1:-1]
            return ("lit", re.sub(r"\\(.)", r"\1", body))
        if t.kind == "kw" and t.value in ("true", "false", "null"):
            return ("lit", {"true": True, "false": False, "null": None}[t.value])
        if t.kind == "name":
            return ("path", t.value)
        if t.kind == "lp":
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise ExpressionError("слишком глубокая вложенность")
            node = self.or_()
            if self.take().kind != "rp":
                raise ExpressionError("ожидалась «)»")
            self.depth -= 1
            return node
        raise ExpressionError(f"неожиданный элемент «{t.value}» в позиции {t.pos + 1}")


def parse(text: str) -> tuple:
    return _Parser(tokenize(text)).parse()


def resolve_path(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


class _Missing:
    pass


_MISSING = _Missing()


def _sev(v: Any) -> int | None:
    return SEVERITY_ORDER.get(v.upper()) if isinstance(v, str) else None


def _compare(op: str, a: Any, b: Any) -> bool:
    if op == "in":
        return isinstance(b, (list, str)) and (a in b if isinstance(b, list) else isinstance(a, str) and a in b)
    if op == "contains":
        return _compare("in", b, a)
    if isinstance(a, list) and not isinstance(b, list) and op in ("==", "!="):
        return (b in a) == (op == "==")
    sa, sb = _sev(a), _sev(b)
    if sa is not None and sb is not None:
        a, b = sa, sb
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    numeric = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b))
    if not numeric and not (isinstance(a, str) and isinstance(b, str)):
        return False
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]


def _eval(node: tuple, ctx: dict[str, Any]) -> Any:
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "path":
        v = resolve_path(ctx, node[1])
        if v is _MISSING:
            name = node[1]
            return name if ("." not in name and name.isupper()) else None
        return v
    if kind == "not":
        return not _truthy(_eval(node[1], ctx))
    if kind == "and":
        return _truthy(_eval(node[1], ctx)) and _truthy(_eval(node[2], ctx))
    if kind == "or":
        return _truthy(_eval(node[1], ctx)) or _truthy(_eval(node[2], ctx))
    if kind == "cmp":
        return _compare(node[1], _eval(node[2], ctx), _eval(node[3], ctx))
    raise ExpressionError(f"unknown node {kind}")


def _truthy(v: Any) -> bool:
    return bool(v)


def evaluate(text: str, ctx: dict[str, Any]) -> bool:
    return _truthy(_eval(parse(text), ctx))
