"""Authenticate demo clients through the same public API as the browser."""
from __future__ import annotations

import os
from getpass import getpass

import httpx


def demo_session(client: httpx.Client, display_name: str) -> tuple[str, dict[str, str]]:
    email = os.environ.get("AISW_DEMO_EMAIL") or input("E-mail демо-пользователя: ").strip()
    password = os.environ.get("AISW_DEMO_PASSWORD") or getpass("Пароль демо-пользователя: ")
    credentials = {"email": email, "password": password}
    session = client.post("/api/auth/register", json={**credentials, "display_name": display_name})
    if session.status_code == 409 and session.json()["error"]["code"] == "email_taken":
        session = client.post("/api/auth/login", json=credentials)
    session.raise_for_status()
    return email, {"Authorization": f"Bearer {session.json()['access_token']}"}
