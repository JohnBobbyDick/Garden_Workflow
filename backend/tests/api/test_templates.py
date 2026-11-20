from app.seed.builtin_templates import seed_builtin_templates
from tests.api.conftest import drain
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.conftest import TRAINING

BOT = "123456789:AATemplateSecretToken_abcdefghijklmnopq"


def make_workflow(client, user):
    cid = client.post("/api/credentials", json={"workspace_id": user.workspace_id, "name": "tg", "kind": "telegram",
                                                "value": BOT}, headers=user.headers).json()["id"]
    g = full_graph()
    g["nodes"][1]["config"] = {"mode": "git_url", "git_url": "https://github.com/TBagirov/training",
                               "subdir": "training-project"}
    g["nodes"].append({"id": "tg", "type": "notify.telegram", "config": {"bot_token": cid, "chat_id": "-100777"}})
    g["edges"].append({"id": "x", "source": "merge", "source_port": "out", "target": "tg", "target_port": "in"})
    return client.post("/api/workflows", json={"name": "Аудит", "graph": g, "workspace_id": user.workspace_id},
                       headers=user.headers).json()["id"]


def publish(client, user, wid, **kw):
    body = {"workflow_id": wid, "name": "Полный аудит Kotlin", "description": "Секреты, SCA и SAST с Telegram",
            "category": "Full Security Audit", "tags": ["kotlin", "telegram"], "version": "1.0.0"}
    body.update(kw)
    return client.post("/api/templates", json=body, headers=user.headers)


def test_publish_strips_secrets_repo_urls_and_chat_ids(client, alice):
    wid = make_workflow(client, alice)
    r = publish(client, alice, wid)
    assert r.status_code == 201, r.text
    t = client.get(f"/api/templates/{r.json()['id']}", headers=alice.headers).json()
    text = str(t["graph"])
    assert "-100777" not in text and "TBagirov" not in text and BOT not in text
    names = {p["name"]: p for p in t["parameters"]}
    assert {"tg.bot_token", "tg.chat_id", "src.git_url"} <= set(names)
    assert names["tg.bot_token"]["type"] == "credential" and names["tg.chat_id"]["type"] == "string"
    assert t["author_name"] and t["usage_count"] == 0
    tg = next(n for n in t["graph"]["nodes"] if n["id"] == "tg")
    assert tg["config"]["bot_token"] == "{{param:tg.bot_token}}"
    actions = [a["action"] for a in client.get(f"/api/workspaces/{alice.workspace_id}/audit", headers=alice.headers).json()]
    assert "template.publish" in actions


def test_catalog_search_filters_and_sort(client, db, alice, bob):
    seed_builtin_templates(db)
    wid = make_workflow(client, alice)
    tid = publish(client, alice, wid).json()["id"]
    all_ = client.get("/api/templates", headers=bob.headers).json()["templates"]
    assert len(all_) >= 8 and any(t["builtin"] and t["author_name"] == "System" for t in all_)
    found = client.get("/api/templates", params={"q": "telegram"}, headers=bob.headers).json()["templates"]
    assert tid in [t["id"] for t in found]
    cat = client.get("/api/templates", params={"category": "SCA"}, headers=bob.headers).json()["templates"]
    assert cat and all(t["category"] == "SCA" for t in cat)
    mine = client.get("/api/templates", params={"mine": "true"}, headers=alice.headers).json()["templates"]
    assert [t["id"] for t in mine] == [tid]
    client.post(f"/api/templates/{tid}/rate", json={"stars": 5}, headers=bob.headers)
    top = client.get("/api/templates", params={"sort": "rating"}, headers=bob.headers).json()["templates"]
    assert top[0]["id"] == tid
    rated = client.get("/api/templates", params={"min_rating": 4}, headers=bob.headers).json()["templates"]
    assert [t["id"] for t in rated] == [tid]
    by_author = client.get("/api/templates", params={"author": "System"}, headers=bob.headers).json()["templates"]
    assert by_author and all(t["author_name"] == "System" for t in by_author)


def test_use_template_with_parameters_creates_independent_copy(client, db, alice, bob):
    wid = make_workflow(client, alice)
    tid = publish(client, alice, wid).json()["id"]
    cred = client.post("/api/credentials", json={"workspace_id": bob.workspace_id, "name": "bobtg", "kind": "telegram",
                                                 "value": "987654321:AABobsOwnTokenValue_zzzzzzzzzzzzzzzzz"},
                       headers=bob.headers).json()["id"]
    r = client.post(f"/api/templates/{tid}/use", json={"workspace_id": bob.workspace_id, "name": "Мой аудит", "params": {
        "tg.bot_token": cred, "tg.chat_id": "42", "src.git_url": "https://github.com/TBagirov/training"}},
        headers=bob.headers)
    assert r.status_code == 201, r.text
    new = client.get(f"/api/workflows/{r.json()['id']}", headers=bob.headers).json()
    assert new["forked_from"] == tid and new["workspace_id"] == bob.workspace_id
    tg = next(n for n in new["graph"]["nodes"] if n["id"] == "tg")
    assert tg["config"] == {"bot_token": cred, "chat_id": "42"}
    assert client.post(f"/api/workflows/{new['id']}/validate", headers=bob.headers).json()["valid"] is True
    # copy is fully editable and independent
    g = new["graph"]
    g["nodes"] = [n for n in g["nodes"] if n["id"] != "tg"]
    g["edges"] = [e for e in g["edges"] if e["target"] != "tg"]
    assert client.put(f"/api/workflows/{new['id']}", json={"graph": g}, headers=bob.headers).status_code == 200
    assert len(client.get(f"/api/templates/{tid}", headers=bob.headers).json()["graph"]["nodes"]) == 10
    assert client.get(f"/api/templates/{tid}", headers=bob.headers).json()["usage_count"] == 1


def test_use_rejects_missing_or_foreign_credential(client, alice, bob):
    wid = make_workflow(client, alice)
    tid = publish(client, alice, wid).json()["id"]
    cred_of_alice = client.get("/api/credentials", headers=alice.headers).json()[0]["id"]
    r = client.post(f"/api/templates/{tid}/use", json={"workspace_id": bob.workspace_id, "params": {
        "tg.bot_token": cred_of_alice, "tg.chat_id": "1", "src.git_url": "https://github.com/TBagirov/training"}},
        headers=bob.headers)
    assert r.status_code == 400


def test_rating_favorites_reviews(client, alice, bob):
    wid = make_workflow(client, alice)
    tid = publish(client, alice, wid).json()["id"]
    client.post(f"/api/templates/{tid}/rate", json={"stars": 2}, headers=bob.headers)
    client.post(f"/api/templates/{tid}/rate", json={"stars": 4}, headers=bob.headers)  # change own rating
    client.post(f"/api/templates/{tid}/rate", json={"stars": 5}, headers=alice.headers)
    t = client.get(f"/api/templates/{tid}", headers=bob.headers).json()
    assert t["rating_count"] == 2 and t["rating_avg"] == 4.5 and t["my_rating"] == 4
    assert client.post(f"/api/templates/{tid}/rate", json={"stars": 7}, headers=bob.headers).status_code == 422
    assert client.post(f"/api/templates/{tid}/favorite", headers=bob.headers).status_code == 204
    favs = client.get("/api/templates", params={"favorites": "true"}, headers=bob.headers).json()["templates"]
    assert [x["id"] for x in favs] == [tid]
    client.delete(f"/api/templates/{tid}/favorite", headers=bob.headers)
    assert client.get("/api/templates", params={"favorites": "true"}, headers=bob.headers).json()["templates"] == []
    rv = client.post(f"/api/templates/{tid}/reviews", json={"text": "Отличный шаблон"}, headers=bob.headers).json()
    assert client.put(f"/api/templates/{tid}/reviews/{rv['id']}", json={"text": "Очень полезно"},
                      headers=bob.headers).status_code == 200
    assert client.put(f"/api/templates/{tid}/reviews/{rv['id']}", json={"text": "чужой"},
                      headers=alice.headers).status_code == 403
    reviews = client.get(f"/api/templates/{tid}/reviews", headers=alice.headers).json()
    assert reviews[0]["text"] == "Очень полезно"
    assert client.delete(f"/api/templates/{tid}/reviews/{rv['id']}", headers=bob.headers).status_code == 204


def test_moderation_unpublish_update_and_admin_hide(client, alice, bob):
    wid = make_workflow(client, alice)
    tid = publish(client, alice, wid).json()["id"]
    assert client.put(f"/api/templates/{tid}", json={"published": False}, headers=bob.headers).status_code == 403
    assert client.put(f"/api/templates/{tid}", json={"version": "1.1.0", "workflow_id": wid},
                      headers=alice.headers).json()["version"] == "1.1.0"
    client.put(f"/api/templates/{tid}", json={"published": False}, headers=alice.headers)
    assert tid not in [t["id"] for t in client.get("/api/templates", headers=bob.headers).json()["templates"]]
    client.put(f"/api/templates/{tid}", json={"published": True}, headers=alice.headers)
    # alice registered first → platform admin
    assert client.post(f"/api/templates/{tid}/hide", json={"hidden": True}, headers=bob.headers).status_code == 403
    assert client.post(f"/api/templates/{tid}/hide", json={"hidden": True}, headers=alice.headers).status_code == 200
    assert tid not in [t["id"] for t in client.get("/api/templates", headers=bob.headers).json()["templates"]]


def test_builtin_templates_are_valid_and_seed_is_idempotent(client, db, alice):
    seed_builtin_templates(db)  # app startup already seeded them
    assert seed_builtin_templates(db) == 0
    names = {t["name"] for t in client.get("/api/templates", params={"author": "System"}, headers=alice.headers)
             .json()["templates"]}
    assert {"Проверка секретов", "SCA зависимостей", "SAST Kotlin/Spring", "Полный аудит безопасности + AI + Telegram",
            "CI gate: упасть на Critical", "Ежедневная проверка + e-mail",
            "Проверка по webhook + Webhook-уведомление"} <= names
    tpl = next(t for t in client.get("/api/templates", headers=alice.headers).json()["templates"]
               if t["name"] == "SCA зависимостей")
    r = client.post(f"/api/templates/{tpl['id']}/use", json={"workspace_id": alice.workspace_id,
                                                             "params": {"src.path": str(TRAINING)}},
                    headers=alice.headers)
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert client.post(f"/api/workflows/{wid}/validate", headers=alice.headers).json()["valid"] is True
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    assert client.get(f"/api/runs/{rid}", headers=alice.headers).json()["summary"]["total"] == 5
