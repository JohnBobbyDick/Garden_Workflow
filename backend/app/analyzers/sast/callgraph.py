"""Light interprocedural call graph through constructor-injected dependencies (Spring style)."""

from __future__ import annotations

from dataclasses import dataclass

from app.analyzers.common.kotlin_ast import (
    KClass,
    KFunction,
    KotlinFile,
    Node,
    ProjectIndex,
    first_child,
    iter_nodes,
    named,
)

SPRING_DATA_BASES = {"JpaRepository", "CrudRepository", "PagingAndSortingRepository", "Repository", "MongoRepository",
                     "ReactiveCrudRepository", "CoroutineCrudRepository", "ListCrudRepository", "R2dbcRepository",
                     "JpaSpecificationExecutor", "ListPagingAndSortingRepository"}


@dataclass
class CallSite:
    caller: KFunction
    node: Node
    receiver: str | None
    method: str
    args: list[Node]
    named_args: dict[str, Node]
    targets: list[KFunction]
    receiver_type: str | None


def call_args(call: Node) -> tuple[list[Node], dict[str, Node]]:
    va = first_child(call, "value_arguments")
    pos: list[Node] = []
    kw: dict[str, Node] = {}
    for a in va.children if va is not None else []:
        if a.type != "value_argument":
            continue
        ch = named(a)
        if len(ch) == 2 and ch[0].type == "identifier":
            kw[ch[0].text.decode()] = ch[1]
        elif ch:
            pos.append(ch[-1])
    lam = first_child(call, "annotated_lambda")
    if lam is not None:
        pos.append(lam)
    return pos, kw


class CallGraph:
    def __init__(self, files: list[KotlinFile], project: ProjectIndex):
        self.files = files
        self.project = project
        self.all_functions: list[KFunction] = [f for kf in files for f in kf.functions()]
        self._impls: dict[str, list[KClass]] = {}
        for kf in files:
            for c in kf.classes():
                for s in c.supertypes:
                    self._impls.setdefault(s, []).append(c)
        self._sites: dict[int, list[CallSite]] = {}
        self._callers: dict[int, list[CallSite]] = {}
        for fn in self.all_functions:
            sites = self._compute_sites(fn)
            self._sites[fn.node.id] = sites
            for s in sites:
                for t in s.targets:
                    self._callers.setdefault(t.node.id, []).append(s)

    # ---------------------------------------------------------------------------------------------------
    def classes_for_type(self, type_name: str) -> list[KClass]:
        direct = self.project.classes.get(type_name, [])
        concrete = [c for c in direct if c.node.type != "interface"]
        impls = self._impls.get(type_name, [])
        out = []
        for c in direct + impls:
            if c not in out:
                out.append(c)
        return out if out else concrete

    def is_spring_data_repo(self, type_name: str | None) -> bool:
        if not type_name:
            return False
        for c in self.project.classes.get(type_name, []):
            if set(c.supertypes) & SPRING_DATA_BASES:
                return True
        return False

    def field_type(self, fn: KFunction, name: str) -> str | None:
        if fn.cls is not None:
            ft = fn.cls.field_types()
            if name in ft:
                return ft[name]
        p = fn.param(name)
        if p is not None:
            return p.type_name
        return None

    def _compute_sites(self, fn: KFunction) -> list[CallSite]:
        body = fn.body
        if body is None:
            return []
        sites: list[CallSite] = []
        for call in iter_nodes(body):
            if call.type != "call_expression":
                continue
            callee = named(call)[0]
            pos, kw = call_args(call)
            receiver, method, rtype = None, None, None
            targets: list[KFunction] = []
            if callee.type == "navigation_expression":
                parts = named(callee)
                method = parts[-1].text.decode()
                recv = parts[0]
                rtext = recv.text.decode()
                if rtext.startswith("this."):
                    rtext = rtext[5:]
                receiver = rtext
                if recv.type in ("identifier", "navigation_expression", "this_expression"):
                    rtype = self.field_type(fn, rtext.split(".")[-1]) if recv.type != "this_expression" else (fn.cls.name if fn.cls else None)
                if rtype:
                    for c in self.classes_for_type(rtype):
                        targets.extend(f for f in c.functions if f.name == method and self._arity_ok(f, pos, kw))
            elif callee.type == "identifier":
                method = callee.text.decode()
                if fn.cls is not None:
                    targets.extend(f for f in fn.cls.functions if f.name == method and f is not fn and self._arity_ok(f, pos, kw))
                if not targets:
                    targets.extend(f for f in fn.file.functions() if f.cls is None and f.name == method and self._arity_ok(f, pos, kw))
            if method is None:
                continue
            sites.append(CallSite(fn, call, receiver, method, pos, kw, targets, rtype))
        return sites

    @staticmethod
    def _arity_ok(f: KFunction, pos: list[Node], kw: dict[str, Node]) -> bool:
        n = len([p for p in pos if p.type != "annotated_lambda"])
        return n <= len(f.params) and all(f.param(k) is not None for k in kw)

    def sites(self, fn: KFunction) -> list[CallSite]:
        return self._sites.get(fn.node.id, [])

    def callers(self, fn: KFunction) -> list[CallSite]:
        return self._callers.get(fn.node.id, [])

    @staticmethod
    def map_args(site: CallSite, target: KFunction) -> dict[str, Node]:
        """target param name → argument expression."""
        out: dict[str, Node] = {}
        positional = [a for a in site.args if a.type != "annotated_lambda"]
        for i, a in enumerate(positional):
            if i < len(target.params):
                out[target.params[i].name] = a
        out.update({k: v for k, v in site.named_args.items() if target.param(k) is not None})
        return out
