from __future__ import annotations

from app.engine.data import findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop
from app.scoring.formula import compute_score, score_params
from app.scoring.priority import priority_list


@register_node
class SecurityScore(BaseNode):
    type = "analysis.security_score"
    category = "analysis"
    icon = "scale"
    title = {"ru": "Security Score", "en": "Security Score"}
    description = {
        "ru": "Детерминированная оценка 0–100: штраф по критичности и новизне находок, нормированный на размер "
              "проекта; дельта к прошлому запуску и Priority Fix List. Для if_else (score.value, score.delta) и "
              "шаблонов уведомлений. Метрика внутреннего тренда, не рейтинг между проектами.",
        "en": "Deterministic 0–100 score: penalty by severity and novelty normalized by project size; delta to the "
              "previous run and the Priority Fix List. Feeds if_else (score.value, score.delta) and notification "
              "templates. An internal trend metric, not a cross-project rating."}
    inputs = [Port("findings", "findings", title_ru="Находки", title_en="Findings"),
              Port("repo", "repo", required=False, title_ru="Код (LOC)", title_en="Code (LOC)")]
    outputs = [Port("out", "json", title_ru="Score", title_en="Score")]
    config_schema = obj({
        "top_n": prop("integer", "Размер Priority Fix List", "Priority Fix List size", minimum=1, maximum=50,
                      default=10),
    })

    async def execute(self, ctx, inputs, config):
        findings = findings_of(inputs["findings"])
        repo = inputs["repo"].data if "repo" in inputs else (ctx.state.get("repo") or {})
        loc = int(repo.get("loc") or 0)
        settings = ctx.services.workspace_settings() if ctx.has_services else {}
        params = score_params(settings)
        res = compute_score(findings, loc, params)
        signature = ctx.state.get("scanner_set", "")
        prev = ctx.services.previous_score(signature) if ctx.has_services and signature else None
        delta = res.score - prev if prev is not None else None
        top = priority_list(findings, loc, params, language=ctx.run.language)[: int(config.get("top_n", 10))]
        data = {"value": res.score, "delta": delta, "penalty": res.penalty, "scale": res.scale, "loc": loc,
                "formula_version": res.formula_version, "breakdown": res.breakdown, "priority": top}
        ctx.state["score"] = data
        ctx.log("info", f"Security Score {res.score}/100" + (f" ({delta:+d})" if delta is not None else ""))
        return {"out": Envelope.make("json", data, ctx.node_id,
                                     f"{res.score}/100" + (f" ({delta:+d})" if delta is not None else ""))}
