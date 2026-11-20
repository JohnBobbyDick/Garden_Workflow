from __future__ import annotations

import socket
from email.message import EmailMessage
from email.utils import make_msgid

import aiosmtplib

from app.config import get_settings
from app.core.ssrf import check_url
from app.engine.templating import render_template
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import credential, obj, prop
from app.notifications import build_content, html_letter


@register_node
class NotifySmtp(BaseNode):
    type = "notify.smtp"
    category = "notify"
    icon = "mail"
    title = {"ru": "Письмо (SMTP)", "en": "E-mail (SMTP)"}
    description = {
        "ru": "HTML-письмо со сводкой и таблицей находок, вложения report.html и report.md. TLS / STARTTLS.",
        "en": "HTML e-mail with a summary and findings table, report.html and report.md attached. TLS / STARTTLS."}
    inputs = [Port("in", "any", multiple=True, title_ru="Данные", title_en="Data")]
    outputs = [Port("out", "json", title_ru="Статус", title_en="Status")]
    config_schema = obj({
        "host": prop("string", "SMTP-сервер", "SMTP host", minLength=1, **{"x-required-user-input": True}),
        "port": prop("integer", "Порт", "Port", minimum=1, maximum=65535, default=587),
        "security": prop("string", "Шифрование", "Security", enum=["starttls", "tls", "none"], default="starttls"),
        "username": prop("string", "Пользователь", "Username"),
        "password": credential("Пароль", "Password", "smtp"),
        "from_addr": prop("string", "От кого", "From", minLength=3, **{"x-required-user-input": True}),
        "to": prop("array", "Кому", "To", items={"type": "string", "minLength": 3}, minItems=1,
                   **{"x-required-user-input": True}),
        "subject": prop("string", "Тема", "Subject", default="AI Security Workflow: {{findings.count}} находок "
                                                             "({{workflow.name}})", **{"x-widget": "template"}),
        "template": prop("string", "Шаблон текста", "Body template", **{"x-widget": "template"}),
    }, required=["host", "from_addr", "to"])

    async def execute(self, ctx, inputs, config):
        settings = get_settings()
        host, port = config["host"], int(config.get("port") or 587)
        check_url(f"http://{host}:{port}/", settings.ssrf_allowed())  # same internal-network policy as HTTP
        password = ctx.secret(config["password"]) if config.get("password") else None
        content = build_content(ctx, inputs, config.get("template"))
        msg = EmailMessage()
        msg["Subject"] = ctx.masker.mask(render_template(config.get("subject") or "", content.context))[:250]
        msg["From"] = config["from_addr"]
        msg["To"] = ", ".join(config["to"])
        msg["Message-ID"] = make_msgid(domain="aisw.local")
        msg.set_content(content.text)
        msg.add_alternative(html_letter(content), subtype="html")
        msg.add_attachment(content.html_report.encode("utf-8"), maintype="text", subtype="html",
                           filename="report.html")
        msg.add_attachment(content.markdown.encode("utf-8"), maintype="text", subtype="markdown",
                           filename="report.md")
        security = config.get("security", "starttls")
        try:
            await aiosmtplib.send(msg, hostname=host, port=port, use_tls=security == "tls",
                                  start_tls=security == "starttls",
                                  username=config.get("username") or None, password=password, timeout=30,
                                  local_hostname=socket.gethostname())  # avoid slow reverse-DNS getfqdn()
        except Exception as exc:
            ctx.services.add_notification(ctx.node_id, "smtp", "failed", ctx.masker.mask(str(exc))[:500])
            raise
        ctx.services.add_notification(ctx.node_id, "smtp", "delivered", f"получателей: {len(config['to'])}")
        ctx.log("info", f"письмо отправлено: {len(config['to'])} получателей")
        return {"out": Envelope.make("json", {"channel": "smtp", "status": "delivered", "recipients": len(config["to"])},
                                     ctx.node_id, "доставлено")}
