import csv
import io
from hashlib import sha256

from app.engine.data import findings_of, summary_dict
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


def _cell(text: str) -> str:
    if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@register_node
class FindingsCsv(BaseNode):
    type = "output.findings_csv"
    category = "output"
    icon = "file-down"
    title = {"ru": "Таблица находок CSV", "en": "Findings CSV"}
    description = {"ru": "Сохраняет входной набор находок в артефакт CSV для электронных таблиц. Включает ID, правило, критичность и расположение.",
                   "en": "Exports the input findings to a spreadsheet-ready CSV artifact with IDs, rules, severities and locations."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "report", title_ru="Файл CSV", title_en="CSV report")]
    config_schema = obj({"delimiter": prop("string", "Разделитель", "Delimiter", enum=[",", ";"], default=",")})

    async def execute(self, ctx, inputs, config):
        findings = findings_of(inputs["in"])
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter=config["delimiter"])
        writer.writerow(["id", "category", "rule_id", "severity", "confidence", "path", "line", "end_line", "title"])
        for f in findings:
            row = [f.id, f.category, f.rule_id, f.severity, f.confidence, f.path, f.line, f.end_line, f.title]
            writer.writerow([_cell(ctx.masker.mask(v)) if isinstance(v, str) else v for v in row])
        # Artifact names are unique within a run. Different CSV nodes may receive different subsets.
        name = f"findings-{sha256(ctx.node_id.encode()).hexdigest()[:16]}.csv"
        mime = "text/csv; charset=utf-8"
        url = ctx.services.save_artifact(ctx.node_id, name, buffer.getvalue().encode("utf-8-sig"), mime)
        data = {"exported": len(findings), "summary": summary_dict(findings),
                "artifacts": [{"name": name, "url": url, "content_type": mime}]}
        return {"out": Envelope.make("report", data, ctx.node_id, f"CSV · {len(findings)}")}
