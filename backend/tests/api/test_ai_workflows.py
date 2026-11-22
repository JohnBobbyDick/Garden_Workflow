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

    for _ in range(3):
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
    for _ in range(3):
        script.reply({"explanation": "x", "operations": [{"op": "connect", "source": "sec", "source_port": "out",
                                                      "target": "src", "target_port": "in"}]})
    bad = client.post(f"/api/ai/workflows/{wid}/chat", json={"message": "сломай"}, headers=alice.headers).json()
    assert bad["valid"] is False and bad["status"] == "failed" and bad["issues"]
    assert client.post(f"/api/ai/workflows/{wid}/chat/{bad['id']}/apply", headers=alice.headers).status_code == 409


def test_chat_retries_bad_operations_then_guards_against_stale_apply(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply(PDF_GRAPH)
    wf = gen(client, alice, PDF_PROMPT, create=True).json()
    url = f"/api/workflows/{wf['workflow_id']}"
    chat = f"/api/ai/workflows/{wf['workflow_id']}/chat"
    script.reply("not json").reply({"operations": [{"op": "remove_node", "node_id": "absent"}]}).reply(
        {"operations": [{"op": "update_node", "node_id": "mail", "label": "Почта команды"}]})
    proposal = client.post(chat, headers=alice.headers, json={"message": "Переименуй почту"}).json()
    assert proposal["valid"] and proposal["attempts"] == 3
    assert "absent" in script.requests[-1]["body"]["messages"][-1]["content"]
    assert proposal["diff"]["changed_nodes"] == ["mail"]
    current = client.get(url, headers=alice.headers).json()["graph"]
    current["nodes"][0]["label"] = "Ручное изменение"
    assert client.put(url, headers=alice.headers, json={"graph": current}).status_code == 200
    stale = client.post(f"{chat}/{proposal['id']}/apply", headers=alice.headers)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "proposal_stale"
    assert client.get(url, headers=alice.headers).json()["graph"]["nodes"][0]["label"] == "Ручное изменение"


def test_restored_proposal_matches_preview_and_is_workspace_scoped(client, alice, bob, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply(PDF_GRAPH)
    wid = gen(client, alice, PDF_PROMPT, create=True).json()["workflow_id"]
    chat = f"/api/ai/workflows/{wid}/chat"
    script.reply({"explanation": "Добавляю метку", "operations": [
        {"op": "update_node", "node_id": "mail", "label": "Почта команды"}]})
    proposal = client.post(chat, headers=alice.headers, json={"message": "Переименуй почту"}).json()
    detail = f"{chat}/{proposal['id']}"
    recovered = client.get(detail, headers=alice.headers)
    assert recovered.status_code == 200
    assert recovered.json() == proposal
    assert proposal["original_message"] == "Переименуй почту" and not proposal["stale"]
    assert client.get(detail, headers=bob.headers).status_code == 404
    assert client.get(f"{chat}/{proposal['user_message_id']}", headers=alice.headers).status_code == 404
    graph = client.get(f"/api/workflows/{wid}", headers=alice.headers).json()["graph"]
    graph["nodes"][0]["label"] = "Ручное изменение"
    client.put(f"/api/workflows/{wid}", headers=alice.headers, json={"graph": graph}).raise_for_status()
    recovered = client.get(detail, headers=alice.headers).json()
    assert recovered["stale"] and recovered["status"] == "proposed" and recovered["diff"] == proposal["diff"]
    assert len(script.requests) == 2


def test_apply_reject_have_one_winner_and_keep_exact_message_pair(client, db, alice, llm):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from threading import Barrier

    from app import models as m

    script, hp = llm
    configure(client, alice, hp)
    script.reply(PDF_GRAPH)
    wid = gen(client, alice, PDF_PROMPT, create=True).json()["workflow_id"]
    chat = f"/api/ai/workflows/{wid}/chat"
    proposals = []
    for label in ("А", "Б"):
        script.reply({"operations": [{"op": "update_node", "node_id": "mail", "label": label}]})
        proposals.append(client.post(chat, headers=alice.headers, json={"message": label}).json())
    a, b = proposals
    with db.session() as s:
        # Simulate interleaved timestamps. Identity must determine the authoring message.
        bot = s.get(m.WorkflowChatMessage, a["id"])
        s.get(m.WorkflowChatMessage, b["user_message_id"]).created_at = bot.created_at - timedelta(microseconds=1)
        s.commit()
    gate = Barrier(2)

    def resolve(action):
        gate.wait(timeout=5)
        return client.post(f"{chat}/{a['id']}/{action}", headers=alice.headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        applied, rejected = pool.map(resolve, ("apply", "reject"))
    assert sorted((applied, rejected)) == [200, 409]
    state = "applied" if applied == 200 else "rejected"
    history = {msg["id"]: msg["status"] for msg in client.get(chat, headers=alice.headers).json()}
    assert history[a["id"]] == history[a["user_message_id"]] == state
    assert history[b["id"]] == history[b["user_message_id"]] == "proposed"
    wf = client.get(f"/api/workflows/{wid}", headers=alice.headers).json()
    assert wf["version"] == (2 if applied == 200 else 1)


def test_generation_and_chat_mask_user_and_model_text_on_storage_and_retrieval(client, db, alice, llm):
    from copy import deepcopy

    from app import models as m

    secret = "sk-" + "canary" * 6
    prompt = f"Создай проверку {secret}"
    script, hp = llm
    configure(client, alice, hp)
    graph = deepcopy(PDF_GRAPH)
    graph["nodes"][0]["label"] = prompt
    script.reply(graph)
    wf = gen(client, alice, prompt, create=True, name=prompt).json()
    wid = wf["workflow_id"]
    assert secret not in json.dumps(wf)
    chat = f"/api/ai/workflows/{wid}/chat"
    script.reply({"explanation": prompt, "operations": [{"op": "update_node", "node_id": "mail", "label": prompt}]})
    response = client.post(chat, headers=alice.headers, json={"message": prompt})
    assert secret not in response.text
    for path in (f"/api/workflows/{wid}", chat, f"{chat}/{response.json()['id']}"):
        assert secret not in client.get(path, headers=alice.headers).text
    with db.session() as s:
        stored = s.get(m.Workflow, wid)
        assert secret not in stored.name + stored.description + json.dumps(stored.graph)
    assert secret not in json.dumps(script.requests)


def test_legacy_proposal_recovery_links_only_an_unambiguous_request(client, db, alice, llm):
    from app import models as m

    script, hp = llm
    configure(client, alice, hp)
    script.reply(PDF_GRAPH)
    wid = gen(client, alice, PDF_PROMPT, create=True).json()["workflow_id"]
    chat = f"/api/ai/workflows/{wid}/chat"
    message = "Переименуй почту"
    script.reply({"operations": [{"op": "update_node", "node_id": "mail", "label": "Рассылка"}]})
    prop = client.post(chat, headers=alice.headers, json={"message": message}).json()
    with db.session() as s:
        legacy = s.get(m.WorkflowChatMessage, prop["id"])
        legacy.proposal_details = legacy.user_message_id = None
        s.commit()
    path = f"{chat}/{prop['id']}"
    preview = client.get(path, headers=alice.headers).json()
    assert preview["original_message"] == message and preview["diff"] == prop["diff"]
    assert preview["needs_input"] == prop["needs_input"]
    assert client.post(f"{path}/apply", headers=alice.headers).status_code == 200
    assert client.post(f"{path}/reject", headers=alice.headers).status_code == 409
    applied = client.get(path, headers=alice.headers).json()
    assert applied["status"] == "applied" and applied["user_message_id"] == prop["user_message_id"]


def test_selected_node_roundtrips_and_deleted_selection_never_calls_llm(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply(PDF_GRAPH)
    wid = gen(client, alice, PDF_PROMPT, create=True).json()["workflow_id"]
    chat = f"/api/ai/workflows/{wid}/chat"
    script.reply({"operations": [{"op": "update_node", "node_id": "mail", "label": "Письмо"}]})
    prop = client.post(chat, headers=alice.headers, json={"message": "Переименуй", "selected_node_id": "mail"}).json()
    assert client.get(f"{chat}/{prop['id']}", headers=alice.headers).json()["selected_node_id"] == "mail"
    bad = client.post(chat, headers=alice.headers, json={"message": "Переименуй", "selected_node_id": "missing"})
    assert bad.status_code == 422 and len(script.requests) == 2


def test_credential_literal_in_model_operation_is_masked_in_entire_turn(client, db, alice, llm):
    from app import models as m

    secret = "opaque-unregistered-value-from-model"
    script, hp = llm
    configure(client, alice, hp)
    script.reply(TZ_GRAPH)
    wid = gen(client, alice, TZ_PROMPT, create=True).json()["workflow_id"]
    chat = f"/api/ai/workflows/{wid}/chat"
    script.reply({"explanation": f"Значение {secret}", "operations": [
        {"op": "update_node", "node_id": "tg", "label": f"Телеграм {secret}", "config": {"bot_token": secret}}]})
    result = client.post(chat, headers=alice.headers, json={"message": "Переименуй Telegram"})
    assert result.json()["valid"] and secret not in result.text
    with db.session() as s:
        msg = s.get(m.WorkflowChatMessage, result.json()["id"])
        assert secret not in msg.content + json.dumps([msg.operations, msg.result_graph, msg.proposal_details])


def test_ambiguous_legacy_proposal_does_not_resolve_another_user_turn(client, db, alice, llm):
    from app import models as m

    script, hp = llm
    configure(client, alice, hp)
    script.reply(PDF_GRAPH)
    wid = gen(client, alice, PDF_PROMPT, create=True).json()["workflow_id"]
    chat = f"/api/ai/workflows/{wid}/chat"
    script.reply({"operations": [{"op": "update_node", "node_id": "mail", "label": "Команда"}]})
    proposal = client.post(chat, headers=alice.headers, json={"message": "Переименуй"}).json()
    with db.session() as s:
        bot = s.get(m.WorkflowChatMessage, proposal["id"])
        user = s.get(m.WorkflowChatMessage, proposal["user_message_id"])
        bot.user_message_id = bot.proposal_details = None
        other = m.WorkflowChatMessage(workflow_id=wid, role="user", content="Другая правка",
                                      status="proposed", created_at=user.created_at)
        s.add(other)
        s.commit()
    path = f"{chat}/{proposal['id']}"
    assert client.get(path, headers=alice.headers).json()["original_message"] is None
    assert client.post(f"{path}/reject", headers=alice.headers).status_code == 200
    history = {msg["id"]: msg["status"] for msg in client.get(chat, headers=alice.headers).json()}
    assert history[proposal["id"]] == "rejected"
    assert history[proposal["user_message_id"]] == history[other.id] == "proposed"
