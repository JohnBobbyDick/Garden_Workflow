from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models as m
from app.core.audit import audit
from app.core.errors import ApiError, bad_request, forbidden, not_found
from app.deps import client_ip, current_user, get_session, load_scoped, resolve_workspace
from app.engine.scheduler import sync_schedules
from app.nodes.base import get_registry
from app.templates_lib import TemplateParamError, apply_parameters, sanitize_graph

router = APIRouter(prefix="/templates", tags=["templates"])
CATEGORY_RE = "^(" + "|".join(c.replace("/", "\\/") for c in m.TEMPLATE_CATEGORIES) + ")$"


class PublishIn(BaseModel):
    workflow_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="Custom", pattern=CATEGORY_RE)
    tags: list[str] = Field(default_factory=list, max_length=20)
    version: str = Field(default="1.0.0", max_length=32)


class UpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, pattern=CATEGORY_RE)
    tags: list[str] | None = None
    version: str | None = Field(default=None, max_length=32)
    published: bool | None = None
    workflow_id: str | None = None


class UseIn(BaseModel):
    workspace_id: str | None = None
    name: str | None = Field(default=None, max_length=200)
    params: dict = Field(default_factory=dict)
    project_id: str | None = None


class RateIn(BaseModel):
    stars: int = Field(ge=1, le=5)


class ReviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class HideIn(BaseModel):
    hidden: bool


def _visible(t: m.Template, user: m.User) -> bool:
    return (t.published and not t.hidden) or t.author_id == user.id or user.is_platform_admin


def _get(s: Session, tid: str, user: m.User) -> m.Template:
    t = s.get(m.Template, tid)
    if t is None or not _visible(t, user):
        raise not_found("шаблон")
    return t


def template_out(s: Session, t: m.Template, user: m.User, full: bool = False) -> dict:
    fav = s.scalars(select(m.TemplateFavorite).where(m.TemplateFavorite.template_id == t.id,
                                                     m.TemplateFavorite.user_id == user.id)).first() is not None
    d = {"id": t.id, "name": t.name, "description": t.description, "category": t.category, "tags": t.tags,
         "version": t.version, "author_name": t.author_name, "author_id": t.author_id, "builtin": t.builtin,
         "usage_count": t.usage_count, "rating_avg": round(t.rating_avg, 2), "rating_count": t.rating_count,
         "published": t.published, "hidden": t.hidden, "favorite": fav, "mine": t.author_id == user.id,
         "node_types": sorted({n.get("type") for n in (t.graph or {}).get("nodes", [])}),
         "created_at": t.created_at, "updated_at": t.updated_at}
    if full:
        mine = s.scalars(select(m.TemplateRating).where(m.TemplateRating.template_id == t.id,
                                                        m.TemplateRating.user_id == user.id)).first()
        d.update({"graph": t.graph, "parameters": t.parameters, "my_rating": mine.stars if mine else None})
    return d


@router.get("")
def list_templates(q: str | None = None, category: str | None = None, min_rating: float | None = None,
                   author: str | None = None, favorites: bool = False, mine: bool = False, sort: str = "new",
                   user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    stmt = select(m.Template)
    if mine:
        stmt = stmt.where(m.Template.author_id == user.id)
    else:
        stmt = stmt.where(m.Template.published.is_(True), m.Template.hidden.is_(False))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(m.Template.name).like(like), func.lower(m.Template.description).like(like)))
    if category:
        stmt = stmt.where(m.Template.category == category)
    if min_rating is not None:
        stmt = stmt.where(m.Template.rating_avg >= min_rating)
    if author:
        stmt = stmt.where(m.Template.author_name == author)
    if favorites:
        stmt = stmt.join(m.TemplateFavorite, m.TemplateFavorite.template_id == m.Template.id).where(
            m.TemplateFavorite.user_id == user.id)
    order = {"popular": m.Template.usage_count.desc(), "rating": m.Template.rating_avg.desc()}.get(
        sort, m.Template.created_at.desc())
    rows = list(s.scalars(stmt.order_by(order, m.Template.created_at.desc())))
    if q:  # tags are JSON: match in Python so search covers name, description and tags
        ql = q.lower()
        extra = s.scalars(select(m.Template).where(m.Template.published.is_(True), m.Template.hidden.is_(False)))
        ids = {t.id for t in rows}
        rows += [t for t in extra if t.id not in ids and any(ql in str(tag).lower() for tag in (t.tags or []))]
    return {"templates": [template_out(s, t, user) for t in rows], "categories": list(m.TEMPLATE_CATEGORIES)}


@router.post("", status_code=201)
def publish(body: PublishIn, request: Request, user: m.User = Depends(current_user),
            s: Session = Depends(get_session)) -> dict:
    wf = load_scoped(s, m.Workflow, body.workflow_id, user, "developer", "сценарий")
    graph, params = sanitize_graph(wf.graph, get_registry())
    t = m.Template(name=body.name, description=body.description, category=body.category,
                   tags=[x.strip()[:40] for x in body.tags if x.strip()], version=body.version, author_id=user.id,
                   author_name=user.display_name or user.email.split("@")[0], source_workspace_id=wf.workspace_id,
                   graph=graph, parameters=params)
    s.add(t)
    audit(s, "template.publish", user_id=user.id, workspace_id=wf.workspace_id, target=body.name,
          details={"version": body.version, "parameters": [p["name"] for p in params]}, ip=client_ip(request))
    s.commit()
    return template_out(s, t, user, full=True)


@router.get("/{tid}")
def get_template(tid: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return template_out(s, _get(s, tid, user), user, full=True)


@router.put("/{tid}")
def update_template(tid: str, body: UpdateIn, request: Request, user: m.User = Depends(current_user),
                    s: Session = Depends(get_session)) -> dict:
    t = _get(s, tid, user)
    if t.author_id != user.id:
        raise forbidden("изменять шаблон может только автор")
    for k in ("name", "description", "category", "tags", "version", "published"):
        v = getattr(body, k)
        if v is not None:
            setattr(t, k, v)
    if body.workflow_id:
        wf = load_scoped(s, m.Workflow, body.workflow_id, user, "developer", "сценарий")
        t.graph, t.parameters = sanitize_graph(wf.graph, get_registry())
    audit(s, "template.update", user_id=user.id, workspace_id=t.source_workspace_id, target=t.name,
          details=body.model_dump(exclude_none=True), ip=client_ip(request))
    s.commit()
    return template_out(s, t, user, full=True)


@router.post("/{tid}/hide")
def hide_template(tid: str, body: HideIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    if not user.is_platform_admin:
        raise forbidden("скрывать шаблоны может только администратор платформы")
    t = s.get(m.Template, tid)
    if t is None:
        raise not_found("шаблон")
    t.hidden = body.hidden
    audit(s, "template.hide", user_id=user.id, target=t.name, details={"hidden": body.hidden})
    s.commit()
    return template_out(s, t, user)


@router.post("/{tid}/use", status_code=201)
def use_template(tid: str, body: UseIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    t = _get(s, tid, user)
    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    creds = set(s.scalars(select(m.Credential.id).where(m.Credential.workspace_id == ws)))
    try:
        graph = apply_parameters(t.graph, t.parameters, body.params, lambda c: c in creds)
    except TemplateParamError as exc:
        raise ApiError(400, "template_params", "не все параметры шаблона заполнены корректно", exc.errors) from exc
    if body.project_id:
        p = s.get(m.Project, body.project_id)
        if p is None or p.workspace_id != ws:
            raise bad_request("проект не найден")
    wf = m.Workflow(workspace_id=ws, name=body.name or t.name, description=t.description, graph=graph,
                    project_id=body.project_id, forked_from=t.id, created_by=user.id)
    s.add(wf)
    s.flush()
    sync_schedules(s, wf)
    t.usage_count += 1
    s.commit()
    return {"id": wf.id, "name": wf.name, "forked_from": t.id}


def _recompute_rating(s: Session, t: m.Template) -> None:
    avg, cnt = s.execute(select(func.avg(m.TemplateRating.stars), func.count()).where(
        m.TemplateRating.template_id == t.id)).one()
    t.rating_avg, t.rating_count = float(avg or 0), int(cnt or 0)


@router.post("/{tid}/rate")
def rate(tid: str, body: RateIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    t = _get(s, tid, user)
    r = s.scalars(select(m.TemplateRating).where(m.TemplateRating.template_id == t.id,
                                                 m.TemplateRating.user_id == user.id)).first()
    if r is None:
        s.add(m.TemplateRating(template_id=t.id, user_id=user.id, stars=body.stars))
    else:
        r.stars = body.stars
    s.flush()
    _recompute_rating(s, t)
    s.commit()
    return {"rating_avg": t.rating_avg, "rating_count": t.rating_count, "my_rating": body.stars}


@router.post("/{tid}/favorite", status_code=204)
def add_favorite(tid: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> Response:
    t = _get(s, tid, user)
    if not s.scalars(select(m.TemplateFavorite).where(m.TemplateFavorite.template_id == t.id,
                                                      m.TemplateFavorite.user_id == user.id)).first():
        s.add(m.TemplateFavorite(template_id=t.id, user_id=user.id))
        s.commit()
    return Response(status_code=204)


@router.delete("/{tid}/favorite", status_code=204)
def remove_favorite(tid: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> Response:
    for f in s.scalars(select(m.TemplateFavorite).where(m.TemplateFavorite.template_id == tid,
                                                        m.TemplateFavorite.user_id == user.id)):
        s.delete(f)
    s.commit()
    return Response(status_code=204)


def review_out(s: Session, r: m.TemplateReview, user: m.User) -> dict:
    author = s.get(m.User, r.user_id)
    return {"id": r.id, "text": r.text, "author": author.display_name if author else "—", "mine": r.user_id == user.id,
            "created_at": r.created_at, "updated_at": r.updated_at}


@router.get("/{tid}/reviews")
def list_reviews(tid: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    t = _get(s, tid, user)
    rows = s.scalars(select(m.TemplateReview).where(m.TemplateReview.template_id == t.id)
                     .order_by(m.TemplateReview.created_at.desc()))
    return [review_out(s, r, user) for r in rows]


@router.post("/{tid}/reviews", status_code=201)
def add_review(tid: str, body: ReviewIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    t = _get(s, tid, user)
    r = m.TemplateReview(template_id=t.id, user_id=user.id, text=body.text)
    s.add(r)
    s.commit()
    return review_out(s, r, user)


def _own_review(s: Session, tid: str, rid: str, user: m.User) -> m.TemplateReview:
    r = s.get(m.TemplateReview, rid)
    if r is None or r.template_id != tid:
        raise not_found("отзыв")
    if r.user_id != user.id:
        raise forbidden("можно изменять только свой отзыв")
    return r


@router.put("/{tid}/reviews/{rid}")
def edit_review(tid: str, rid: str, body: ReviewIn, user: m.User = Depends(current_user),
                s: Session = Depends(get_session)) -> dict:
    r = _own_review(s, tid, rid, user)
    r.text = body.text
    s.commit()
    return review_out(s, r, user)


@router.delete("/{tid}/reviews/{rid}", status_code=204)
def delete_review(tid: str, rid: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> Response:
    s.delete(_own_review(s, tid, rid, user))
    s.commit()
    return Response(status_code=204)

