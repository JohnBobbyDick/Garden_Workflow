"""New/existing classification of a finished finding set against the change map (analyzers ran on full files).

SECRET/SAST: ``new`` if any line of ``[line, end_line]`` is in the file's ``new_lines``; cross-file findings
(IDOR etc.) are new if the diff touches the primary location or any ``alternate_location``. SCA goes through
``sca_diff`` (by versions). New findings get ``introduced_in_commit`` / ``author`` from blame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analyzers.common.finding import SEVERITY_ORDER, Finding
from app.analyzers.diff.git import DiffContext
from app.analyzers.diff.sca_diff import diff_sca


@dataclass
class DiffResult:
    new: list[Finding] = field(default_factory=list)
    existing: list[Finding] = field(default_factory=list)
    fixed_in_diff: list[dict] = field(default_factory=list)


def _touched(ctx: DiffContext, path: str, line: int, end_line: int | None) -> tuple[bool, str | None]:
    ch = ctx.changes.get(path)
    if ch is None or not ch.new_lines:
        return False, None
    end = end_line or line
    if any(ln in ch.new_lines for ln in range(line, end + 1)):
        h = ch.hunk_for(line, end)
        return True, h.header if h else None
    return False, None


def classify(findings: list[Finding], ctx: DiffContext, base_sca: list[Finding] | None = None,
             attribute: bool = True) -> DiffResult:
    res = DiffResult()
    sca_status, res.fixed_in_diff = diff_sca(findings, base_sca or [])
    for f in findings:
        g = f.model_copy(deep=True)
        if g.category == "SCA":
            st = sca_status.get(g.id, {"diff_status": "new", "version_changed": None})
            g.diff_status, g.version_changed = st["diff_status"], st["version_changed"]
            hit, hunk = _touched(ctx, g.path, g.line, g.end_line)
            g.diff_hunk = hunk if hit else None
        else:
            hit, hunk = _touched(ctx, g.path, g.line, g.end_line)
            if not hit:
                for loc in g.alternate_locations:
                    hit, hunk = _touched(ctx, loc.path, loc.line, loc.end_line)
                    if hit:
                        break
            g.diff_status, g.diff_hunk = ("new", hunk) if hit else ("existing", None)
        if g.diff_status == "new" and attribute:
            who = ctx.attribution(g.path, g.line)
            if who:
                g.introduced_in_commit, g.author = who
        (res.new if g.diff_status == "new" else res.existing).append(g)
    return res


def all_new(findings: list[Finding]) -> DiffResult:
    """``on_missing_diff = treat_all_as_new``."""
    res = DiffResult()
    for f in findings:
        g = f.model_copy(deep=True)
        g.diff_status = "new"
        res.new.append(g)
    return res


def verdict(res: DiffResult, threshold: str = "CRITICAL", report_only: bool = False) -> dict:
    thr = threshold.upper()
    counts = {s: 0 for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    for f in res.new:
        counts[f.severity] += 1
    blocking = [f for f in res.new if thr in SEVERITY_ORDER and SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER[thr]]
    would_fail = bool(blocking)
    out = {"verdict": "PASS" if report_only or not would_fail else "FAIL", "threshold": thr,
           "new_counts_by_severity": counts, "new_count": len(res.new), "existing_count": len(res.existing),
           "fixed_in_diff": res.fixed_in_diff, "report_only": report_only, "blocking_count": len(blocking)}
    if report_only and would_fail:
        out["would_fail_reason"] = f"{len(blocking)} новых находок уровня ≥ {thr}"
    return out
