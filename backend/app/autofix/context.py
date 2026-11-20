"""AutoFix context for the LLM (12A.3 §1): rule, ±10 lines, enclosing function/class (tree-sitter), related functions
of cross-file findings — everything masked line by line so that line numbers of the masked view equal the real file.

Raw secret values come from ``scan_secrets(collect=...)`` and live only in memory for the duration of one AutoFix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.common.finding import Finding
from app.analyzers.common.kotlin_ast import KotlinFile, node_end_line, node_line
from app.analyzers.common.masking import mask_in_text
from app.analyzers.secrets.detector import scan_secrets
from app.core.masking import Masker

SNIPPET_RADIUS = 10
MAX_ENCLOSING_LINES = 80
MAX_CONTEXT_CHARS = 12_000
MASK_ARTIFACTS = ("…(len=", "••••", "[идентификатор удалён")
ENCLOSING_TYPES = ("function_declaration", "class_declaration", "object_declaration", "companion_object")


def _split_values(values: set[str]) -> set[str]:
    """Multi-line values (private keys) are masked line by line so that the line count never changes."""
    out: set[str] = set()
    for v in values:
        parts = [p for p in v.splitlines() if len(p.strip()) >= 4]
        out.update(parts if len(parts) > 1 else [v])
    return out


@dataclass
class SecretIndex:
    """Per-file raw secret values of one project copy (memory only)."""
    by_file: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def scan(cls, root: Path) -> SecretIndex:
        collect: dict[str, set[str]] = {}
        scan_secrets(root, collect=collect)
        return cls({k: _split_values(v) for k, v in collect.items()})

    def all_values(self) -> set[str]:
        return {v for vs in self.by_file.values() for v in vs}

    def masked_lines(self, rel: str, text: str, masker: Masker | None = None) -> list[str]:
        values = self.by_file.get(rel, set())
        m = masker or Masker()
        return [m.mask(mask_in_text(line, values)) for line in text.splitlines()]


def numbered(lines: list[str], start: int, end: int) -> str:
    return "\n".join(f"{i:>5}| {lines[i - 1]}" for i in range(max(1, start), min(len(lines), end) + 1))


def enclosing_range(kf: KotlinFile, line: int, end_line: int) -> tuple[str, str, int, int] | None:
    """Innermost function, else innermost class containing the lines: (kind, name, start, end)."""
    best = None
    stack = [kf.root]
    while stack:
        n = stack.pop()
        for c in n.children:
            if node_line(c) <= line and node_end_line(c) >= end_line:
                if c.type in ENCLOSING_TYPES:
                    name = next((x.text.decode() for x in c.children if x.type in ("identifier", "type_identifier")),
                                "")
                    best = ("function" if c.type == "function_declaration" else "class", name, node_line(c),
                            node_end_line(c))
                stack.append(c)
    return best


def _window(lines: list[str], line: int, end_line: int, kf: KotlinFile | None) -> dict | None:
    if kf is None:
        return None
    enc = enclosing_range(kf, line, end_line)
    if enc is None:
        return None
    kind, name, s, e = enc
    if e - s + 1 > MAX_ENCLOSING_LINES:  # token limit: only the part around the finding
        s, e = max(s, line - MAX_ENCLOSING_LINES // 2), min(e, end_line + MAX_ENCLOSING_LINES // 2)
    return {"kind": kind, "name": name, "start_line": s, "end_line": e, "code": numbered(lines, s, e)}


def read_text(root: Path, rel: str) -> str | None:
    p = (root / rel).resolve()
    if not p.is_relative_to(root.resolve()) or not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def build_context(root: Path, finding: Finding, secrets: SecretIndex, masker: Masker | None = None) -> dict:
    text = read_text(root, finding.path)
    if text is None:
        raise FileNotFoundError(finding.path)
    lines = secrets.masked_lines(finding.path, text, masker)
    kf = KotlinFile.parse(finding.path, text) if finding.path.endswith((".kt", ".kts")) else None
    end = finding.end_line or finding.line
    ctx = {
        "rule": {"rule_id": finding.rule_id, "class": finding.cls, "category": finding.category,
                 "title": finding.title, "severity": finding.severity, "cwe": finding.cwe,
                 "description": (masker or Masker()).mask(finding.description),
                 "remediation": finding.remediation},
        "finding": {"file": finding.path, "start_line": finding.line, "end_line": end},
        "snippet": numbered(lines, finding.line - SNIPPET_RADIUS, end + SNIPPET_RADIUS),
        "enclosing": _window(lines, finding.line, end, kf),
        "related": [],
        "file_lines": len(lines),
    }
    budget = MAX_CONTEXT_CHARS - len(ctx["snippet"]) - len((ctx["enclosing"] or {}).get("code", ""))
    for loc in finding.alternate_locations:
        if loc.path == finding.path or budget <= 0:
            continue
        t = read_text(root, loc.path)
        if t is None:
            continue
        rl = secrets.masked_lines(loc.path, t, masker)
        rk = KotlinFile.parse(loc.path, t) if loc.path.endswith((".kt", ".kts")) else None
        w = _window(rl, loc.line, loc.end_line or loc.line, rk) or {
            "kind": "lines", "name": "", "start_line": max(1, loc.line - 5),
            "end_line": min(len(rl), (loc.end_line or loc.line) + 5),
            "code": numbered(rl, loc.line - 5, (loc.end_line or loc.line) + 5)}
        if len(w["code"]) > budget:
            break
        budget -= len(w["code"])
        ctx["related"].append({"file": loc.path, "file_lines": len(rl), **w})
    return ctx


def allowed_files(ctx: dict) -> dict[str, int]:
    """Files the LLM may patch → their line count (finding file + related files from the context)."""
    out = {ctx["finding"]["file"]: ctx["file_lines"]}
    for r in ctx["related"]:
        out[r["file"]] = r["file_lines"]
    return out
