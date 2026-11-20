from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop

DAILY = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@register_node
class ScheduleTrigger(BaseNode):
    type = "trigger.schedule"
    category = "trigger"
    icon = "clock"
    title = {"ru": "По расписанию", "en": "Schedule"}
    description = {"ru": "Запуск по cron-выражению или ежедневно в заданное время (часовой пояс настраивается).",
                   "en": "Runs on a cron expression or every day at HH:MM (timezone configurable)."}
    outputs = [Port("out", "trigger", title_ru="Старт", title_en="Start")]
    config_schema = obj({
        "cron": prop("string", "Cron-выражение", "Cron expression", "Например «0 14 * * *» — каждый день в 14:00",
                     "E.g. '0 14 * * *' — every day at 14:00", **{"x-widget": "cron"}),
        "daily_at": prop("string", "Каждый день в (ЧЧ:ММ)", "Every day at (HH:MM)", pattern=r"^\d{1,2}:\d{2}$"),
        "timezone": prop("string", "Часовой пояс", "Timezone", "Пусто — часовой пояс рабочего пространства",
                         "Empty — workspace timezone"),
    })

    @staticmethod
    def cron_of(config: dict) -> str | None:
        if config.get("cron"):
            return str(config["cron"]).strip()
        m = DAILY.match(str(config.get("daily_at") or ""))
        if m:
            return f"{int(m.group(2))} {int(m.group(1))} * * *"
        return None

    @classmethod
    def validate_config(cls, config):
        errors = []
        if config.get("daily_at") and not DAILY.match(str(config["daily_at"])):
            errors.append("время должно быть в формате ЧЧ:ММ (00:00–23:59)")
        cron = cls.cron_of(config)
        if cron is None:
            if not errors:
                errors.append("укажите cron-выражение или время ежедневного запуска")
        elif not croniter.is_valid(cron) or len(cron.split()) != 5:
            errors.append(f"некорректное cron-выражение «{cron}» (нужно 5 полей)")
        tz = config.get("timezone")
        if tz:
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                errors.append(f"неизвестный часовой пояс «{tz}»")
        return errors

    async def execute(self, ctx, inputs, config):
        payload = {"trigger_type": "schedule", "cron": self.cron_of(config), "slot": ctx.run.trigger_payload.get("slot"),
                   "source": ctx.run.trigger_payload.get("source") or {}}
        return {"out": Envelope.make("trigger", payload, ctx.node_id, f"расписание {payload['cron']}")}
