from sqlalchemy import select

from app import models as m


def test_library_is_persistent_and_scoped(client, db, alice, bob):
    url = f"/api/nodes/custom?workspace_id={alice.workspace_id}"
    body = {"name": "Высокий риск", "fields": {"high": "counts.HIGH"}}
    created = client.post(url, headers=alice.headers, json=body)
    assert created.status_code == 201, created.text
    assert created.json() == {**body, "id": created.json()["id"]}
    assert client.get(url, headers=alice.headers).json() == [created.json()]
    assert client.post(url, headers=alice.headers, json=body).status_code == 409
    assert client.get(url, headers=bob.headers).status_code == 404
    assert client.post(url, headers=bob.headers, json=body).status_code == 404
    assert client.get("/api/nodes/custom", headers=bob.headers).json() == []
    assert client.post(url, headers=alice.headers, json={**body, "fields": {"bad": "x()"}}).status_code == 422
    with db.session() as s:
        s.scalar(select(m.Membership).where(m.Membership.user_id == alice.id)).role = "viewer"
        s.commit()
    assert client.get(url, headers=alice.headers).status_code == 200
    assert client.post(url, headers=alice.headers, json=body).status_code == 403
