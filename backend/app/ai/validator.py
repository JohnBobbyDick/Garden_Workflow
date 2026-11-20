"""Trust validation of LLM answers (prompt §11.3). Nothing an LLM says is stored or shown before this passes.

1. JSON + schema (the caller makes one repair attempt on failure);
2. every ``finding_id`` exists, no duplicates; unknown ids are dropped and counted;
3. ``fix.path``/lines refer to the finding (or its alternate locations) and ``fix.before`` literally matches the
   (masked) file text at those lines, whitespace-normalized; inline ``file:line`` references must exist;
4. CVE/GHSA ids must belong to (vulnerability database ∩ findings of this run), others are removed → flag
   ``hallucinated_ids``;
5. ``safe_version`` of SCA items must be one of the advisory's ``fixedVersions`` (corrected otherwise);
6. every step is recorded (accepted / corrected / dropped) with metrics for the UI "trust" indicator."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from app.ai.schemas import REPORT_SCHEMA
from app.analyzers.common.files import safe_file
from app.analyzers.common.finding import Finding
from app.analyzers.sca.versions import UnsupportedVersion, nearest_fixed_version

ADVISORY_RE = re.compile(r"\b(CVE-\d{4}-\d{4,}|GHSA(?:-[a-z0-9]{4}){3})\b", re.IGNORECASE)
REF_RE = re.compile(r"([\w./\-]+\.(?:kts|kt|java|ya?ml|properties|gradle|toml|json|xml|sql|lockfile)):(\d+)")
REMOVED_ID = "[идентификатор удалён валидатором]"
REMOVED_REF = "[ссылка удалена валидатором]"
MASK_ARTIFACT = "…(len="

FileReader = Callable[[str], list[str] | None]


class AIFormatError(ValueError):
    pass


@dataclass
class ValidationLog:
    checks: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)

    def add(self, check: str, status: str, details: str = "", **extra: Any) -> None:
        self.checks.append({"check": check, "status": status, "details": details, **extra})

    def to_dict(self) -> dict[str, Any]:
        return {"checks": self.checks, "metrics": self.metrics, "flags": self.flags}


def parse_json(text: str) -> dict:
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if fence:
        t = fence.group(1)
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            t = t[start:end + 1]
    try:
        data = json.loads(t)
    except json.JSONDecodeError as exc:
        raise AIFormatError(f"ответ не является JSON: {exc.msg} (позиция {exc.pos})") from exc
    if not isinstance(data, dict):
        raise AIFormatError("ответ должен быть JSON-объектом")
    return data


def schema_errors(data: dict, schema: dict = REPORT_SCHEMA) -> list[str]:
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))][:20]


def masked_file_reader(root: str | Path | None, findings: list[Finding]) -> FileReader:
    """Lines of a project file as the LLM saw them: secret lines replaced by the analyzers' masked snippets."""
    by_path: dict[str, list[Finding]] = {}
    for f in findings:
        by_path.setdefault(f.path, []).append(f)
    cache: dict[str, list[str] | None] = {}

    def read(path: str) -> list[str] | None:
        if path in cache:
            return cache[path]
        lines: list[str] | None = None
        if root is not None:
            p = safe_file(root, path)
            if p is not None:
                try:
                    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    lines = None
        if lines is None and path in by_path:
            size = max((f.end_line or f.line) for f in by_path[path])
            lines = [""] * size
        if lines is not None:
            for f in by_path.get(path, []):
                snip = f.snippet.split("\n") if f.snippet else []
                end = f.end_line or f.line
                if snip and len(snip) == end - f.line + 1 and end <= len(lines):
                    lines[f.line - 1:end] = snip
        cache[path] = lines
        return lines

    return read


def _norm(s: str) -> str:
    return " ".join(s.split())


def allowed_advisories(findings: list[Finding], db_ids: set[str] | None) -> set[str]:
    run_ids: set[str] = set()
    for f in findings:
        if f.advisory_id:
            run_ids.add(f.advisory_id.upper())
        run_ids.update(a.upper() for a in f.aliases)
    return run_ids if db_ids is None else run_ids & {i.upper() for i in db_ids}


def _scrub_ids(text: str, allowed: set[str], found: list[str]) -> str:
    def repl(m: re.Match) -> str:
        if m.group(1).upper() in allowed:
            return m.group(1)
        found.append(m.group(1))
        return REMOVED_ID
    return ADVISORY_RE.sub(repl, text)


def _scrub_refs(text: str, known: dict[str, int | None], bad: list[str]) -> str:
    def repl(m: re.Match) -> str:
        path, line = m.group(1), int(m.group(2))
        size = next((v for k, v in known.items() if k == path or k.endswith("/" + path)), -1)
        if size == -1 or (size is not None and not 1 <= line <= size):
            bad.append(m.group(0))
            return REMOVED_REF
        return m.group(0)
    return REF_RE.sub(repl, text)


def validate_report(data: dict, findings: list[Finding], read: FileReader, allowed_ids: set[str]
                    ) -> tuple[dict, ValidationLog]:
    log = ValidationLog()
    errors = schema_errors(data)
    if errors:
        raise AIFormatError("ответ не соответствует схеме: " + "; ".join(errors[:5]))
    log.add("schema", "ok")
    data = deepcopy(data)
    by_id = {f.id: f for f in findings}
    items_in = data.get("findings", [])
    kept: list[dict] = []
    unknown: list[str] = []
    dup = 0
    seen: set[str] = set()
    for it in items_in:
        fid = it.get("finding_id")
        if fid not in by_id:
            unknown.append(str(fid))
            continue
        if fid in seen:
            dup += 1
            continue
        seen.add(fid)
        kept.append({k: it[k] for k in ("finding_id", "explanation", "impact", "remediation_steps", "safe_version",
                                         "fix") if k in it and it[k] is not None})
    order = []
    for fid in data.get("priority_order", []):
        if fid in by_id and fid not in order:
            order.append(fid)
        elif fid not in by_id:
            unknown.append(str(fid))
    log.add("finding_ids", "dropped" if unknown or dup else "ok",
            f"неизвестных id: {len(set(unknown))}, дубликатов: {dup}", unknown=sorted(set(unknown)))

    # fixes
    fixes_kept = fixes_dropped = 0
    reasons: list[dict] = []
    for it in kept:
        fix = it.get("fix")
        if not fix:
            continue
        f = by_id[it["finding_id"]]
        allowed_paths = {f.path, *(a.path for a in f.alternate_locations)}
        reason = None
        if fix["path"] not in allowed_paths:
            reason = "файл не относится к находке"
        else:
            lines = read(fix["path"])
            s, e = fix["start_line"], fix["end_line"]
            if lines is None:
                reason = "файл недоступен"
            elif not (1 <= s <= e <= len(lines)) or e - s > 40:
                reason = "строки вне файла"
            elif _norm("\n".join(lines[s - 1:e])) != _norm(fix["before"]):
                reason = "before не совпадает с текстом файла"
            elif MASK_ARTIFACT in fix["after"]:
                reason = "after содержит маску секрета"
        if reason:
            it.pop("fix")
            fixes_dropped += 1
            reasons.append({"finding_id": f.id, "reason": reason})
        else:
            fixes_kept += 1
    log.add("fixes", "dropped" if fixes_dropped else "ok", f"принято {fixes_kept}, отброшено {fixes_dropped}",
            reasons=reasons)

    # advisory ids
    hallucinated: list[str] = []

    def scrub(text: str) -> str:
        return _scrub_ids(text, allowed_ids, hallucinated)

    data["summary"] = scrub(data.get("summary", ""))
    data["global_recommendations"] = [scrub(x) for x in data.get("global_recommendations", [])]
    for it in kept:
        for k in ("explanation", "impact"):
            if k in it:
                it[k] = scrub(it[k])
        it["remediation_steps"] = [scrub(x) for x in it.get("remediation_steps", [])]
        if "fix" in it:
            it["fix"]["after"] = scrub(it["fix"]["after"])
    log.add("advisory_ids", "dropped" if hallucinated else "ok",
            f"удалено непроверенных идентификаторов: {len(hallucinated)}", removed=hallucinated)

    # safe versions
    corrected = 0
    for it in kept:
        f = by_id[it["finding_id"]]
        if f.category != "SCA":
            it.pop("safe_version", None)
            continue
        sv = it.get("safe_version")
        if f.fixed_versions and sv not in f.fixed_versions:
            try:
                best = nearest_fixed_version(f.version or "", f.fixed_versions) or f.fixed_versions[0]
            except (UnsupportedVersion, ValueError):
                best = f.fixed_versions[0]
            if sv:
                corrected += 1
            it["safe_version"] = best
    log.add("safe_versions", "corrected" if corrected else "ok", f"исправлено версий: {corrected}")

    # inline references
    known: dict[str, int | None] = {}
    for f in findings:
        for p in {f.path, *(a.path for a in f.alternate_locations)}:
            lines = read(p)
            known[p] = len(lines) if lines is not None else None
    bad: list[str] = []
    data["summary"] = _scrub_refs(data["summary"], known, bad)
    for it in kept:
        for k in ("explanation", "impact"):
            if k in it:
                it[k] = _scrub_refs(it[k], known, bad)
        it["remediation_steps"] = [_scrub_refs(x, known, bad) for x in it["remediation_steps"]]
    log.add("references", "dropped" if bad else "ok", f"удалено ссылок: {len(bad)}", removed=bad)

    report = {"summary": data["summary"], "priority_order": order, "findings": kept,
              "global_recommendations": data["global_recommendations"]}
    log.metrics = {"total_items": len(items_in), "valid_items": len(kept), "dropped": len(items_in) - len(kept),
                   "unknown_ids": sorted(set(unknown)), "duplicates": dup, "fixes_kept": fixes_kept,
                   "fixes_dropped": fixes_dropped, "hallucinated_ids": hallucinated,
                   "safe_version_corrected": corrected, "bad_references": len(bad),
                   "covered_findings": len(kept), "input_findings": len(findings)}
    log.flags = {"hallucinated_ids": bool(hallucinated), "corrected": bool(corrected or bad or fixes_dropped
                                                                           or unknown or dup)}
    return report, log
