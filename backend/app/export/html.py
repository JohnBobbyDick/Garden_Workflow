"""Self-contained HTML report (Russian): inline CSS, no scripts, no external resources."""

from __future__ import annotations

from html import escape

from app.analyzers.common.finding import Finding
from app.export.ai_section import AI_CSS, ai_html
from app.export.common import (
    CATEGORY_ORDER,
    CATEGORY_TITLES,
    SEVERITY_LEVELS,
    coordinates,
    location,
    one_line,
    report_order,
    secret_display,
    severity_label,
    shorten,
    summary,
)

_CSS = """
:root { color-scheme: light dark; --bg:#fff; --fg:#1d1f23; --muted:#5f6670; --line:#d9dde3; --head:#f3f5f8; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181c; --fg:#e6e8eb; --muted:#9aa2ad; --line:#2f343b; --head:#1f2328; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
  font:14px/1.5 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
main { max-width:1200px; margin:0 auto; }
h1 { font-size:24px; margin:0 0 16px; }
h2 { font-size:18px; margin:28px 0 10px; }
.table-wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; margin:8px 0; }
th, td { border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { background:var(--head); font-weight:600; }
td.loc, td.mono { font-family:ui-monospace, Menlo, Consolas, monospace; font-size:12px; word-break:break-all; }
.muted { color:var(--muted); }
.sev { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px; font-weight:600; white-space:nowrap; }
.sev-critical { background:#7a1020; color:#fff; }
.sev-high { background:#c0392b; color:#fff; }
.sev-medium { background:#e6a23c; color:#1d1f23; }
.sev-low { background:#4a90d9; color:#fff; }
"""


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _sev(severity: str) -> str:
    return f'<span class="sev sev-{_e(severity.lower())}">{_e(severity_label(severity))}</span>'


def _table(header: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(rows_cell for rows_cell in r) + "</tr>" for r in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _td(value: object, css: str = "") -> str:
    cls = f' class="{css}"' if css else ""
    return f"<td{cls}>{_e(value) if value != '' else '—'}</td>"


def _category_table(category: str, items: list[Finding]) -> str:
    if category == "SCA":
        header = ["Категория", "Название", "Описание", "Файл объявления", "Зависимость", "Уязвимость", "Серьёзность"]
        rows = [
            [
                _td(f.category), _td(f.title), _td(shorten(f.description)), _td(location(f), "loc"),
                _td(coordinates(f), "mono"), _td(f.advisory_id or "", "mono"), f"<td>{_sev(f.severity)}</td>",
            ]
            for f in items
        ]
    elif category == "SECRET":
        header = ["Категория", "Название", "Класс", "Описание", "Расположение", "Значение (маскировано)", "Серьёзность"]
        rows = [
            [
                _td(f.category), _td(f.title), _td(f.cls, "mono"), _td(shorten(f.description)), _td(location(f), "loc"),
                _td(secret_display(f), "mono"), f"<td>{_sev(f.severity)}</td>",
            ]
            for f in items
        ]
    else:
        header = ["Категория", "Название", "Класс", "Описание", "Расположение", "Серьёзность"]
        rows = [
            [
                _td(f.category), _td(f.title), _td(f.cls, "mono"), _td(shorten(f.description)), _td(location(f), "loc"),
                f"<td>{_sev(f.severity)}</td>",
            ]
            for f in items
        ]
    return _table(header, rows)


def render_html(findings: list[Finding], project_name: str, meta: dict | None = None, ai: dict | None = None) -> str:
    title = f"Отчёт анализа безопасности: {one_line(project_name)}"
    parts: list[str] = [f"<h1>{_e(title)}</h1>"]

    if meta:
        parts.append("<h2>Параметры анализа</h2>")
        parts.append(_table(["Параметр", "Значение"], [[_td(k), _td(v)] for k, v in meta.items()]))

    by_category, by_severity = summary(findings)
    parts.append("<h2>Сводка</h2>")
    parts.append(f"<p>Всего находок: {len(findings)}</p>")
    if not findings:
        parts.append('<p class="muted">Находок нет.</p>')
    else:
        parts.append(_table(["Категория", "Количество"], [[_td(c), _td(by_category.get(c, 0))] for c in CATEGORY_ORDER]))
        parts.append(
            _table(["Серьёзность", "Количество"], [[f"<td>{_sev(s)}</td>", _td(by_severity.get(s, 0))] for s in SEVERITY_LEVELS])
        )
        if ai:
            parts.append(ai_html(ai, findings))
        ordered = report_order(findings)
        for category in CATEGORY_ORDER:
            items = [f for f in ordered if f.category == category]
            parts.append(f"<h2>{_e(CATEGORY_TITLES[category])}</h2>")
            parts.append(_category_table(category, items) if items else '<p class="muted">Находок нет.</p>')

    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n<style>{_CSS}{AI_CSS if ai else ""}</style>\n</head>\n"
        f"<body>\n<main>\n{''.join(parts)}\n</main>\n</body>\n</html>\n"
    )
