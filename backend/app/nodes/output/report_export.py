from __future__ import annotations

import json

from app.analyzers.common.finding import Finding
from app.engine.data import findings_of, summary_dict
from app.export.html import render_html
from app.export.markdown import render_markdown
from app.export.submission_json import OFFICIAL_MIN_CONFIDENCE, to_submission
from app.export.validator import validate_submission
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop

FORMATS = ["submission_json", "markdown", "html"]
FILES = {"submission_json": ("submission.json", "application/json"), "markdown": ("report.md", "text/markdown"),
         "html": ("report.html", "text/html")}


class ExportValidationError(ValueError):
    pass


def report_findings(findings: list[Finding], min_confidence: float, include_transitive: bool) -> list[Finding]:
    return [f for f in findings if f.confidence >= min_confidence
            and (include_transitive or f.scope != "transitive")]


def build_reports(findings, project_name: str, min_confidence: float, include_transitive: bool,
                  ai_report: dict | None = None, meta: dict | None = None) -> dict[str, str]:
    """Render the official JSON (validated) and the readable Markdown/HTML from the same finding set."""
    doc = to_submission(findings, min_confidence=min_confidence, include_transitive=include_transitive)
    errors = validate_submission(doc)
    if errors:
        raise ExportValidationError("submission.json не прошёл валидацию формата: " + "; ".join(errors[:5]))
    shown = report_findings(findings, min_confidence, include_transitive)
    hidden = len(findings) - len(shown)
    meta = dict(meta or {})
    meta["Порог уверенности"] = f"{min_confidence:g}"
    if hidden:
        meta["Находок ниже порога (видны в интерфейсе)"] = str(hidden)
    md = render_markdown(shown, project_name, meta, ai_report)
    html = render_html(shown, project_name, meta, ai_report)
    return {"submission_json": json.dumps(doc, ensure_ascii=False, indent=2) + "\n", "markdown": md, "html": html}


@register_node
class ReportExport(BaseNode):
    type = "output.report_export"
    category = "output"
    icon = "file-down"
    title = {"ru": "Экспорт отчёта", "en": "Report export"}
    description = {
        "ru": "Формирует submission.json (официальный формат, проверяется валидатором), report.md и report.html "
              "из одного набора находок и сохраняет их в артефакты запуска.",
        "en": "Builds submission.json (official format, validated), report.md and report.html from the same finding "
              "set and stores them as run artifacts."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings"),
              Port("ai", "report", required=False, title_ru="AI-отчёт", title_en="AI report")]
    outputs = [Port("out", "report", title_ru="Отчёт", title_en="Report")]
    config_schema = obj({
        "formats": prop("array", "Форматы", "Formats", items={"type": "string", "enum": FORMATS}, default=FORMATS,
                        uniqueItems=True, minItems=1),
        "min_confidence": prop("number", "Порог уверенности", "Confidence threshold", minimum=0, maximum=1,
                               default=OFFICIAL_MIN_CONFIDENCE),
        "include_transitive": prop("boolean", "Включать транзитивные SCA", "Include transitive SCA", default=False),
    })

    async def execute(self, ctx, inputs, config):
        findings = findings_of(inputs["in"])
        ai = inputs["ai"].data if "ai" in inputs else None
        project = ctx.run.project_name or (ctx.state.get("repo") or {}).get("project_name") or "project"
        meta = {"Запуск": ctx.run.run_id, "Сценарий": ctx.run.workflow_name or "—"}
        min_confidence = float(config["min_confidence"])
        include_transitive = bool(config.get("include_transitive"))
        reports = build_reports(findings, project, min_confidence, include_transitive, ai, meta)
        reports = {k: ctx.masker.mask(v) for k, v in reports.items()}
        artifacts = []
        for fmt in config["formats"]:
            name, ctype = FILES[fmt]
            url = ctx.services.save_artifact(ctx.node_id, name, reports[fmt].encode("utf-8"), ctype)
            artifacts.append({"name": name, "url": url, "content_type": ctype})
        exported = len(json.loads(reports["submission_json"])["findings"])
        data = {"artifacts": artifacts, "summary": summary_dict(findings), "exported": exported,
                "project_name": project}
        saved = {"markdown": reports["markdown"], "html": reports["html"], "artifacts": artifacts,
                 "findings": report_findings(findings, min_confidence, include_transitive)}
        ctx.state.setdefault("reports_by_node", {})[ctx.node_id] = saved
        ctx.state["report"] = saved
        ctx.log("info", f"экспортировано {exported} находок: {', '.join(a['name'] for a in artifacts)}")
        return {"out": Envelope.make("report", data, ctx.node_id, f"{len(artifacts)} файла, {exported} находок")}
