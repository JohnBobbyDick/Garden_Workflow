from __future__ import annotations

from app.ai.pool import canonical_provider
from app.ai.providers.base import build_provider
from app.ai.report_service import generate_report
from app.ai.validator import masked_file_reader
from app.engine.data import findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import credential, obj, prop


@register_node
class AIReport(BaseNode):
    type = "ai.report"
    category = "ai"
    icon = "sparkles"
    timeout_seconds = 900
    title = {"ru": "AI-объяснение", "en": "AI explanation"}
    description = {
        "ru": "LLM объясняет уже найденные анализаторами проблемы простым языком, оценивает последствия и предлагает "
              "исправления (diff). Ответ проходит валидатор достоверности; без AI — детерминированный отчёт с пометкой.",
        "en": "The LLM explains findings already detected by our analyzers in plain words, assesses impact and "
              "suggests fixes (diff). The answer passes the trust validator; without AI a marked deterministic report "
              "is produced."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "report", title_ru="AI-отчёт", title_en="AI report")]
    config_schema = obj({
        "provider": prop("string", "Провайдер (пусто — из настроек workspace)", "Provider (empty — workspace settings)",
                         enum=["", "nvidia", "ollama"], default=""),
        "base_url": prop("string", "Адрес сервера Ollama", "Ollama server URL"),
        "model": prop("string", "Модель Ollama", "Ollama model"),
        "api_key": credential("API-ключ провайдера", "Provider API key", "llm_api_key"),
        "language": prop("string", "Язык отчёта", "Report language", "auto — язык интерфейса пользователя",
                         "auto — user's interface language", enum=["auto", "ru", "en"], default="auto"),
        "generate_fix_diff": prop("boolean", "Предлагать исправления (diff)", "Suggest fixes (diff)", default=True),
        "fallback_to_deterministic": prop("boolean", "Отчёт без AI при недоступности LLM",
                                          "Deterministic report if the LLM is unavailable", default=True),
        "max_findings": prop("integer", "Максимум находок для AI", "Max findings for AI", minimum=1, maximum=200,
                             default=60),
    })

    @classmethod
    def validate_config(cls, config):
        provider = config.get("provider")
        if provider and not canonical_provider(provider, config.get("base_url") or "", config.get("model") or ""):
            return ["выберите NVIDIA Nemotron 3.5 Lightning или Ollama"]
        if provider == "ollama" and not (config.get("base_url") and config.get("model")):
            return ["для переопределения провайдера укажите base_url и модель"]
        return []

    async def execute(self, ctx, inputs, config):
        findings = findings_of(inputs["in"])
        override = {k: config.get(k) for k in ("provider", "base_url", "model", "api_key")} \
            if config.get("provider") else None
        cfg = ctx.services.ai_provider_config(override)
        provider = build_provider(cfg) if cfg is not None else None
        language = ctx.run.language if config.get("language", "auto") == "auto" else config["language"]
        repo = ctx.state.get("repo") or {}
        read = masked_file_reader(repo.get("root"), findings)
        allowed = {f.advisory_id for f in findings if f.advisory_id} | {a for f in findings for a in f.aliases}
        outcome = await generate_report(findings, provider, read=read, allowed_ids=allowed, masker=ctx.masker,
                                        language=language, generate_fix_diff=bool(config.get("generate_fix_diff", True)),
                                        fallback=bool(config.get("fallback_to_deterministic", True)),
                                        project=repo.get("project_name") or ctx.run.project_name or "project",
                                        max_findings=int(config.get("max_findings") or 60))
        report_id = ctx.services.save_ai_report(ctx.node_id, "report", outcome)
        ctx.state["ai"] = {"summary": outcome.report.get("summary", ""), "ai_generated": outcome.ai_generated}
        m = outcome.validation.get("metrics", {})
        if outcome.ai_generated:
            ctx.log("info", f"AI-отчёт {outcome.provider}/{outcome.model}: принято {m.get('valid_items')} из "
                            f"{m.get('total_items')}, выдуманных id: {len(m.get('hallucinated_ids', []))}")
        else:
            ctx.log("warning", f"AI недоступен, сформирован отчёт без AI: {outcome.error}")
        data = {"report": outcome.report, "ai_generated": outcome.ai_generated, "validation": outcome.validation,
                "provider": outcome.provider, "model": outcome.model, "error": outcome.error,
                "ai_report_id": report_id, "language": outcome.language}
        summary = "AI-отчёт" if outcome.ai_generated else "отчёт без AI"
        return {"out": Envelope.make("report", data, ctx.node_id, summary)}
