import re

from sqlalchemy import func, select

from app import models as m
from app.config import get_settings
from tests.nodes.test_notify_nodes import smtp_server  # noqa: F401


def test_register_requires_code_delivered_to_that_address(client, db, smtp_server, monkeypatch):
    port, inbox = smtp_server
    for key, value in {"HOST": "127.0.0.1", "PORT": str(port), "SECURITY": "none",
                       "FROM": "register@example.org"}.items():
        monkeypatch.setenv(f"APP_SMTP_{key}", value)
    get_settings.cache_clear()
    credentials = {"email": "new@example.org", "password": "New-account-pass1"}
    assert client.post("/api/auth/register", json=credentials).status_code == 422
    response = client.post("/api/auth/registration-code", json={"email": credentials["email"]})
    assert response.status_code == 204, response.text
    assert client.post("/api/auth/registration-code", json={"email": credentials["email"]}).status_code == 429
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(m.User)) == 0
    assert len(inbox.messages) == 1
    envelope, message = inbox.messages[0]
    assert envelope.rcpt_tos == [credentials["email"]]
    code = re.search(r"\b[0-9]{6}\b", message.get_body().get_content())[0]
    wrong = f"{(int(code) + 1) % 1000000:06d}"
    assert client.post("/api/auth/register", json={**credentials, "code": wrong}).status_code == 400
    assert client.post("/api/auth/register", json={**credentials, "email": "other@example.org", "code": code}).status_code == 400
    response = client.post("/api/auth/register", json={**credentials, "code": code})
    assert response.status_code == 201 and response.json()["access_token"]
    assert client.post("/api/auth/register", json={**credentials, "code": code}).status_code == 409
