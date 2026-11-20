from __future__ import annotations

from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import credential, obj, prop

EVENTS = ["push", "pull_request", "merge_request"]


@register_node
class WebhookTrigger(BaseNode):
    type = "trigger.webhook"
    category = "trigger"
    icon = "webhook"
    title = {"ru": "Webhook / CI", "en": "Webhook / CI"}
    description = {
        "ru": "Запуск из GitHub/GitLab (push, pull/merge request) по подписанному вебхуку или из CI через API.",
        "en": "Started by a signed GitHub/GitLab webhook (push, pull/merge request) or from CI via the API."}
    outputs = [Port("out", "trigger", title_ru="Событие", title_en="Event")]
    config_schema = obj({
        "provider": prop("string", "Провайдер", "Provider", enum=["github", "gitlab", "ci"], default="github"),
        "secret": credential("Секрет вебхука", "Webhook secret", "webhook_secret",
                             "Для проверки подписи X-Hub-Signature-256 / X-Gitlab-Token",
                             "Verifies X-Hub-Signature-256 / X-Gitlab-Token"),
        "events": prop("array", "События", "Events", items={"type": "string", "enum": EVENTS},
                       default=["push", "pull_request", "merge_request"]),
        "branches": prop("array", "Ветки (пусто — все)", "Branches (empty — all)", items={"type": "string"},
                         default=[]),
        "repo_url": prop("string", "Репозиторий (из allowlist)", "Repository (allowlisted)",
                         "Событие принимается только для этого репозитория", "Only events for this repository"),
    })

    async def execute(self, ctx, inputs, config):
        p = ctx.run.trigger_payload
        data = {"trigger_type": ctx.run.trigger_type, "provider": p.get("provider") or config.get("provider"),
                "event": p.get("event"), "ref": p.get("ref"), "head_sha": p.get("head_sha"),
                "base_sha": p.get("base_sha"), "base_ref": p.get("base_ref"), "pr_number": p.get("pr_number"), "repo": p.get("repo"),
                "source": p.get("source") or {}, "diff_context": p.get("diff_context")}
        return {"out": Envelope.make("trigger", data, ctx.node_id, f"{data['provider']}: {data['event'] or 'ci'}")}
