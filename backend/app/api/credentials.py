from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.ai.pool import parse_proxy
from app.config import get_settings
from app.core.audit import audit
from app.core.crypto import get_box
from app.core.errors import ApiError, bad_request, conflict
from app.core.masking import global_masker, mask_tail
from app.core.ssrf import SSRFError, safe_request
from app.deps import client_ip, current_user, get_session, load_scoped, resolve_workspace

router = APIRouter(tags=["credentials"])

KINDS = ["telegram", "smtp", "webhook_secret", "repo_token", "repo_write_token", "llm_api_key", "proxy", "generic"]


class CredentialIn(BaseModel):
    workspace_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="generic", pattern="^(" + "|".join(KINDS) + ")$")
    value: str = Field(min_length=1, max_length=20000)


class CredentialUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=20000)


def cred_out(c: m.Credential) -> dict:
    return {"id": c.id, "workspace_id": c.workspace_id, "name": c.name, "kind": c.kind, "display": c.tail,
            "created_at": c.created_at, "updated_at": c.updated_at}


def store_value(c: m.Credential, value: str) -> None:
    box = get_box()
    c.ciphertext = box.encrypt(value)
    c.key_version = box.current
    c.tail = proxy_display(value) if c.kind == "proxy" else mask_tail(value)
    global_masker.register(value)


def proxy_display(value: str) -> str:
    """A proxy secret is shown as ``host:port`` only: its tail would be the end of the password."""
    url = parse_proxy(value, "http", None)
    if not url:
        return mask_tail(value)
    p = urlsplit(url)
    return f"{p.hostname}:{p.port}" if p.port else (p.hostname or mask_tail(value))


@router.get("/credentials")
def list_credentials(workspace_id: str | None = None, user: m.User = Depends(current_user),
                     s: Session = Depends(get_session)) -> list[dict]:
    ws = resolve_workspace(s, user, workspace_id)
    rows = s.scalars(select(m.Credential).where(m.Credential.workspace_id == ws).order_by(m.Credential.name)).all()
    return [cred_out(c) for c in rows]


@router.post("/credentials", status_code=201)
def create_credential(body: CredentialIn, request: Request, user: m.User = Depends(current_user),
                      s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "admin")
    c = m.Credential(workspace_id=ws, name=body.name, kind=body.kind, created_by=user.id)
    store_value(c, body.value)
    s.add(c)
    audit(s, "credential.create", user_id=user.id, workspace_id=ws, target=body.name, details={"kind": body.kind},
          ip=client_ip(request))
    try:
        s.commit()
    except IntegrityError as exc:
        raise conflict("секрет с таким именем уже существует") from exc
    return cred_out(c)


@router.put("/credentials/{credential_id}")
def update_credential(credential_id: str, body: CredentialUpdate, request: Request,
                      user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    c = load_scoped(s, m.Credential, credential_id, user, "admin", "секрет")
    store_value(c, body.value)
    audit(s, "credential.update", user_id=user.id, workspace_id=c.workspace_id, target=c.name, ip=client_ip(request))
    s.commit()
    return cred_out(c)


@router.delete("/credentials/{credential_id}", status_code=204)
def delete_credential(credential_id: str, request: Request, user: m.User = Depends(current_user),
                      s: Session = Depends(get_session)) -> Response:
    c = load_scoped(s, m.Credential, credential_id, user, "admin", "секрет")
    audit(s, "credential.delete", user_id=user.id, workspace_id=c.workspace_id, target=c.name, ip=client_ip(request))
    s.delete(c)
    s.commit()
    return Response(status_code=204)


class TelegramChatLookup(BaseModel):
    username: str = Field(pattern=r"^@?[A-Za-z][A-Za-z0-9_]{0,31}$")


@router.post("/credentials/{credential_id}/telegram-chat")
async def telegram_chat(credential_id: str, body: TelegramChatLookup, user: m.User = Depends(current_user),
                        s: Session = Depends(get_session)) -> dict:
    credential = load_scoped(s, m.Credential, credential_id, user, "developer", "секрет")
    if credential.kind != "telegram":
        raise bad_request("Выберите токен Telegram-бота.")
    token = get_box().decrypt(credential.ciphertext)
    global_masker.register(token)
    settings = get_settings()
    base = f"{settings.telegram_api_base.rstrip('/')}/bot{token}"
    failed = ApiError(502, "telegram_lookup_failed", "Не удалось получить данные чата. Проверьте токен и доступ бота.")

    async def lookup(method: str, params: dict) -> dict | list | None:
        try:
            response = await safe_request("POST", f"{base}/{method}", allow_hosts=settings.ssrf_allowed(),
                                          json=params, timeout=10, max_redirects=0)
            if method == "getUpdates" and response.status_code == 409:
                raise ApiError(409, "telegram_updates_busy",
                               "Активен webhook или другой получатель обновлений. Введите числовой ID чата.")
            payload = response.json()
        except (ValueError, httpx.HTTPError, SSRFError):
            raise ApiError(502, "telegram_unavailable", "Не удалось получить ответ Telegram.") from None
        if not isinstance(payload, dict):
            raise failed
        if method == "getChat" and response.status_code == 400 and payload.get("ok") is False:
            return None  # A personal username cannot be resolved by getChat.
        if response.status_code != 200 or payload.get("ok") is not True or not isinstance(payload.get("result"), (dict, list)):
            raise failed
        return payload["result"]

    username = body.username.lstrip("@")
    public = await lookup("getChat", {"chat_id": f"@{username}"})
    if public is not None:
        if (isinstance(public, dict) and public.get("type") in ("channel", "supergroup")
                and type(public.get("id")) is int and public["id"] < 0):
            return {"chat_id": str(public["id"])}
        raise failed
    # Reading without an offset leaves the bot's updates unacknowledged.
    updates = await lookup("getUpdates", {"limit": 100, "timeout": 0})
    if not isinstance(updates, list):
        raise failed
    for event in reversed(updates):
        if not isinstance(event, dict):
            continue
        message = event.get("message") or event.get("edited_message")
        chat = message.get("chat") if isinstance(message, dict) else None
        if (isinstance(chat, dict) and chat.get("type") == "private" and isinstance(chat.get("username"), str)
                and chat["username"].lower() == username.lower() and type(chat.get("id")) is int and chat["id"] > 0):
            return {"chat_id": str(chat["id"])}
    raise ApiError(404, "telegram_chat_missing",
                   "Чат не найден. Для личного чата отправьте боту /start и повторите поиск или введите числовой ID.")
