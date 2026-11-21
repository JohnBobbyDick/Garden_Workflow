import asyncio
import re
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db import Database, set_db
from app.engine.worker import Worker


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    d.create_all()
    set_db(d)
    yield d
    set_db(None)


@pytest.fixture
def client(db):
    from app.api.auth import reset_rate_limits
    from app.main import create_app

    reset_rate_limits()
    with TestClient(create_app()) as c:
        yield c


class User:
    def __init__(self, client, email, password="Str0ng-Passw0rd!"):
        from app.config import get_settings

        with (patch.object(get_settings(), "smtp_host", "test"),
              patch.object(get_settings(), "smtp_from", "register@example.org"),
              patch("app.core.registration.send_mail", new_callable=AsyncMock) as delivered):
            request = client.post("/api/auth/registration-code", json={"email": email})
            assert request.status_code == 204, request.text
            message = delivered.await_args.args[0]
            code = re.search(r"\b[0-9]{6}\b", message.get_content())[0]
        r = client.post("/api/auth/register", json={"email": email, "password": password,
                                                    "display_name": email, "code": code})
        assert r.status_code == 201, r.text
        body = r.json()
        self.email = email
        self.password = password
        self.token = body["access_token"]
        self.refresh = body["refresh_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        me = client.get("/api/auth/me", headers=self.headers).json()
        self.id = me["user"]["id"]
        self.workspace_id = me["workspaces"][0]["id"]


@pytest.fixture
def alice(client):
    return User(client, "alice@example.org")


@pytest.fixture
def bob(client):
    return User(client, "bob@example.org")


def drain(db):
    """Execute every queued run with a real worker (same process)."""
    w = Worker(db, "test-worker", poll_interval=0.05)
    done = []
    while True:
        rid = asyncio.run(w.run_once())
        if rid is None:
            return done
        done.append(rid)
