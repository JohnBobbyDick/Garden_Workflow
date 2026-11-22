def test_register_without_mail_starts_session_and_rejects_duplicate(client):
    credentials = {"email": "new@example.org", "password": "New-account-pass1"}
    registered = client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201
    session = registered.json()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {session['access_token']}"}).json()
    assert me["user"]["email"] == credentials["email"] and len(me["workspaces"]) == 1
    assert client.post("/api/auth/register", json={**credentials, "email": "NEW@example.org"}).status_code == 409
    assert client.post("/api/auth/login", json=credentials).status_code == 200


def test_demo_registers_then_logs_in_without_mail(client, monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import demo_auth

    monkeypatch.setenv("AISW_DEMO_EMAIL", "demo@example.org")
    monkeypatch.setenv("AISW_DEMO_PASSWORD", "Demo-account-pass1")

    for _ in range(2):
        email, headers = demo_auth.demo_session(client, "Demo")
        assert client.get("/api/auth/me", headers=headers).json()["user"]["email"] == email
