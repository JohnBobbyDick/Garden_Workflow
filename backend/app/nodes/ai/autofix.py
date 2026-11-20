from __future__ import annotations

from app.ai.providers.base import build_provider
from app.analyzers.common.finding import SEVERITY_ORDER
from app.autofix.service import AutofixError, generate_at
from app.engine.data import findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class AIAutofix(BaseNode):
    type = "ai.autofix"
    category = "ai"
    icon = "wrench"
    timeout_seconds = 1800
    title = {"ru": "AI AutoFix", "en": "AI AutoFix"}
    description = {
        "ru": "Готовит патч для найденных проблем: детерминированное обновление уязвимой зависимости или исправление "
              "от LLM. Каждый патч проходит валидатор (схема, совпадение с файлом, без секретов, синтаксис, "
              "самопроверка всеми анализаторами). По желанию открывает PR/MR — только в репозиторий с allow_write.",
        "en": "Prepares patches for detected problems: a deterministic vulnerable-dependency bump or an LLM fix. Every "
              "patch passes the validator (schema, file match, no secrets, syntax, self-check with all analyzers). "
              "Optionally opens a PR/MR — only for a repository with allow_write."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "json", title_ru="Результаты AutoFix", title_en="AutoFix results")]
    config_schema = obj({
        "auto_create_pr": prop("boolean", "Создавать PR/MR автоматически", "Open PR/MR automatically",
                               "только для validated и репозитория с allow_write", "validated fixes, allow_write only",
                               default=False),
        "max_findings": prop("integer", "Максимум находок", "Max findings", minimum=1, maximum=20, default=3),
        "min_severity": prop("string", "Минимальная критичность", "Minimum severity",
                             enum=["LOW", "MEDIUM", "HIGH", "CRITICAL"], default="HIGH"),
        "target_branch": prop("string", "Целевая ветка PR", "PR target branch", "пусто — base-ветка",
                              "empty — base branch"),
        "pr_template": prop("string", "Шаблон описания PR (добавляется в начало)", "PR description template (prepended)",
                            **{"x-widget": "textarea"}),
    })

    async def execute(self, ctx, inputs, config):
        root = (ctx.state.get("repo") or {}).get("root")
        if not root:
            raise ValueError("AutoFix требует исходники: подключите «Источник кода» перед анализаторами")
        min_rank = SEVERITY_ORDER[config.get("min_severity") or "HIGH"]
        candidates = sorted((f for f in findings_of(inputs["in"])
                             if f.autofix != "none" and f.severity_rank >= min_rank),
                            key=lambda f: (-f.severity_rank, -f.confidence, f.path, f.line))
        candidates = candidates[: int(config.get("max_findings") or 3)]
        cfg = ctx.services.ai_provider_config(None)
        provider = build_provider(cfg) if cfg is not None else None
        from pathlib import Path

        results = []
        for f in candidates:
            item = {"finding_id": f.id, "title": f.title, "status": "skipped", "reason": None, "patch": None,
                    "pr_url": None, "autofix_id": None}
            try:
                out = await generate_at(Path(root), f, provider, ctx.run.language)
            except AutofixError as exc:
                item["reason"] = exc.message
                results.append(item)
                ctx.log("warning", f"AutoFix {f.id}: {exc.message}")
                continue
            v = out.validation
            item.update(status=v.status, reason=ctx.masker.mask(v.reason) if v.reason else None,
                        patch=out.patch or None, autofix_id=ctx.services.save_autofix(ctx.node_id, f, out))
            ctx.log("info" if v.status == "validated" else "warning", f"AutoFix {f.id}: {v.status}"
                    + (f" — {item['reason']}" if item["reason"] else ""))
            if v.status == "validated" and config.get("auto_create_pr"):
                try:
                    item["pr_url"] = await ctx.services.create_autofix_pr(
                        item["autofix_id"], f, config.get("target_branch") or None, config.get("pr_template") or None)
                    ctx.log("info", f"AutoFix {f.id}: PR {item['pr_url']}")
                except Exception as exc:  # PR creation must not fail the analysis run
                    item["pr_error"] = ctx.masker.mask(str(exc))[:300]
                    ctx.log("warning", f"AutoFix {f.id}: PR не создан — {item['pr_error']}")
            results.append(item)
        ok = sum(1 for r in results if r["status"] == "validated")
        ctx.state["autofix"] = {"validated": ok, "total": len(results)}
        return {"out": Envelope.make("json", {"autofix": results, "validated": ok, "total": len(results)},
                                     ctx.node_id, f"{ok} из {len(results)} исправлений проверено")}
