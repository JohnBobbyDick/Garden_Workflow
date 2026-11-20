"""Tiny helpers for writing node ``config_schema`` (JSON Schema + UI hints, RU/EN labels).

UI hints understood by the editor form generator:
``x-title-en`` / ``x-description-en`` (English labels; ``title``/``description`` are Russian),
``x-widget``: ``credential`` | ``cron`` | ``expression`` | ``textarea`` | ``template`` | ``keyvalue`` | ``password``,
``x-credential-kind``: hint for the credential selector, ``credential_ref: true``: value is a credential id,
``x-required-user-input: true``: must be filled by the user (AI generation / templates highlight it)."""

from __future__ import annotations

from typing import Any


def prop(type_: str | list, ru: str, en: str, desc_ru: str = "", desc_en: str = "", **extra: Any) -> dict[str, Any]:
    p: dict[str, Any] = {"type": type_, "title": ru, "x-title-en": en}
    if desc_ru:
        p["description"] = desc_ru
    if desc_en:
        p["x-description-en"] = desc_en
    p.update(extra)
    return p


def credential(ru: str, en: str, kind: str, desc_ru: str = "", desc_en: str = "") -> dict[str, Any]:
    return prop("string", ru, en, desc_ru, desc_en, credential_ref=True, **{"x-widget": "credential",
                                                                           "x-credential-kind": kind})


def obj(properties: dict[str, dict], required: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        s["required"] = required
    s.update(extra)
    return s


SEVERITY_ENUM = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
