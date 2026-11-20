"""Evaluation of the analyzers against expected-findings files (organizer ground truth format)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.common.finding import Finding


@dataclass
class EvalReport:
    dataset: str
    matched: list[tuple[str, str]] = field(default_factory=list)   # (expected id, finding id)
    missed: list[dict] = field(default_factory=list)
    control_hits: list[tuple[str, Finding]] = field(default_factory=list)
    extras: list[Finding] = field(default_factory=list)

    @property
    def recall(self) -> float:
        total = len(self.matched) + len(self.missed)
        return len(self.matched) / total if total else 1.0

    @property
    def precision(self) -> float:
        total = len(self.matched) + len(self.extras) + len(self.control_hits)
        return len(self.matched) / total if total else 1.0

    def summary(self) -> str:
        lines = [f"[{self.dataset}] recall {self.recall:.2%} ({len(self.matched)}/{len(self.matched) + len(self.missed)}), "
                 f"precision {self.precision:.2%}, controls hit {len(self.control_hits)}, extras {len(self.extras)}"]
        lines += [f"  MISSED {m['id']} {m['category']} {m.get('class')} {m['path']}:{m.get('line')}" for m in self.missed]
        lines += [f"  CONTROL {cid} hit by {f.cls} {f.path}:{f.line}" for cid, f in self.control_hits]
        lines += [f"  EXTRA {f.category} {f.cls} {f.path}:{f.line}-{f.end_line} {f.title}" for f in self.extras]
        return "\n".join(lines)


def _ranges(entry: dict) -> list[tuple[str, int, int]]:
    out = [(entry["path"], entry["line"], entry.get("endLine") or entry["line"])]
    for a in entry.get("alternateLocations") or []:
        out.append((a["path"], a["line"], a.get("endLine") or a["line"]))
    return out


def _line_match(f: Finding, entry: dict) -> bool:
    for path, lo, hi in _ranges(entry):
        if f.path == path and lo <= f.line <= hi:
            return True
    return False


def _classes(entry: dict) -> set[str]:
    return {entry.get("class"), *(entry.get("classAliases") or [])} - {None}


def _matches(f: Finding, entry: dict) -> bool:
    if f.category != entry["category"]:
        return False
    if f.category == "SCA":
        ids = set(entry.get("advisoryIds") or []) | ({entry["advisoryId"]} if entry.get("advisoryId") else set())
        return (f.group, f.artifact, f.version) == (entry["group"], entry["artifact"], entry["version"]) and \
            f.advisory_id in ids
    return f.cls in _classes(entry) and _line_match(f, entry)


def _control_hit(f: Finding, ctl: dict) -> bool:
    if f.category != ctl["category"]:
        return False
    if f.category == "SCA":
        return (f.group, f.artifact, f.version) == (ctl.get("group"), ctl.get("artifact"), ctl.get("version"))
    lo, hi = ctl["line"], ctl.get("endLine") or ctl["line"]
    end = f.end_line or f.line
    return f.path == ctl["path"] and f.line <= hi and end >= lo


def evaluate(findings: list[Finding], expected_path: Path, dataset: str | None = None,
             explained_extra: set[str] | None = None) -> EvalReport:
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    rep = EvalReport(dataset or data.get("dataset", expected_path.stem))
    used: set[str] = set()
    for entry in data["findings"]:
        hit = next((f for f in findings if f.id not in used and _matches(f, entry)), None)
        if hit is None:
            rep.missed.append(entry)
        else:
            used.add(hit.id)
            rep.matched.append((entry["id"], hit.id))
    for f in findings:
        if f.id in used:
            continue
        ctl = next((c for c in data.get("controls", []) if _control_hit(f, c)), None)
        if ctl is not None:
            rep.control_hits.append((ctl["id"], f))
        elif not explained_extra or f.rule_id not in explained_extra:
            rep.extras.append(f)
    return rep
