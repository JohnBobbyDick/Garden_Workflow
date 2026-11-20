"""Validator for the organizer submission JSON format.

Usage: ``python -m app.export.validator report.json`` — exits 0 when valid, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.export.common import CATEGORY_ORDER, MAX_RANGE_LINES, path_problem

OPTIONAL_STRINGS: tuple[str, ...] = ("severity", "description", "remediation")
SCA_REQUIRED: tuple[str, ...] = ("group", "artifact", "version", "advisoryId")


def _reject_constant(name: str) -> Any:
    raise ValueError(f"недопустимое значение {name}")


def _is_json_int(value: object) -> bool:
    return type(value) is int


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "логическое значение"
    if isinstance(value, int):
        return "целое число"
    if isinstance(value, float):
        return "дробное число"
    if isinstance(value, str):
        return "строка"
    if isinstance(value, list):
        return "массив"
    if isinstance(value, dict):
        return "объект"
    return type(value).__name__


def _check_required_string(item: dict, key: str, where: str, errors: list[str]) -> None:
    if key not in item:
        errors.append(f"{where}: отсутствует обязательное поле '{key}'")
        return
    value = item[key]
    if not isinstance(value, str):
        errors.append(f"{where}: поле '{key}' должно быть строкой, получено: {_type_name(value)}")
    elif not value.strip():
        errors.append(f"{where}: поле '{key}' должно содержать хотя бы один непробельный символ")


def _check_lines(item: dict, where: str, errors: list[str]) -> None:
    if "line" not in item:
        errors.append(f"{where}: отсутствует обязательное поле 'line'")
        line = None
    else:
        line = item["line"]
        if not _is_json_int(line):
            errors.append(f"{where}: поле 'line' должно быть целым числом JSON, получено: {_type_name(line)} ({line!r})")
            line = None
        elif line < 1:
            errors.append(f"{where}: поле 'line' должно быть не меньше 1, получено: {line}")
            line = None
    if "endLine" not in item:
        return
    end = item["endLine"]
    if not _is_json_int(end):
        errors.append(f"{where}: поле 'endLine' должно быть целым числом JSON, получено: {_type_name(end)} ({end!r})")
        return
    if line is None:
        return
    if end < line:
        errors.append(f"{where}: 'endLine' ({end}) меньше 'line' ({line})")
    elif end > line + MAX_RANGE_LINES - 1:
        errors.append(
            f"{where}: 'endLine' ({end}) превышает 'line' + {MAX_RANGE_LINES - 1} ({line + MAX_RANGE_LINES - 1}); "
            f"диапазон должен быть от 1 до {MAX_RANGE_LINES} строк"
        )


def _check_finding(item: object, index: int, errors: list[str]) -> None:
    where = f"findings[{index}]"
    if not isinstance(item, dict):
        errors.append(f"{where}: находка должна быть объектом, получено: {_type_name(item)}")
        return

    category = item.get("category")
    if "category" not in item:
        errors.append(f"{where}: отсутствует обязательное поле 'category'")
    elif category not in CATEGORY_ORDER:
        errors.append(f"{where}: поле 'category' должно быть одним из SECRET, SAST, SCA, получено: {category!r}")

    if "path" not in item:
        errors.append(f"{where}: отсутствует обязательное поле 'path'")
    else:
        problem = path_problem(item["path"])
        if problem:
            errors.append(f"{where}: недопустимый 'path' {item['path']!r}: {problem}")

    for key in OPTIONAL_STRINGS:
        if key in item:
            value = item[key]
            if not isinstance(value, str):
                errors.append(f"{where}: поле '{key}' должно быть строкой, получено: {_type_name(value)}")
            elif not value.strip():
                errors.append(f"{where}: поле '{key}' пустое; необязательные поля без данных нужно опускать")

    if category in ("SECRET", "SAST"):
        _check_required_string(item, "class", where, errors)
        _check_lines(item, where, errors)
    elif category == "SCA":
        for key in SCA_REQUIRED:
            if key == "advisoryId" and isinstance(item.get(key), list):
                errors.append(f"{where}: поле 'advisoryId' должно быть одной строкой, а не массивом")
                continue
            if key == "advisoryId" and key not in item and "advisoryIds" in item:
                errors.append(
                    f"{where}: отсутствует обязательное поле 'advisoryId'; массив 'advisoryIds' относится к эталону"
                )
                continue
            _check_required_string(item, key, where, errors)


def validate_submission(data: dict | str) -> list[str]:
    """Validate a submission document (parsed or JSON text). Returns error messages; empty means valid."""
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data, parse_constant=_reject_constant)
        except (ValueError, UnicodeDecodeError) as exc:
            return [f"Некорректный JSON: {exc}"]

    if not isinstance(data, dict):
        return [f"Корень документа должен быть объектом, получено: {_type_name(data)}"]
    if "findings" not in data:
        return ["В корне отсутствует обязательный массив 'findings'"]
    findings = data["findings"]
    if not isinstance(findings, list):
        return [f"Поле 'findings' должно быть массивом, получено: {_type_name(findings)}"]

    errors: list[str] = []
    for index, item in enumerate(findings):
        _check_finding(item, index, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Использование: python -m app.export.validator <report.json>", file=sys.stderr)
        return 1
    path = Path(args[0])
    try:
        raw = path.read_bytes()
    except OSError as exc:
        print(f"Не удалось прочитать файл {path}: {exc}", file=sys.stderr)
        return 1
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"Файл {path} не в кодировке UTF-8: {exc}", file=sys.stderr)
        return 1
    errors = validate_submission(text)
    if errors:
        print(f"{path}: найдено ошибок: {len(errors)}")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"{path}: формат корректен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
