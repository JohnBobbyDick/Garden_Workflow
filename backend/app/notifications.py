"""Shared content of notifications: every channel carries the report, not just "scan finished"."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from app.analyzers.common.finding import SEVERITY_ORDER, Finding
from app.engine.context import NodeContext
from app.engine.data import build_context, findings_of, flatten_inputs, summary_dict
from app.engine.templating import render_template
from app.export.common import coordinates, location
from app.export.submission_json import OFFICIAL_MIN_CONFIDENCE
from app.nodes.output.report_export import build_reports

TEXT = {
    "ru": {
        "title": "🔐 AI Security Workflow — отчёт о проверке",
        "default": ("{{workflow.name}}\nПроект: {{project.name}}\n"
                    "Найдено находок: {{findings.count}} (CRITICAL {{severity.critical}}, HIGH {{severity.high}}, "
                    "MEDIUM {{severity.medium}}, LOW {{severity.low}})"),
        "top": "Главные находки:", "score": "Security Score", "ai": "Вывод AI", "det": "Вывод (без AI)",
        "link": "Подробнее", "none": "Находок нет 🎉", "verdict": "Вердикт diff", "gate": "CI gate",
    },
    "en": {
        "title": "🔐 AI Security Workflow — scan report",
        "default": ("{{workflow.name}}\nProject: {{project.name}}\n"
                    "Findings: {{findings.count}} (CRITICAL {{severity.critical}}, HIGH {{severity.high}}, "
                    "MEDIUM {{severity.medium}}, LOW {{severity.low}})"),
        "top": "Top findings:", "score": "Security Score", "ai": "AI summary", "det": "Summary (no AI)",
        "link": "Details", "none": "No findings 🎉", "verdict": "Diff verdict", "gate": "CI gate",
    },
}


@dataclass
class NotificationContent:
    findings: list[Finding]
    context: dict[str, Any]
    text: str          # plain text summary (template + top findings + score + AI + link)
    markdown: str      # report.md
    html_report: str   # report.html
    lang: str

    def t(self, key: str) -> str:
        return TEXT[self.lang][key]


def finding_line(f: Finding) -> str:
    where = coordinates(f) if f.category == "SCA" else location(f)
    adv = f" {f.advisory_id}" if f.advisory_id else ""
    return f"{f.severity} · {f.category} {f.cls} — {where}{adv}"


def top_findings(findings: list[Finding], n: int = 5) -> list[Finding]:
    return sorted(findings, key=lambda f: (-SEVERITY_ORDER[f.severity], f.category, f.path, f.line))[:n]


def build_content(ctx: NodeContext, inputs: dict[str, Any], template: str | None = None) -> NotificationContent:
    lang = ctx.run.language if ctx.run.language in TEXT else "ru"
    envs = flatten_inputs(inputs)
    exports = ctx.state.get("reports_by_node", {})
    export = next((e for e in reversed(envs) if e.type == "report" and e.meta.node_id in exports), None)
    report = exports[export.meta.node_id] if export else None
    finding_inputs = [e for e in envs if "findings" in e.data]
    if report is None and not finding_inputs:
        report = ctx.state.get("report")
    findings = report["findings"] if report else findings_of(finding_inputs)
    c = build_context(inputs, ctx.run, ctx.state, findings=findings)
    tt = TEXT[lang]
    head = render_template(template or tt["default"], c).strip()
    lines = [tt["title"], "", head, ""]
    official = findings if report else [f for f in findings if f.confidence >= OFFICIAL_MIN_CONFIDENCE]
    if official:
        lines.append(tt["top"])
        lines += [f"• {finding_line(f)}" for f in top_findings(official)]
    elif not findings:
        lines.append(tt["none"])
    if c["score"]["value"] is not None:
        delta = c["score"]["delta"]
        lines += ["", f"{tt['score']}: {c['score']['value']}/100" + (f" ({delta:+d})" if delta is not None else "")]
    if c["verdict"]:
        lines.append(f"{tt['verdict']}: {c['verdict']}")
    if c["gate"]:
        lines.append(f"{tt['gate']}: {c['gate']}")
    ai = ctx.state.get("ai") or {}
    if ai.get("summary") and ai["summary"] not in head:
        lines += ["", f"{tt['ai'] if ai.get('ai_generated', True) else tt['det']}: {ai['summary']}"]
    lines += ["", f"{tt['link']}: {ctx.run.run_url}"]
    if report and report.get("markdown"):
        md, html = report["markdown"], report["html"]
    else:
        project = ctx.run.project_name or (ctx.state.get("repo") or {}).get("project_name") or "project"
        rep = build_reports(findings, project, OFFICIAL_MIN_CONFIDENCE, False, None, {"Запуск": ctx.run.run_id})
        md, html = rep["markdown"], rep["html"]
    m = ctx.masker
    return NotificationContent(findings, c, m.mask("\n".join(lines)), m.mask(md), m.mask(html), lang)


def html_letter(content: NotificationContent) -> str:
    """HTML e-mail body: summary + findings table (masked)."""
    rows = []
    for f in top_findings([f for f in content.findings if f.confidence >= OFFICIAL_MIN_CONFIDENCE], 50):
        where = coordinates(f) if f.category == "SCA" else location(f)
        rows.append(f"<tr><td>{escape(f.severity)}</td><td>{escape(f.category)}</td><td>{escape(f.cls)}</td>"
                    f"<td>{escape(f.title)}</td><td><code>{escape(where)}</code></td>"
                    f"<td>{escape(f.advisory_id or '')}</td></tr>")
    s = summary_dict(content.findings)
    sev = " · ".join(f"{k}: {v}" for k, v in sorted(s["by_severity"].items(), key=lambda kv: -SEVERITY_ORDER[kv[0]]))
    summary_html = "<br>".join(escape(line) for line in content.text.splitlines())
    table = ("<table border='1' cellpadding='4' cellspacing='0' style='border-collapse:collapse'>"
             "<thead><tr><th>Severity</th><th>Category</th><th>Class</th><th>Title</th><th>Location</th>"
             "<th>Advisory</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>") if rows else ""
    return (
        "<!doctype html><html><body style='font-family:Arial,sans-serif'>"
        f"<h2>{escape(content.t('title'))}</h2><p>{summary_html}</p>"
        f"<p><b>{len(content.findings)}</b> — {escape(sev)}</p>{table}</body></html>")


def split_message(text: str, limit: int = 4096) -> list[str]:
    """Split on line boundaries so every chunk fits the channel limit (hard-cut overlong lines)."""
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks or [""]
