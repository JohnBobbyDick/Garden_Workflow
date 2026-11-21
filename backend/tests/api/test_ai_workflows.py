import json

import pytest

from tests.api.test_ai_api import configure

PDF_PROMPT = "Каждый день в 14:00 проверяй код из репозитория на наличие секретов и отправляй отчет на почту"
TZ_PROMPT = ("Каждый день в 14:00 проверяй мой Kotlin-проект на секреты и уязвимые зависимости. "
             "Если найдёшь Critical или High — отправь уведомление в Telegram.")


def g(nodes, edges):
    return {"nodes": [{"id": i, "type": t, "config": c} for i, t, c in nodes],
            "edges": [{"source": s, "source_port": sp, "target": d, "target_port": dp} for s, sp, d, dp in edges]}


PDF_GRAPH = g([("t", "trigger.schedule", {"cron": "0 14 * * *"}), ("src", "source.repo", {"mode": "project"}),
               ("sec", "scanner.secrets", {}), ("exp", "output.report_export", {}),
               ("mail", "notify.smtp", {"host": "", "from_addr": "", "to": []})],
              [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("sec", "out", "exp", "in"),
               ("exp", "out", "mail", "in")])
TZ_GRAPH = g([("t", "trigger.schedule", {"cron": "0 14 * * *"}), ("src", "source.repo", {"mode": "project"}),
              ("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("merge", "logic.merge", {}),
              ("if", "logic.if_else", {"expression": "severity.max >= HIGH"}),
              ("tg", "notify.telegram", {"bot_token": "123456789:AAleakedTokenShouldBeStripped_abcdefgh", "chat_id": ""})],
             [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("src", "out", "sca", "in"),
              ("sec", "out", "merge", "in"), ("sca", "out", "merge", "in"), ("merge", "out", "if", "in"),
              ("if", "true", "tg", "in")])


@pytest.fixture
def llm(nvidia_server):
    script, hp = nvidia_server
    return script, hp


def gen(client, user, prompt, **kw):
    return client.post("/api/ai/workflows/generate", json={"workspace_id": user.workspace_id, "prompt": prompt, **kw},
                       headers=user.headers)


def types(graph):
    return sorted(n["type"] for n in graph["nodes"])


def test_generation_requires_configured_provider(client, alice):
    r = gen(client, alice, PDF_PROMPT)
    assert r.status_code == 400 and r.json()["error"]["code"] == "ai_not_configured"


def test_pdf_example_generates_valid_graph_with_catalog_in_prompt(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply(PDF_GRAPH)
    r = gen(client, alice, PDF_PROMPT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True and body["attempts"] == 1
    assert types(body["graph"]) == ["notify.smtp", "output.report_export", "scanner.secrets", "source.repo",
                                    "trigger.schedule"]
    assert next(n for n in body["graph"]["nodes"] if n["type"] == "trigger.schedule")["config"]["cron"] == "0 14 * * *"
    assert all("position" in n for n in body["graph"]["nodes"])
    assert {"node_id": "mail", "field": "host"} in [{k: x[k] for k in ("node_id", "field")} for x in body["needs_input"]]
    system = script.requests[0]["body"]["messages"][0]["content"]
    assert "scanner.secrets" in system and "notify.telegram" in system and "config" in system
    assert PDF_PROMPT in script.requests[0]["body"]["messages"][-1]["content"]


def test_tz_example_and_secret_literals_are_stripped(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply(TZ_GRAPH)
    body = gen(client, alice, TZ_PROMPT, create=True, name="Ежедневно").json()
    assert body["valid"] is True and body["workflow_id"]
    gr = body["graph"]
    assert types(gr) == sorted(["trigger.schedule", "source.repo", "scanner.secrets", "scanner.sca", "logic.merge",
                                "logic.if_else", "notify.telegram"])
    iff = next(n for n in gr["nodes"] if n["type"] == "logic.if_else")
    assert iff["config"]["expression"] == "severity.max >= HIGH"
    tg = next(n for n in gr["nodes"] if n["type"] == "notify.telegram")
    assert any(e["source"] == iff["id"] and e["source_port"] == "true" and e["target"] == tg["id"] for e in gr["edges"])
    assert "leakedToken" not in json.dumps(body) and not tg["config"].get("bot_token")
    assert {(x["node_id"], x["field"]) for x in body["needs_input"]} >= {(tg["id"], "bot_token"), (tg["id"], "chat_id")}
    wf = client.get(f"/api/workflows/{body['workflow_id']}", headers=alice.headers).json()
    assert len(wf["graph"]["nodes"]) == 7


def test_invalid_graph_is_repaired_with_validator_errors(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    broken = json.loads(json.dumps(PDF_GRAPH))
    broken["edges"].append({"source": "sec", "source_port": "out", "target": "src", "target_port": "in"})  # cycle+type
    script.reply(broken).reply(PDF_GRAPH)
    body = gen(client, alice, PDF_PROMPT).json()
    assert body["valid"] is True and body["attempts"] == 2
    repair = script.requests[1]["body"]["messages"][-1]["content"]
    assert "cycle" in repair or "цикл" in repair


def test_generation_gives_up_after_three_attempts(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    bad = g([("src", "source.repo", {})], [])  # no trigger
    for _ in range(3):
        script.reply(bad)
    r = gen(client, alice, PDF_PROMPT, create=True)
    assert r.status_code == 422 and r.json()["error"]["code"] == "generation_failed"
    assert any(i["code"] == "no_trigger" for i in r.json()["error"]["details"]["issues"])
    assert client.get("/api/workflows", headers=alice.headers).json() == []
    assert len(script.requests) == 3


def test_chat_add_email_preview_apply_and_history(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply(TZ_GRAPH)
    wid = gen(client, alice, TZ_PROMPT, create=True).json()["workflow_id"]
    script.reply({"explanation": "Добавляю письмо", "operations": [
        {"op": "add_node", "node_id": "mail", "type": "notify.smtp", "config": {"host": "", "from_addr": "", "to": []}},
        {"op": "connect", "source": "if", "source_port": "true", "target": "mail", "target_port": "in"}]})
    r = client.post(f"/api/ai/workflows/{wid}/chat", json={"message": "добавь отправку на email"}, headers=alice.headers)
    assert r.status_code == 200, r.text
    prop = r.json()
    assert prop["diff"]["added_nodes"] == ["mail"] and prop["diff"]["added_edges"] and prop["status"] == "proposed"
    assert len(client.get(f"/api/workflows/{wid}", headers=alice.headers).json()["graph"]["nodes"]) == 7  # not yet
    ap = client.post(f"/api/ai/workflows/{wid}/chat/{prop['id']}/apply", headers=alice.headers)
    assert ap.status_code == 200
    wf = client.get(f"/api/workflows/{wid}", headers=alice.headers).json()
    assert "notify.smtp" in types(wf["graph"])
    script.reply({"explanation": "Заменяю", "operations": [{"op": "remove_node", "node_id": "tg"}]})
    p2 = client.post(f"/api/ai/workflows/{wid}/chat", json={"message": "убери Telegram"}, headers=alice.headers).json()
    assert p2["diff"]["removed_nodes"] == ["tg"]
    client.post(f"/api/ai/workflows/{wid}/chat/{p2['id']}/reject", headers=alice.headers)
    assert "notify.telegram" in types(client.get(f"/api/workflows/{wid}", headers=alice.headers).json()["graph"])
    hist = client.get(f"/api/ai/workflows/{wid}/chat", headers=alice.headers).json()
    assert hist[0]["content"] == TZ_PROMPT  # the generation prompt opens the history
    assert [(h["role"], h["status"]) for h in hist[1:]] == [("user", "applied"), ("assistant", "applied"),
                                                         ("user", "rejected"), ("assistant", "rejected")]


def test_chat_connects_report_to_smtp_when_model_copies_field_descriptions(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply({"nodes": PDF_GRAPH["nodes"][:-1], "edges": PDF_GRAPH["edges"][:-1]})
    wid = gen(client, alice, "Проверка с отчётом", create=True).json()["workflow_id"]
    chat_url = f"/api/ai/workflows/{wid}/chat"
    config = {
        "host": {"type": "string", "title": "SMTP-сервер"},
        "port": {"type": "integer", "default": 25, "title": "Порт"},
        "security": {"type": "string", "enum": ["starttls", "tls", "none"], "default": "starttls"},
        "username": {"type": "string", "credential_ref": True, "title": "Пользователь"},
        "password": {"type": "string", "credential_ref": True, "title": "Пароль"},
        "from_addr": {"type": "string", "credential_ref": True, "title": "От кого"},
        "to": {"type": "array", "title": "Кому"},
        "template": {"type": "string", "title": "Шаблон текста"},
        "subject": "Результаты проверки",
    }
    script.reply({"operations": [
        {"op": "add_node", "node_id": "mail", "type": "notify.smtp", "config": config},
        {"op": "connect", "source": "exp", "target": "mail"},
    ]})
    proposal = client.post(chat_url, json={"message": "Отправь отчёт на email"}, headers=alice.headers).json()
    assert proposal["status"] == "proposed", proposal["issues"]
    assert proposal["diff"]["added_edges"] == [["exp", "out", "mail", "in"]]
    mail_inputs = {item["field"]: item["kind"] for item in proposal["needs_input"] if item["node_id"] == "mail"}
    assert mail_inputs == {"host": "value", "from_addr": "value", "to": "value", "password": "credential"}
    saved = client.post(f"{chat_url}/{proposal['id']}/apply", headers=alice.headers).json()["graph"]
    mail = next(node for node in saved["nodes"] if node["id"] == "mail")
    assert mail["config"]["subject"] == "Результаты проверки"
    assert mail["config"].get("port", 587) == 587
    assert mail["config"].get("security", "starttls") == "starttls"
    assert not any(isinstance(value, dict) for value in mail["config"].values())

    # Repeating catalog metadata during an edit must preserve the user's subject.
    script.reply({"operations": [{"op": "update_node", "node_id": "mail", "config": {
        "subject": {"type": "string", "title": "Тема"}, "port": 465, "security": "tls"}}]})
    updated = client.post(chat_url, json={"message": "Используй TLS"}, headers=alice.headers).json()
    assert updated["valid"]
    config = next(node["config"] for node in updated["graph"]["nodes"] if node["id"] == "mail")
    assert (config["subject"], config["port"], config["security"]) == ("Результаты проверки", 465, "tls")

    script.reply({"operations": [{"op": "update_node", "node_id": "mail", "config": {"port": {"value": 25}}}]})
    invalid = client.post(chat_url, json={"message": "Измени порт"}, headers=alice.headers).json()
    assert invalid["status"] == "failed"
    assert any(issue["field"] == "port" for issue in invalid["issues"])


def test_chat_repairs_telegram_config_and_preserves_delivery_settings(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    token = client.post("/api/credentials", headers=alice.headers, json={
        "workspace_id": alice.workspace_id, "kind": "telegram", "name": "Telegram", "value": "test-bot-token",
    }).json()["id"]
    telegram = {"bot_token": token, "chat_id": "-100123", "template": "Итоги проверки", "send_document": False}
    graph = {"nodes": [*PDF_GRAPH["nodes"][:-1], {"id": "mail", "type": "notify.telegram",
                      "config": {**telegram, "from_addr": "team@example.org", "subject": "Проверка"}}],
             "edges": [{**edge, "id": f"e{i}"} for i, edge in enumerate(PDF_GRAPH["edges"])]}
    created = client.post("/api/workflows", headers=alice.headers, json={
        "workspace_id": alice.workspace_id, "name": "Отчёт в Telegram", "graph": graph,
    })
    assert created.status_code == 201, created.text
    wf = created.json()
    url = f"/api/workflows/{wf['id']}"
    assert not client.post(f"{url}/validate", headers=alice.headers).json()["valid"]
    script.reply({"operations": [{"op": "update_node", "node_id": "mail", "config": {
        "bot_token": "", "chat_id": "", "send_document": True, "to": ["team@example.org"],
    }}]})
    chat = f"/api/ai/workflows/{wf['id']}/chat"
    proposal = client.post(chat, headers=alice.headers, json={"message": "Исправь Telegram, приложи .md"}).json()
    assert proposal["status"] == "proposed", proposal["issues"]
    assert proposal["diff"]["changed_nodes"] == ["mail"]
    applied = client.post(f"{chat}/{proposal['id']}/apply", headers=alice.headers).json()["graph"]
    assert applied["edges"] == wf["graph"]["edges"]
    assert next(n["config"] for n in applied["nodes"] if n["id"] == "mail") == {**telegram, "send_document": True}
    assert client.post(f"{url}/validate", headers=alice.headers).json()["valid"]


def test_chat_set_schedule_and_invalid_ops(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply(TZ_GRAPH)
    wid = gen(client, alice, TZ_PROMPT, create=True).json()["workflow_id"]
    script.reply({"explanation": "Только по будням", "operations": [{"op": "set_schedule", "cron": "0 14 * * 1-5"}]})
    p = client.post(f"/api/ai/workflows/{wid}/chat", json={"message": "запускай только по будням"},
                    headers=alice.headers).json()
    assert p["valid"] is True and p["diff"]["changed_nodes"] == ["t"]
    script.reply({"explanation": "x", "operations": [{"op": "connect", "source": "sec", "source_port": "out",
                                                      "target": "src", "target_port": "in"}]})
    bad = client.post(f"/api/ai/workflows/{wid}/chat", json={"message": "сломай"}, headers=alice.headers).json()
    assert bad["valid"] is False and bad["status"] == "failed" and bad["issues"]
    assert client.post(f"/api/ai/workflows/{wid}/chat/{bad['id']}/apply", headers=alice.headers).status_code == 409
