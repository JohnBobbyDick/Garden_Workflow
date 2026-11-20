from __future__ import annotations

from fastapi import APIRouter, Depends

from app import models as m
from app.deps import current_user
from app.nodes.base import CATEGORIES, PORT_TYPES, get_registry

router = APIRouter(tags=["nodes"])

CATEGORY_TITLES = {
    "trigger": {"ru": "Триггеры", "en": "Triggers"}, "source": {"ru": "Источник кода", "en": "Source"},
    "scanner": {"ru": "Сканеры", "en": "Scanners"}, "logic": {"ru": "Логика", "en": "Logic"},
    "analysis": {"ru": "Анализ", "en": "Analysis"}, "ai": {"ru": "AI", "en": "AI"},
    "output": {"ru": "Вывод", "en": "Output"}, "notify": {"ru": "Уведомления", "en": "Notifications"},
}


@router.get("/nodes")
def list_nodes(_: m.User = Depends(current_user)) -> dict:
    return {"nodes": [cls.spec() for cls in get_registry().all()], "port_types": list(PORT_TYPES),
            "categories": [{"id": c, "title": CATEGORY_TITLES[c]} for c in CATEGORIES]}
