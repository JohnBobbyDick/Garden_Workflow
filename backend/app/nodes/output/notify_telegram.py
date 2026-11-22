from __future__ import annotations

import json
import re

from app.config import get_settings
from app.core.ssrf import safe_request
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import credential, obj, prop
from app.notifications import build_content, split_message

TELEGRAM_LIMIT = 4096


class TelegramError(RuntimeError):
    pass


@register_node
class NotifyTelegram(BaseNode):
    type = "notify.telegram"
    category = "notify"
    icon = "send"
    title = {"ru": "Уведомление в Telegram", "en": "Telegram notification"}
    description = {
        "ru": "Сводка (критичность, главные находки, score, вывод AI) и файл report.md через Bot API. Длинные "
              "сообщения режутся по лимиту 4096 символов.",
        "en": "Summary (severity, top findings, score, AI summary) plus report.md via the Bot API. Long messages are "
              "split at the 4096-character limit."}
    inputs = [Port("in", "any", multiple=True, title_ru="Данные", title_en="Data")]
    outputs = [Port("out", "json", title_ru="Статус", title_en="Status")]
    config_schema = obj({
        "bot_token": credential("Токен бота", "Bot token", "telegram"),
        "chat_id": prop("string", "Получатель Telegram", "Telegram recipient",
                        "Введите числовой ID чата или @username публичного канала либо супергруппы. "
                        "Для личного чата отправьте боту /start, выберите его токен, введите свой @username "
                        "и нажмите «Найти Chat ID».",
                        "Enter a numeric chat ID or the @username of a public channel or supergroup. For a private "
                        "chat, send /start to the bot, select its token, enter your @username and click Find chat ID.",
                        minLength=1, **{"x-widget": "telegram-chat", "x-required-user-input": True}),
        "template": prop("string", "Шаблон сообщения", "Message template",
                         "Подстановки: {{findings.count}}, {{severity.critical}}, {{score.value}}, {{run.url}}…",
                         "Placeholders: {{findings.count}}, {{severity.critical}}, {{score.value}}, {{run.url}}…",
                         **{"x-widget": "template"}),
        "send_document": prop("boolean", "Прикладывать report.md", "Attach report.md", default=True),
    }, required=["bot_token", "chat_id"])

    async def execute(self, ctx, inputs, config):
        token = ctx.secret(config["bot_token"])
        settings = get_settings()
        base = f"{settings.telegram_api_base.rstrip('/')}/bot{token}"
        allow = settings.ssrf_allowed()
        content = build_content(ctx, inputs, config.get("template"))
        recipient = config["chat_id"].strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", recipient):
            recipient = "@" + recipient
        sent = 0
        try:
            for chunk in split_message(content.text, TELEGRAM_LIMIT):
                resp = await safe_request("POST", f"{base}/sendMessage", allow_hosts=allow,
                                          json={"chat_id": recipient, "text": chunk,
                                                "disable_web_page_preview": True})
                self._check(resp)
                sent += 1
            if config.get("send_document", True):
                files = {"document": ("report.md", content.markdown.encode("utf-8"), "text/markdown")}
                resp = await safe_request("POST", f"{base}/sendDocument", allow_hosts=allow,
                                          data={"chat_id": recipient,
                                                "caption": content.text.splitlines()[0][:1024]}, files=files)
                self._check(resp)
        except Exception as exc:
            ctx.services.add_notification(ctx.node_id, "telegram", "failed", ctx.masker.mask(str(exc))[:500])
            raise
        ctx.services.add_notification(ctx.node_id, "telegram", "delivered", f"сообщений: {sent}")
        ctx.log("info", f"Telegram: отправлено {sent} сообщений" + (" + report.md" if config.get("send_document", True)
                                                                     else ""))
        return {"out": Envelope.make("json", {"channel": "telegram", "status": "delivered", "messages": sent},
                                     ctx.node_id, "доставлено")}

    @staticmethod
    def _check(resp) -> None:  # noqa: ANN001
        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError):
            payload = {}
        if resp.status_code != 200 or not payload.get("ok"):
            detail = str(payload.get("description") or resp.text[:200])
            if resp.status_code == 400 and "chat not found" in detail.lower():
                detail += ". Проверьте Chat ID. Для личного чата отправьте боту /start, для группы добавьте в неё бота."
            raise TelegramError(f"Telegram API {resp.status_code}: {detail}")
