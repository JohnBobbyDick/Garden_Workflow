"""GitHub/GitLab webhooks: signature check, event filter, subscription matching (trigger.webhook), idempotency by
delivery id, run creation and a ``pending`` commit status."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.api.workflows import start_run
from app.ci.status import post_status, scm_target
from app.config import get_settings
from app.core.audit import audit
from app.core.crypto import CryptoError, get_box
from app.core.errors import ApiError
from app.core.repo_guard import normalize_repo_url
from app.db import get_db
from app.engine.services import allowlist_for

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)
MAX_BODY = 1024 * 1024
GH_PR_ACTIONS = {"opened", "synchronize", "reopened"}
GL_MR_ACTIONS = {"open", "update", "reopen"}


def _parse_github(event: str, p: dict) -> dict | None:
    repo = p.get("repository") or {}
    base = {"provider": "github", "repo_url": repo.get("html_url") or "", "project": repo.get("full_name") or ""}
    if event == "pull_request":
        if p.get("action") not in GH_PR_ACTIONS:
            return None
        pr = p.get("pull_request") or {}
        return {**base, "event": "pull_request", "ref": (pr.get("head") or {}).get("ref"),
                "head_sha": (pr.get("head") or {}).get("sha"), "base_sha": (pr.get("base") or {}).get("sha"),
                "base_ref": (pr.get("base") or {}).get("ref"), "pr_number": p.get("number")}
    if event == "push":
        return {**base, "event": "push", "ref": (p.get("ref") or "").removeprefix("refs/heads/"),
                "head_sha": p.get("after"), "base_sha": p.get("before"), "pr_number": None}
    return None


def _parse_gitlab(event: str, p: dict) -> dict | None:
    proj = p.get("project") or {}
    base = {"provider": "gitlab", "repo_url": proj.get("web_url") or "", "project": proj.get("path_with_namespace") or ""}
    if event == "Merge Request Hook":
        a = p.get("object_attributes") or {}
        if a.get("action") not in GL_MR_ACTIONS:
            return None
        refs = p.get("diff_refs") or a.get("diff_refs") or {}
        return {**base, "event": "merge_request", "ref": a.get("source_branch"), "base_ref": a.get("target_branch"),
                "head_sha": (a.get("last_commit") or {}).get("id") or refs.get("head_sha"),
                "base_sha": refs.get("base_sha"), "pr_number": a.get("iid")}
    if event == "Push Hook":
        return {**base, "event": "push", "ref": (p.get("ref") or "").removeprefix("refs/heads/"),
                "head_sha": p.get("checkout_sha") or p.get("after"), "base_sha": p.get("before"), "pr_number": None}
    return None


def _verify(provider: str, secret: str, body: bytes, request: Request) -> bool:
    if provider == "github":
        sig = request.headers.get("x-hub-signature-256", "")
        want = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, want)
    return hmac.compare_digest(request.headers.get("x-gitlab-token", ""), secret)


def _subscriptions(s, provider: str, repo_url: str):  # noqa: ANN001, ANN202
    norm = normalize_repo_url(repo_url) if repo_url else ""
    for wf in s.scalars(select(m.Workflow)):
        for node in (wf.graph or {}).get("nodes", []):
            cfg = node.get("config") or {}
            if node.get("type") != "trigger.webhook" or node.get("disabled") or cfg.get("provider") != provider:
                continue
            if not cfg.get("repo_url") or normalize_repo_url(cfg["repo_url"]) != norm:
                continue
            yield wf, node


async def _handle(provider: str, request: Request) -> JSONResponse:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY:
        raise ApiError(413, "payload_too_large", "тело вебхука слишком большое")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise ApiError(413, "payload_too_large", "тело вебхука слишком большое")
    event = request.headers.get("x-github-event" if provider == "github" else "x-gitlab-event", "")
    delivery = request.headers.get("x-github-delivery" if provider == "github" else "x-gitlab-event-uuid") \
        or hashlib.sha256(body).hexdigest()
    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise ApiError(400, "bad_json", "тело вебхука не является JSON") from exc
    info = (_parse_github if provider == "github" else _parse_gitlab)(event, payload) if isinstance(payload, dict) \
        else None
    repo_url = info["repo_url"] if info else ((payload.get("repository") or {}).get("html_url")
                                              or (payload.get("project") or {}).get("web_url") or "")
    db = get_db()
    created: list[str] = []
    pending: list[tuple] = []
    with db.session() as s:
        dup = s.scalars(select(m.WebhookDelivery).where(m.WebhookDelivery.provider == provider,
                                                        m.WebhookDelivery.delivery_id == delivery)).first()
        if dup is not None:
            return JSONResponse({"duplicate": True, "run_ids": dup.run_ids}, status_code=200)
        subs = list(_subscriptions(s, provider, repo_url))
        if not subs:
            raise ApiError(404, "no_subscription", "нет сценариев, подписанных на этот репозиторий")
        verified = []
        for wf, node in subs:
            cred = s.get(m.Credential, (node.get("config") or {}).get("secret") or "")
            if cred is None or cred.workspace_id != wf.workspace_id:
                continue
            try:
                secret = get_box().decrypt(cred.ciphertext)
            except CryptoError:
                continue
            if _verify(provider, secret, body, request):
                verified.append((wf, node))
        if not verified:
            raise ApiError(401, "invalid_signature", "подпись вебхука не прошла проверку")
        workspace_id = verified[0][0].workspace_id
        if info is not None:
            for wf, node in verified:
                cfg = node.get("config") or {}
                if info["event"] not in (cfg.get("events") or ["push", "pull_request", "merge_request"]):
                    continue
                branches = cfg.get("branches") or []
                if branches and info["event"] == "push" and info.get("ref") not in branches:
                    continue
                if normalize_repo_url(info["repo_url"]) not in {normalize_repo_url(u) for u in allowlist_for(s, wf.workspace_id)}:
                    continue
                payload_run = {**{k: info.get(k) for k in ("provider", "event", "ref", "head_sha", "base_sha",
                                                           "base_ref", "pr_number")},
                               "repo": info["project"],
                               "scm": {"provider": provider, "repo_url": info["repo_url"], "project": info["project"],
                                       "sha": info.get("head_sha"), "pr": info.get("pr_number")},
                               "source": {"mode": "git_url", "git_url": info["repo_url"], "ref": info.get("head_sha")}}
                run = start_run(s, wf, None, "webhook", trigger_node_id=node["id"], payload=payload_run)
                created.append(run.id)
                target = scm_target(s, wf.workspace_id, provider, info["repo_url"], info["project"])
                if target is not None and info.get("head_sha"):
                    pending.append((run.id, target, info["head_sha"]))
        s.add(m.WebhookDelivery(provider=provider, delivery_id=delivery[:200], workspace_id=workspace_id,
                                event=event[:64], run_ids=created))
        audit(s, "webhook.received", workspace_id=workspace_id, target=f"{provider}:{event}",
              details={"delivery": delivery[:80], "runs": created})
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return JSONResponse({"duplicate": True, "run_ids": []}, status_code=200)
    base = get_settings().public_url.rstrip("/")
    for run_id, target, sha in pending:
        await post_status(db, run_id, target, sha, "pending", "проверка безопасности запущена", f"{base}/runs/{run_id}")
    return JSONResponse({"run_ids": created, "delivery": delivery, "id": uuid.uuid4().hex[:8]}, status_code=202)


@router.post("/github")
async def github(request: Request) -> JSONResponse:
    return await _handle("github", request)


@router.post("/gitlab")
async def gitlab(request: Request) -> JSONResponse:
    return await _handle("gitlab", request)
