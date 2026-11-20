"""Readable Markdown report (Russian)."""

from __future__ import annotations

from app.analyzers.common.finding import Finding
from app.export.ai_section import ai_markdown
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


def cell(value: object) -> str:
    """Make a value safe for a Markdown table cell: one line, escaped pipes."""
    text = one_line(str(value)).replace("\\", "\\\\").replace("|", "\\|")
    return text or "—"


def _row(cells: list[object]) -> str:
    return "| " + " | ".join(cell(c) for c in cells) + " |"


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    lines = [_row(list(header)), "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend(_row(r) for r in rows)
    return lines


def _category_rows(category: str, items: list[Finding]) -> tuple[list[str], list[list[object]]]:
    if category == "SCA":
        header = ["Категория", "Название", "Описание", "Файл объявления", "Зависимость", "Уязвимость", "Серьёзность"]
        rows = [
            [f.category, f.title, shorten(f.description), location(f), coordinates(f), f.advisory_id or "", severity_label(f.severity)]
            for f in items
        ]
    elif category == "SECRET":
        header = ["Категория", "Название", "Класс", "Описание", "Расположение", "Значение (маскировано)", "Серьёзность"]
        rows = [
            [f.category, f.title, f.cls, shorten(f.description), location(f), secret_display(f), severity_label(f.severity)]
            for f in items
        ]
    else:
        header = ["Категория", "Название", "Класс", "Описание", "Расположение", "Серьёзность"]
        rows = [
            [f.category, f.title, f.cls, shorten(f.description), location(f), severity_label(f.severity)] for f in items
        ]
    return header, rows


def render_markdown(findings: list[Finding], project_name: str, meta: dict | None = None,
                    ai: dict | None = None) -> str:
    lines: list[str] = [f"# Отчёт анализа безопасности: {one_line(project_name)}", ""]

    if meta:
        lines += ["## Параметры анализа", ""]
        lines += _table(["Параметр", "Значение"], [[k, v] for k, v in meta.items()])
        lines.append("")

    by_category, by_severity = summary(findings)
    lines += ["## Сводка", "", f"Всего находок: {len(findings)}", ""]
    if not findings:
        lines += ["Находок нет.", ""]
        return "\n".join(lines)

    lines += _table(["Категория", "Количество"], [[c, by_category.get(c, 0)] for c in CATEGORY_ORDER])
    lines.append("")
    lines += _table(["Серьёзность", "Количество"], [[s, by_severity.get(s, 0)] for s in SEVERITY_LEVELS])
    lines.append("")

    if ai:
        lines += ai_markdown(ai, findings)

    ordered = report_order(findings)
    for category in CATEGORY_ORDER:
        items = [f for f in ordered if f.category == category]
        lines += [f"## {CATEGORY_TITLES[category]}", ""]
        if not items:
            lines += ["Находок нет.", ""]
            continue
        header, rows = _category_rows(category, items)
        lines += _table(header, rows)
        lines.append("")

    return "\n".join(lines)
