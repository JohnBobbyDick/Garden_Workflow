from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

from app.config import get_settings
from app.core.ssrf import safe_request
from app.engine.data import summary_dict
from app.engine.templating import render_template
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import credential, obj, prop
from app.notifications import build_content

HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}


def masked_finding(f) -> dict:  # noqa: ANN001
    d = {"id": f.id, "category": f.category, "class": f.cls, "severity": f.severity, "title": f.title,
         "path": f.path, "line": f.line, "end_line": f.end_line, "confidence": f.confidence}
    if f.category == "SCA":
        d.update({"group": f.group, "artifact": f.artifact, "version": f.version, "advisory_id": f.advisory_id,
                  "fixed_versions": f.fixed_versions})
    if f.category == "SECRET":
        d["masked_value"] = f.masked_value
    if f.diff_status:
        d["diff_status"] = f.diff_status
    return d


@register_node
class NotifyWebhook(BaseNode):
    type = "notify.webhook"
    category = "notify"
    icon = "globe"
    title = {"ru": "HTTP Webhook", "en": "HTTP Webhook"}
    description = {
        "ru": "JSON со сводкой, маскированными находками и ссылками на экспорт; подпись HMAC-SHA256; защита от SSRF.",
        "en": "JSON with a summary, masked findings and export links; HMAC-SHA256 signature; SSRF protection."}
    inputs = [Port("in", "any", multiple=True, title_ru="Данные", title_en="Data")]
    outputs = [Port("out", "json", title_ru="Статус", title_en="Status")]
    config_schema = obj({
        "url": prop("string", "URL", "URL", minLength=8, **{"x-required-user-input": True}),
        "method": prop("string", "Метод", "Method", enum=["POST", "PUT"], default="POST"),
        "headers": prop("object", "Заголовки", "Headers", additionalProperties={"type": "string"}, default={},
                        **{"x-widget": "keyvalue"}),
        "secret_headers": prop("object", "Секретные заголовки (из хранилища)", "Secret headers (from vault)",
                               additionalProperties={"type": "string"}, default={},
                               **{"x-widget": "keyvalue-credential"}),
        "hmac_secret": credential("Секрет подписи HMAC", "HMAC signing secret", "webhook_secret"),
        "body_template": prop("string", "Шаблон тела (пусто — JSON по умолчанию)", "Body template (empty — default JSON)",
                              **{"x-widget": "textarea"}),
    }, required=["url"])

    async def execute(self, ctx, inputs, config):
        content = build_content(ctx, inputs)
        headers = {"Content-Type": "application/json", "User-Agent": "aisw-webhook/1"}
        for name, value in (config.get("headers") or {}).items():
            if HEADER_NAME.match(name) and name.lower() not in FORBIDDEN_HEADERS:
                headers[name] = str(value)
        for name, cred in (config.get("secret_headers") or {}).items():
            if HEADER_NAME.match(name) and name.lower() not in FORBIDDEN_HEADERS:
                headers[name] = ctx.secret(cred)
        if config.get("body_template"):
            body = ctx.masker.mask(render_template(config["body_template"], content.context)).encode("utf-8")
            headers["Content-Type"] = "text/plain; charset=utf-8"
        else:
            report = ctx.state.get("report") or {}
            doc = {
                "event": "aisw.run.report",
                "run": {"id": ctx.run.run_id, "url": ctx.run.run_url, "trigger": ctx.run.trigger_type},
                "workflow": ctx.run.workflow_name, "project": content.context["project"]["name"],
                "summary": summary_dict(content.findings),
                "findings": [masked_finding(f) for f in content.findings],
                "score": content.context["score"], "verdict": content.context["verdict"],
                "gate": content.context["gate"], "ai": content.context["ai"],
                "links": {"run": ctx.run.run_url,
                          "artifacts": report.get("artifacts") or [],
                          "submission_json": f"{ctx.run.run_url.replace('/runs/', '/api/runs/')}/export/submission.json"},
                "message": content.text,
            }
            body = ctx.masker.mask(json.dumps(doc, ensure_ascii=False)).encode("utf-8")
        if config.get("hmac_secret"):
            secret = ctx.secret(config["hmac_secret"]).encode("utf-8")
            ts = str(int(time.time()))
            headers["X-AISW-Timestamp"] = ts
            headers["X-AISW-Signature"] = "sha256=" + hmac.new(secret, ts.encode() + b"." + body,
                                                               hashlib.sha256).hexdigest()
        try:
            resp = await safe_request(config.get("method", "POST"), config["url"], headers=headers, content=body,
                                      allow_hosts=get_settings().ssrf_allowed())
            if resp.status_code >= 400:
                raise RuntimeError(f"получатель webhook ответил {resp.status_code}")
        except Exception as exc:
            ctx.services.add_notification(ctx.node_id, "webhook", "failed", ctx.masker.mask(str(exc))[:500])
            raise
        ctx.services.add_notification(ctx.node_id, "webhook", "delivered", f"HTTP {resp.status_code}")
        ctx.log("info", f"webhook доставлен: HTTP {resp.status_code}")
        return {"out": Envelope.make("json", {"channel": "webhook", "status": "delivered", "http_status": resp.status_code},
                                     ctx.node_id, f"HTTP {resp.status_code}")}
