from __future__ import annotations

from fastapi import APIRouter, Depends
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.core.errors import ApiError, conflict
from app.core.masking import global_masker
from app.deps import current_user, get_session, resolve_workspace
from app.nodes.base import CATEGORIES, PORT_TYPES, get_registry
from app.nodes.logic.map_fields import FIELDS, MapFields

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


class CustomNodeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    fields: dict[str, str] = Field(min_length=1, max_length=24)


def _definition(node: m.CustomNode) -> dict:
    return {"id": node.id, "name": node.name, "fields": node.fields}


@router.get("/nodes/custom")
def custom_nodes(workspace_id: str | None = None, user: m.User = Depends(current_user),
                 s: Session = Depends(get_session)) -> list[dict]:
    ws = resolve_workspace(s, user, workspace_id)
    rows = s.scalars(select(m.CustomNode).where(m.CustomNode.workspace_id == ws).order_by(m.CustomNode.name))
    return [_definition(row) for row in rows]


@router.post("/nodes/custom", status_code=201)
def create_custom_node(body: CustomNodeIn, workspace_id: str | None = None, user: m.User = Depends(current_user),
                       s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, workspace_id, "developer")
    name = body.name.strip()
    if not name or not Draft202012Validator(FIELDS).is_valid(body.fields):
        raise ApiError(422, "invalid_node_definition", "Проверьте имя ноды, имена полей и пути во входном JSON.")
    issues = MapFields.validate_config({"fields": body.fields})
    if issues:
        raise ApiError(422, "invalid_node_definition", issues[0])
    if any(global_masker.mask(v) != v for v in [name, *body.fields, *body.fields.values()]):
        raise ApiError(422, "invalid_node_definition", "Удалите секреты из определения ноды.")
    node = m.CustomNode(workspace_id=ws, name=name, fields=body.fields)
    s.add(node)
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        if s.scalar(select(m.CustomNode.id).where(m.CustomNode.workspace_id == ws, m.CustomNode.name == name)):
            raise conflict("В этом рабочем пространстве уже есть нода с таким названием.") from None
        raise
    return _definition(node)
