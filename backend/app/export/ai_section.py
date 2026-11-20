"""AI section of the readable reports: explanations, fix diffs and the validator's trust indicator."""

from __future__ import annotations

from html import escape
from typing import Any

from app.analyzers.common.finding import Finding
from app.export.common import coordinates, location


def _where(f: Finding | None) -> str:
    if f is None:
        return "—"
    return coordinates(f) if f.category == "SCA" else location(f)


def trust_line(ai: dict[str, Any]) -> str:
    if not ai.get("ai_generated"):
        reason = ai.get("error") or "AI-провайдер не настроен"
        return f"отчёт сформирован детерминированно по данным анализаторов, без AI (ai_generated: false; {reason})"
    m = (ai.get("validation") or {}).get("metrics") or {}
    flags = (ai.get("validation") or {}).get("flags") or {}
    parts = [f"принято {m.get('valid_items', 0)} из {m.get('total_items', 0)} пунктов ответа",
             f"отброшено {m.get('dropped', 0)}", f"исправлений кода принято {m.get('fixes_kept', 0)}, "
             f"отброшено {m.get('fixes_dropped', 0)}"]
    if m.get("filled_deterministic"):
        parts.append(f"дополнено без AI: {m['filled_deterministic']}")
    if flags.get("hallucinated_ids"):
        parts.append(f"удалены выдуманные идентификаторы: {', '.join(m.get('hallucinated_ids', []))}")
    return "; ".join(parts)


def _title(ai: dict[str, Any]) -> str:
    return "AI-объяснение и рекомендации" if ai.get("ai_generated") else "Объяснение и рекомендации (без AI)"


def _diff(fix: dict) -> list[str]:
    out = [f"--- {fix['path']}:{fix['start_line']}-{fix['end_line']}"]
    out += [f"- {line}" for line in fix["before"].splitlines()]
    out += [f"+ {line}" for line in fix["after"].splitlines()]
    return out


def ai_markdown(ai: dict[str, Any], findings: list[Finding]) -> list[str]:
    report = ai.get("report") or {}
    by_id = {f.id: f for f in findings}
    model = f"{ai.get('provider')}/{ai.get('model')}" if ai.get("ai_generated") else "—"
    lines = [f"## {_title(ai)}", "", f"Модель: {model}", "", f"**Доверие к ответу:** {trust_line(ai)}", "",
             report.get("summary", ""), ""]
    order = [fid for fid in report.get("priority_order", []) if fid in by_id]
    if order:
        lines += ["### Порядок исправления", ""]
        lines += [f"{i}. {by_id[fid].severity} — {by_id[fid].title} ({_where(by_id[fid])})"
                  for i, fid in enumerate(order, 1)]
        lines.append("")
    items = [it for it in report.get("findings", []) if it.get("finding_id") in by_id]
    if items:
        lines += ["### По находкам", ""]
    for it in items:
        f = by_id[it["finding_id"]]
        src = " _(без AI)_" if it.get("source") == "deterministic" and ai.get("ai_generated") else ""
        lines += [f"#### {f.title} — `{_where(f)}`{src}", "", it.get("explanation", ""), "",
                  f"**Последствия:** {it.get('impact', '')}", "", "**Что сделать:**", ""]
        lines += [f"- {s}" for s in it.get("remediation_steps", [])]
        if it.get("safe_version"):
            lines += ["", f"**Безопасная версия:** {it['safe_version']}"]
        if it.get("fix"):
            lines += ["", "```diff", *_diff(it["fix"]), "```"]
        lines.append("")
    recs = report.get("global_recommendations") or []
    if recs:
        lines += ["### Общие рекомендации", ""] + [f"- {r}" for r in recs] + [""]
    return lines


def ai_html(ai: dict[str, Any], findings: list[Finding]) -> str:
    report = ai.get("report") or {}
    by_id = {f.id: f for f in findings}
    e = escape
    model = f"{ai.get('provider')}/{ai.get('model')}" if ai.get("ai_generated") else "—"
    parts = [f"<h2>{e(_title(ai))}</h2>", f'<p class="muted">Модель: {e(model)}</p>',
             f"<p><b>Доверие к ответу:</b> {e(trust_line(ai))}</p>", f"<p>{e(report.get('summary', ''))}</p>"]
    for it in report.get("findings", []):
        f = by_id.get(it.get("finding_id"))
        if f is None:
            continue
        parts.append(f"<h3>{e(f.title)} — <code>{e(_where(f))}</code></h3>")
        parts.append(f"<p>{e(it.get('explanation', ''))}</p><p><b>Последствия:</b> {e(it.get('impact', ''))}</p>")
        steps = "".join(f"<li>{e(s)}</li>" for s in it.get("remediation_steps", []))
        parts.append(f"<p><b>Что сделать:</b></p><ul>{steps}</ul>")
        if it.get("safe_version"):
            parts.append(f"<p><b>Безопасная версия:</b> {e(it['safe_version'])}</p>")
        if it.get("fix"):
            rows = "".join(f'<div class="{"del" if line.startswith("- ") else "add" if line.startswith("+ ") else "muted"}">'
                           f"{e(line)}</div>" for line in _diff(it["fix"]))
            parts.append(f'<pre class="diff">{rows}</pre>')
    recs = report.get("global_recommendations") or []
    if recs:
        parts.append("<h3>Общие рекомендации</h3><ul>" + "".join(f"<li>{e(r)}</li>" for r in recs) + "</ul>")
    return "".join(parts)


AI_CSS = """
pre.diff { font-family:ui-monospace, Menlo, Consolas, monospace; font-size:12px; border:1px solid var(--line);
  padding:8px; overflow-x:auto; }
pre.diff .del { color:#c0392b; } pre.diff .add { color:#2e8b57; }
h3 { font-size:15px; margin:18px 0 6px; }
"""
