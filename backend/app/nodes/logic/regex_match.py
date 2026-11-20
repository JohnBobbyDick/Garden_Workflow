from __future__ import annotations

import asyncio

import regex

from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop

MAX_PATTERN = 500
MAX_INPUT = 1_000_000
FLAG_MAP = {"i": regex.IGNORECASE, "m": regex.MULTILINE, "s": regex.DOTALL}


class RegexTimeout(Exception):
    pass


def _compile(pattern: str, flags: str) -> regex.Pattern:
    if len(pattern) > MAX_PATTERN:
        raise ValueError(f"шаблон длиннее {MAX_PATTERN} символов")
    f = 0
    for ch in flags or "":
        if ch not in FLAG_MAP:
            raise ValueError(f"неизвестный флаг «{ch}»")
        f |= FLAG_MAP[ch]
    return regex.compile(pattern, f)


def _search(p: regex.Pattern, text: str, timeout: float):
    try:
        return p.search(text[:MAX_INPUT], timeout=timeout)
    except TimeoutError as exc:
        raise RegexTimeout("превышено время выполнения регулярного выражения (защита от ReDoS)") from exc


def _findall(p: regex.Pattern, text: str, timeout: float) -> list[str]:
    try:
        return [m.group(0) for m in p.finditer(text[:MAX_INPUT], timeout=timeout)][:1000]
    except TimeoutError as exc:
        raise RegexTimeout("превышено время выполнения регулярного выражения (защита от ReDoS)") from exc


@register_node
class RegexNode(BaseNode):
    type = "logic.regex"
    category = "logic"
    icon = "regex"
    title = {"ru": "Регулярное выражение", "en": "Regular expression"}
    description = {
        "ru": "match — есть ли совпадение; extract — извлечь совпадения; filter — оставить находки/строки, поле "
              "которых совпадает. Таймаут и лимит длины защищают от катастрофического бэктрекинга.",
        "en": "match — whether it matches; extract — pull matches; filter — keep findings/lines whose field matches. "
              "A timeout and length limits protect from catastrophic backtracking."}
    inputs = [Port("in", "any", title_ru="Данные", title_en="Data")]
    outputs = [Port("out", "any", title_ru="Результат", title_en="Result")]
    config_schema = obj({
        "pattern": prop("string", "Шаблон", "Pattern", minLength=1, maxLength=MAX_PATTERN),
        "flags": prop("string", "Флаги (i, m, s)", "Flags (i, m, s)", default="", pattern="^[ims]*$"),
        "field": prop("string", "Поле", "Field", "Для находок: path, class, title, description, snippet…",
                      "For findings: path, class, title, description, snippet…", default="path"),
        "mode": prop("string", "Режим", "Mode", enum=["match", "extract", "filter"], default="match"),
        "timeout_ms": prop("integer", "Таймаут, мс", "Timeout, ms", minimum=10, maximum=5000, default=500),
    }, required=["pattern"])

    @classmethod
    def validate_config(cls, config):
        try:
            _compile(str(config.get("pattern") or ""), str(config.get("flags") or ""))
        except (regex.error, ValueError) as exc:
            return [f"некорректное регулярное выражение: {exc}"]
        return []

    async def execute(self, ctx, inputs, config):
        env: Envelope = inputs["in"]
        p = _compile(config["pattern"], config.get("flags", ""))
        timeout = config.get("timeout_ms", 500) / 1000
        field = config.get("field") or "path"
        mode = config.get("mode", "match")
        if "findings" in env.data:
            fs = findings_of(env)
            values = [(f, str(f.model_dump(by_alias=True).get(field) or "")) for f in fs]
        else:
            text = str(env.data.get(field if field in env.data else "text", "")) if env.type != "json" else \
                str(env.data.get(field, env.data))
            values = [(line, line) for line in text.splitlines()] if mode == "filter" else [(text, text)]

        def work():
            if mode == "filter":
                return [obj_ for obj_, v in values if _search(p, v, timeout)]
            if mode == "extract":
                out: list[str] = []
                for _, v in values:
                    out.extend(_findall(p, v, timeout))
                return out
            return any(_search(p, v, timeout) for _, v in values)

        result = await asyncio.to_thread(work)
        if mode == "filter":
            if "findings" in env.data:
                return {"out": findings_envelope(result, ctx.node_id)}
            return {"out": Envelope.make("text", {"text": "\n".join(result)}, ctx.node_id, f"{len(result)} строк")}
        if mode == "extract":
            return {"out": Envelope.make("json", {"matches": result, "count": len(result)}, ctx.node_id,
                                         f"{len(result)} совпадений")}
        return {"out": Envelope.make("json", {"matched": result}, ctx.node_id, "совпало" if result else "нет")}
