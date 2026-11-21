import re
from datetime import timedelta
from email import message_from_bytes
from email.policy import default

import pytest
from sqlalchemy import func, select

from app import models as m
from app.config import get_settings


@pytest.fixture
def inbox(smtp_server, monkeypatch):
    port, inbox = smtp_server
    for key, value in {"HOST": "127.0.0.1", "PORT": str(port), "SECURITY": "none",
                       "FROM": "register@example.org", "USERNAME": "", "PASSWORD": ""}.items():
        monkeypatch.setenv(f"APP_SMTP_{key}", value)
    get_settings.cache_clear()
    return inbox


def test_register_requires_code_delivered_to_that_address(client, db, inbox):
    credentials = {"email": "new@example.org", "password": "New-account-pass1"}
    assert client.post("/api/auth/register", json=credentials).status_code == 422
    response = client.post("/api/auth/registration-code", json={"email": credentials["email"]})
    assert response.status_code == 204, response.text
    assert client.post("/api/auth/registration-code", json={"email": credentials["email"]}).status_code == 429
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(m.User)) == 0
    assert len(inbox.messages) == 1
    envelope = inbox.messages[0]
    message = message_from_bytes(envelope.content, policy=default)
    assert envelope.rcpt_tos == [credentials["email"]]
    code = re.search(r"\b[0-9]{6}\b", message.get_body().get_content())[0]
    wrong = f"{(int(code) + 1) % 1000000:06d}"
    assert client.post("/api/auth/register", json={**credentials, "code": wrong}).status_code == 400
    assert client.post("/api/auth/register", json={**credentials, "email": "other@example.org", "code": code}).status_code == 400
    response = client.post("/api/auth/register", json={**credentials, "code": code})
    assert response.status_code == 201 and response.json()["access_token"]
    assert client.post("/api/auth/register", json={**credentials, "code": code}).status_code == 409


@pytest.mark.parametrize("elapsed,wrong_attempts", [(10, 0), (0, 5)])
def test_expired_or_exhausted_challenge_is_replaced(client, inbox, monkeypatch, elapsed, wrong_attempts):
    from app.core import registration

    now = m.utcnow()
    monkeypatch.setattr(registration, "utcnow", lambda: now)
    codes = iter([1234, 5678])
    monkeypatch.setattr(registration.secrets, "randbelow", lambda _: next(codes))
    email = {"email": "resend@example.org", "locale": "en"}
    credentials = {**email, "password": "New-account-pass1"}
    assert client.post("/api/auth/registration-code", json=email).status_code == 204
    for _ in range(wrong_attempts):
        assert client.post("/api/auth/register", json={**credentials, "code": "999999"}).status_code == 400
    now += timedelta(minutes=elapsed)
    assert client.post("/api/auth/register", json={**credentials, "code": "001234"}).status_code == 400
    now += timedelta(minutes=1)
    assert client.post("/api/auth/registration-code", json=email).status_code == 204
    assert len(inbox.messages) == 2
    assert client.post("/api/auth/register", json={**credentials, "code": "001234"}).status_code == 400
    assert client.post("/api/auth/register", json={**credentials, "code": "005678"}).status_code == 201


def test_demo_registers_then_logs_in_with_verified_email(client, inbox, monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import demo_auth

    monkeypatch.setenv("AISW_DEMO_EMAIL", "demo@example.org")
    monkeypatch.setenv("AISW_DEMO_PASSWORD", "Demo-account-pass1")

    def code_from_inbox(_):
        message = message_from_bytes(inbox.messages[-1].content, policy=default)
        return re.search(r"\b[0-9]{6}\b", message.get_body().get_content())[0]

    monkeypatch.setattr(demo_auth, "getpass", code_from_inbox)
    for _ in range(2):
        email, headers = demo_auth.demo_session(client, "Demo")
        assert client.get("/api/auth/me", headers=headers).json()["user"]["email"] == email
    assert len(inbox.messages) == 1
