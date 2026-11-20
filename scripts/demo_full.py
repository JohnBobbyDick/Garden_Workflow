"""Demo scenario §21 end to end against the Compose stack (profiles ``mock`` + ``ollama``), steps 1–8 and 10.

Diff-aware PR (step 9) and AutoFix PR (step 11) need a temporary git repository and their own mock GitHub — they are
covered by ``scripts/demo_diff.py`` / ``scripts/demo_autofix.py`` on the dev stack. The drag-and-drop part of step 3
is covered by the Playwright e2e test (``frontend/e2e/flow.spec.ts``); here the same graph is created via the API.

Prints one line per check and a JSON summary to ``--out`` (used in docs/REPORT.md). Run with the backend venv:

    python scripts/demo_full.py --url http://localhost:8088 --model qwen2.5:3b
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.export.validator import validate_submission  # noqa: E402

TRAINING = ROOT / "fixtures" / "organizer-training" / "training-project"
ORGANIZER_REPO = "https://github.com/TBagirov/training"
RESULTS: list[dict] = []


def check(step: str, ok: bool, detail: str) -> bool:
    RESULTS.append({"step": step, "ok": bool(ok), "detail": detail})
    print(f"[{'OK ' if ok else 'FAIL'}] {step}: {detail}", flush=True)
    return bool(ok)


def graph(nodes: list[tuple], edges: list[tuple]) -> dict:
    return {"schema_version": 1,
            "nodes": [{"id": i, "type": t, "position": {"x": 220 * k, "y": 0}, "config": cfg}
                      for k, (i, t, cfg) in enumerate(nodes)],
            "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": d, "target_port": dp}
                      for k, (s, sp, d, dp) in enumerate(edges)]}


def zip_dir(src: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())
    return buf.getvalue()


def patched_copy(dst: Path, fixes: list[tuple[str, str, str]]) -> Path:
    """Copy of the training project (fixtures stay untouched) with literal replacements applied."""
    shutil.copytree(TRAINING, dst)
    for rel, old, new in fixes:
        f = dst / rel
        text = f.read_text(encoding="utf-8")
        assert old in text, f"{rel}: pattern not found"
        f.write_text(text.replace(old, new, 1), encoding="utf-8")
    return dst


def main() -> int:  # noqa: C901, PLR0915 - a linear demo script
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("AISW_URL", "http://localhost:8080"))
    ap.add_argument("--mock", default="http://localhost:8025")
    ap.add_argument("--model", default="qwen2.5:3b")
    ap.add_argument("--ollama", default="http://ollama:11434", help="Ollama URL as seen from the backend")
    ap.add_argument("--no-llm", action="store_true", help="skip AI provider setup (deterministic mode)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.url, timeout=900)
    tmp = Path(tempfile.mkdtemp(prefix="aisw-full-"))
    t0 = time.time()

    def wait(rid: str, limit: float = 1800) -> dict:
        end = time.time() + limit
        while time.time() < end:
            run = c.get(f"/api/runs/{rid}", headers=h).json()
            if run["status"] in ("success", "failed", "cancelled"):
                time.sleep(1)
                return c.get(f"/api/runs/{rid}", headers=h).json()
            time.sleep(1)
        raise TimeoutError(rid)

    def start(wf_id: str) -> dict:
        r = c.post(f"/api/workflows/{wf_id}/run", headers=h, json={})
        if r.status_code >= 400:
            raise RuntimeError(f"run rejected: {r.text[:500]}")
        return wait(r.json()["id"])

    def received() -> list[dict]:
        return httpx.get(f"{args.mock}/_received", timeout=10).json()

    # ---- 1. registration → workspace → AI + Telegram/SMTP ---------------------------------------------------------
    email = f"demo-{uuid.uuid4().hex[:6]}@example.org"
    reg = c.post("/api/auth/register", json={"email": email, "password": "Demo-Passw0rd!", "display_name": "Demo"})
    reg.raise_for_status()
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    ws = c.post("/api/workspaces", headers=h, json={"name": "Команда безопасности", "timezone": "Europe/Moscow"})
    check("1 workspace", ws.status_code in (200, 201), f"пользователь {email}, создан workspace «{ws.json().get('name')}»")
    ws = ws.json()["id"]
    if not args.no_llm:
        put = c.put("/api/settings/ai", headers=h, json={"workspace_id": ws, "enabled": True, "provider": "ollama",
                                                         "base_url": args.ollama, "model": args.model,
                                                         "timeout": 600, "json_mode": "auto"})
        test = c.post("/api/settings/ai/test", headers=h, json={"workspace_id": ws})
        check("1 AI provider", put.status_code == 200 and test.status_code == 200 and test.json().get("ok", True),
              f"ollama {args.model}: {test.text[:160]}")
    tg_token = f"{uuid.uuid4().int % 10**10}:{uuid.uuid4().hex}"
    tg = c.post("/api/credentials", headers=h, json={"workspace_id": ws, "name": "telegram-bot", "kind": "telegram",
                                                     "value": tg_token}).json()
    check("1 notifications", "id" in tg and tg_token not in json.dumps(tg),
          "токен Telegram сохранён в хранилище, API вернул только маску; SMTP — mock:2525")

    # ---- 2. project from the organizer repository (git_url, allowlist) --------------------------------------------
    prj = c.post("/api/projects", headers=h, json={"workspace_id": ws, "name": "training (organizers)",
                                                    "source_mode": "git_url", "git_url": ORGANIZER_REPO,
                                                    "subdir": "training-project"})
    check("2 project git_url", prj.status_code in (200, 201), f"{ORGANIZER_REPO} (subdir training-project): "
                                                            f"HTTP {prj.status_code}")
    pid = prj.json()["id"]

    # ---- 3. the demo workflow ---------------------------------------------------------------------------------------
    nodes = [("trigger", "trigger.manual", {}), ("source", "source.repo", {"mode": "project"}),
             ("secrets", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {}),
             ("merge", "logic.merge", {}), ("score", "analysis.security_score", {}),
             ("if", "logic.if_else", {"expression": "severity.max >= HIGH"}),
             ("ai", "ai.report", {"generate_fix_diff": True}),
             ("export", "output.report_export", {}),
             ("telegram", "notify.telegram", {"bot_token": tg["id"], "chat_id": "100500",
                                              "template": "Найдено {{findings.count}}, critical "
                                                          "{{severity.critical}}, score {{score.value}}"}),
             ("smtp", "notify.smtp", {"host": "mock", "port": 2525, "security": "none",
                                      "from_addr": "aisw@example.org", "to": ["team@example.org"],
                                      "subject": "AISW: {{findings.count}} находок"}),
             ("webhook", "notify.webhook", {"url": "http://mock:8025/aisw-clean"})]
    edges = [("trigger", "out", "source", "in"), ("source", "out", "secrets", "in"), ("source", "out", "sca", "in"),
             ("source", "out", "sast", "in"), ("secrets", "out", "merge", "in"), ("sca", "out", "merge", "in"),
             ("sast", "out", "merge", "in"), ("merge", "out", "score", "findings"),
             ("source", "out", "score", "repo"), ("merge", "out", "if", "in"), ("if", "true", "ai", "in"),
             ("if", "true", "export", "in"), ("ai", "out", "export", "ai"), ("export", "out", "telegram", "in"),
             ("export", "out", "smtp", "in"), ("if", "false", "webhook", "in")]
    g = graph(nodes, edges)
    val = c.post("/api/workflows/validate", headers=h, json={"workspace_id": ws, "graph": g}).json()
    wf = c.post("/api/workflows", headers=h, json={"workspace_id": ws, "name": "Полный аудит", "graph": g,
                                                   "project_id": pid})
    check("3 workflow", wf.status_code in (200, 201), f"{len(nodes)} нод, {len(edges)} рёбер; проверка графа: "
                                                      f"{'ошибок нет' if not val.get('errors') else val['errors']}")
    wf_id = wf.json()["id"]

    # ---- 4. run --------------------------------------------------------------------------------------------------
    before = len(received())
    t_run = time.time()
    run = start(wf_id)
    rid = run["id"]
    statuses = {n["node_id"]: n["status"] for n in run["nodes"]}
    check("4 run", run["status"] == "success", f"{run['status']} за {time.time() - t_run:.0f} с; статусы нод: "
                                                f"{statuses}")
    ev = c.get(f"/api/runs/{rid}/events", headers=h, timeout=30).text
    kinds = {line.split(":", 1)[1].strip() for line in ev.splitlines() if line.startswith("event:")}
    check("4 live events", {"node.status", "edge.data", "run.status"} <= kinds, f"SSE: {sorted(kinds)}")
    s = run["summary"]
    check("4 findings", s.get("total") == 15, f"{s.get('total')} находок, по критичности {s.get('by_severity')}")
    check("4 false branch", statuses.get("webhook") == "skipped", "ветка false (webhook) пропущена")
    rep = c.get(f"/api/runs/{rid}/ai-report", headers=h).json()
    met = rep.get("metrics") or {}
    fixes = sum(1 for i in (rep.get("report") or {}).get("findings", []) if i.get("fix"))
    check("4 AI report", rep.get("report") is not None,
          f"ai_generated={rep.get('ai_generated')} {rep.get('provider')}/{rep.get('model')}; принято "
          f"{met.get('valid_items')} из {met.get('total_items')}, отброшено {met.get('dropped')}, выдуманных id "
          f"{len(met.get('hallucinated_ids') or []) if isinstance(met.get('hallucinated_ids'), list) else met.get('hallucinated_ids')}, "
          f"fix-диффов сохранено {met.get('fixes_kept')} (в отчёте {fixes}), дополнено шаблоном "
          f"{met.get('filled_deterministic')}")
    new = received()[before:]
    kinds_rx = [r["kind"] for r in new]
    check("4 notifications", "telegram" in kinds_rx and "smtp" in kinds_rx and tg_token not in json.dumps(new),
          f"на mock доставлено: {kinds_rx}; токен в записях замаскирован")
    arts = {a["name"]: a["url"] for a in run.get("artifacts", [])}
    sub = json.loads(c.get(arts["submission.json"], headers=h).text)
    errors = validate_submission(sub)
    check("4 submission.json", not errors and len(sub["findings"]) == 15,
          f"{len(sub['findings'])} находок, валидатор формата: {errors or 'ошибок нет'}")

    # ---- 5. fix the SQL injection in an uploaded copy → re-run → compare ---------------------------------------
    sql_file = "src/main/kotlin/lab/repairdesk/repair/RepairLookupController.kt"
    sql_fix = (sql_file, "WHERE frame_tag = '$frameTag'\", String::class.java)",
               "WHERE frame_tag = ?\", String::class.java, frameTag)")
    tls_fix = ("src/main/kotlin/lab/repairdesk/integration/SupplierHttpsClient.kt",
               "            hostnameVerifier = HostnameVerifier { _, _ -> true }\n", "")

    def upload(src: Path, name: str) -> str:
        r = c.post("/api/uploads", headers=h, data={"workspace_id": ws},
                   files={"file": (name, zip_dir(src), "application/zip")})
        r.raise_for_status()
        return r.json()["id"]

    lite_nodes = nodes[:7] + [("export", "output.report_export", {})]
    lite_edges = edges[:9] + [("merge", "out", "export", "in")]

    def archive_project(name: str, upload_id: str) -> tuple[str, str]:
        prj_id = c.post("/api/projects", headers=h, json={"workspace_id": ws, "name": name, "source_mode": "upload",
                                                          "upload_id": upload_id}).json()["id"]
        wf_x = c.post("/api/workflows", headers=h, json={"workspace_id": ws, "name": f"Аудит: {name}",
                                                         "graph": graph(lite_nodes, lite_edges),
                                                         "project_id": prj_id}).json()["id"]
        return prj_id, wf_x

    original = upload(TRAINING, "training.zip")
    sql_only = upload(patched_copy(tmp / "sql", [sql_fix]), "training-sql-fixed.zip")
    both = upload(patched_copy(tmp / "both", [sql_fix, tls_fix]), "training-sql-tls-fixed.zip")
    arc_prj, arc_wf = archive_project("training (архив)", original)
    r_base = start(arc_wf)
    c.patch(f"/api/projects/{arc_prj}", headers=h, json={"upload_id": sql_only}).raise_for_status()
    r_fixed = start(arc_wf)
    cmp_ = c.get("/api/runs/compare", headers=h, params={"base": r_base["id"], "head": r_fixed["id"]}).json()
    check("5 compare", len(cmp_["fixed"]) == 1 and not cmp_["new"],
          f"{r_base['summary']['total']} → {r_fixed['summary']['total']}: устранено {len(cmp_['fixed'])} "
          f"({', '.join(f['class'] for f in cmp_['fixed'])}), новых {len(cmp_['new'])}, без изменений "
          f"{len(cmp_['unchanged'])}")

    # ---- 10. Security Score: first run → two fixes → second run -------------------------------------------------
    sc_prj, sc_wf = archive_project("training (score)", original)
    s1 = start(sc_wf)
    c.patch(f"/api/projects/{sc_prj}", headers=h, json={"upload_id": both}).raise_for_status()
    s2 = start(sc_wf)
    score2 = c.get(f"/api/runs/{s2['id']}/score", headers=h).json()
    top = [f"{i.get('class') or i.get('title')}(+{i.get('expected_gain')})" for i in score2.get("priority", [])[:3]]
    check("10 score delta", (s2.get("score_delta") or 0) > 0,
          f"score {s1.get('score')} → {s2.get('score')} (дельта {s2.get('score_delta'):+}); находок "
          f"{s1['summary']['total']} → {s2['summary']['total']}; Priority Fix List: {len(score2.get('priority', []))} "
          f"пунктов, топ-3 {top}")
    t_plan = time.time()
    plan = c.post(f"/api/runs/{s2['id']}/sprint-plan", headers=h, json={})
    pj = plan.json() if plan.status_code < 500 else {"error": plan.text[:200]}
    items = (pj.get("plan") or {}).get("priority", []) if isinstance(pj, dict) else []
    check("10 AI sprint plan", plan.status_code in (200, 201),
          f"HTTP {plan.status_code} за {time.time() - t_plan:.0f} с: ai_generated={pj.get('ai_generated')}, "
          f"{pj.get('provider')}/{pj.get('model')}, пунктов {len(items)}, проверка: "
          f"{json.dumps((pj.get('validation') or {}).get('corrected_numbers', pj.get('validation')), ensure_ascii=False)[:200]}")

    # ---- 6. template: publish → search → use → edit the copy -----------------------------------------------------
    pub = c.post("/api/templates", headers=h, json={"workflow_id": wf_id, "name": f"Полный аудит Kotlin {uuid.uuid4().hex[:4]}",
                                                    "description": "Секреты, SCA, SAST, AI-объяснение и уведомления",
                                                    "category": "Full Security Audit", "tags": ["kotlin", "demo"]})
    tpl = pub.json()
    leaked = tg["id"] in json.dumps(tpl.get("graph")) or "100500" in json.dumps(tpl.get("graph"))
    check("6 publish", pub.status_code in (200, 201) and not leaked,
          f"параметры шаблона: {[p['name'] for p in tpl.get('parameters', [])]}; credential-ссылки и chat_id вычищены")
    found = c.get("/api/templates", headers=h, params={"q": "Полный аудит Kotlin"}).json()
    ids = [t["id"] for t in found.get("templates", [])]
    check("6 search", tpl["id"] in ids, f"поиск «Полный аудит Kotlin»: {len(ids)} результат(ов)")
    params = {p["name"]: (tg["id"] if p.get("type") == "credential" else
                          p.get("default") or ("100500" if "chat" in p["name"] else "http://mock:8025/aisw"))
              for p in tpl.get("parameters", [])}
    used = c.post(f"/api/templates/{tpl['id']}/use", headers=h, json={"workspace_id": ws, "params": params,
                                                                     "project_id": pid, "name": "Аудит из шаблона"})
    copy_id = used.json().get("id")
    cp = c.get(f"/api/workflows/{copy_id}", headers=h).json() if copy_id else {}
    if cp:
        cp["graph"]["nodes"] = [n for n in cp["graph"]["nodes"] if n["id"] != "smtp"]
        cp["graph"]["edges"] = [e for e in cp["graph"]["edges"] if "smtp" not in (e["source"], e["target"])]
    upd = c.put(f"/api/workflows/{copy_id}", headers=h, json={"name": "Аудит из шаблона (без e-mail)",
                                                              "graph": cp.get("graph")}) if cp else None
    check("6 use + edit", used.status_code in (200, 201) and upd is not None and upd.status_code == 200,
          f"копия {copy_id} (forked_from {used.json().get('forked_from')}), правка: удалена нода smtp → "
          f"версия {upd.json().get('version') if upd is not None else None}")

    # ---- 7. CI: YAML, CLI exit 1 on Critical ---------------------------------------------------------------------
    gh = c.get("/api/ci/yaml", headers=h, params={"provider": "github", "workflow_id": wf_id})
    gl = c.get("/api/ci/yaml", headers=h, params={"provider": "gitlab", "workflow_id": wf_id})
    check("7 YAML", gh.status_code == 200 and "aisw_ci.py" in gh.text and gl.status_code == 200 and
          "aisw_security" in gl.text, f"GitHub Actions {len(gh.text)} байт, GitLab CI {len(gl.text)} байт")
    ci_nodes = [("t", "trigger.webhook", {"provider": "ci"}), ("src", "source.repo", {"mode": "project"}),
                ("secrets", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {}),
                ("merge", "logic.merge", {}), ("gate", "output.ci_gate", {"fail_on": "CRITICAL"})]
    ci_edges = [("t", "out", "src", "in"), ("src", "out", "secrets", "in"), ("src", "out", "sca", "in"),
                ("src", "out", "sast", "in"), ("secrets", "out", "merge", "in"), ("sca", "out", "merge", "in"),
                ("sast", "out", "merge", "in"), ("merge", "out", "gate", "in")]
    ci_wf = c.post("/api/workflows", headers=h, json={"workspace_id": ws, "name": "CI gate",
                                                      "graph": graph(ci_nodes, ci_edges)}).json()["id"]
    token = c.post("/api/api-tokens", headers=h, json={"workspace_id": ws, "name": "ci"}).json()["token"]
    cli = tmp / "cli"
    cli.mkdir()
    (cli / "aisw_ci.py").write_bytes(c.get("/api/ci/cli").content)
    work = tmp / "repo"
    shutil.copytree(TRAINING, work)
    env = {"AISW_TOKEN": token, "PATH": os.environ.get("PATH", "")}
    p_fail = subprocess.run([sys.executable, str(cli / "aisw_ci.py"), "--url", args.url, "--workflow", ci_wf,
                             "--out", str(tmp / "ci-out")], cwd=work, env=env, capture_output=True, text=True,
                            timeout=600)
    last = [ln for ln in p_fail.stdout.splitlines() if ln.startswith("aisw:")][-1:]
    check("7 CLI", p_fail.returncode == 1 and (tmp / "ci-out" / "submission.json").exists(),
          f"exit {p_fail.returncode}; {last}; отчёт: {sorted(x.name for x in (tmp / 'ci-out').iterdir())}")

    # ---- 8. AI generation from text → chat edit → run -----------------------------------------------------------
    if not args.no_llm:
        t_gen = time.time()
        gen = c.post("/api/ai/workflows/generate", headers=h, json={
            "workspace_id": ws, "create": True, "name": "AI: ежедневная проверка",
            "prompt": "Каждый день в 14:00 проверять проект на секреты и уязвимые зависимости; если есть Critical — "
                      "отправить отчёт в Telegram"}, timeout=1800)
        gj = gen.json()
        gnodes = [n["type"] for n in (gj.get("graph") or {}).get("nodes", [])]
        check("8 AI generate", gen.status_code in (200, 201) and bool(gnodes),
              f"HTTP {gen.status_code} за {time.time() - t_gen:.0f} с: ноды {gnodes or gj}")
        gen_wf = gj.get("workflow_id") or gj.get("id")
        if gen.status_code in (200, 201) and gen_wf:
            t_chat = time.time()
            chat = c.post(f"/api/ai/workflows/{gen_wf}/chat", headers=h, timeout=1800,
                          json={"message": "добавь отправку отчёта на e-mail team@example.org через SMTP mock:2525"})
            cj = chat.json()
            applied = None
            if chat.status_code == 200 and cj.get("valid"):
                applied = c.post(f"/api/ai/workflows/{gen_wf}/chat/{cj['id']}/apply", headers=h)
            types = [n["type"] for n in (applied.json()["graph"]["nodes"] if applied is not None and
                                         applied.status_code == 200 else [])]
            check("8 AI chat edit", "notify.smtp" in types,
                  f"HTTP {chat.status_code} за {time.time() - t_chat:.0f} с, valid={cj.get('valid')}, diff="
                  f"{json.dumps(cj.get('diff'), ensure_ascii=False)[:200]}; после применения: {types}")
            if "notify.smtp" in types:
                wfg = c.get(f"/api/workflows/{gen_wf}", headers=h).json()
                c.put(f"/api/workflows/{gen_wf}", headers=h, json={"project_id": pid, "graph": wfg["graph"]})
                rr = c.post(f"/api/workflows/{gen_wf}/run", headers=h, json={})
                if rr.status_code < 400:
                    gr = wait(rr.json()["id"])
                    check("8 AI workflow run", gr["status"] in ("success", "failed"),
                          f"{gr['status']} {gr.get('error') or ''}; находок {gr['summary'].get('total')}")
                else:
                    check("8 AI workflow run", False, f"запуск отклонён: {rr.text[:300]}")

    ok = all(r["ok"] for r in RESULTS)
    if args.out:
        Path(args.out).write_text(json.dumps({"results": RESULTS, "seconds": round(time.time() - t0)},
                                             ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[demo-full] {'OK' if ok else 'FAILED'}: {sum(r['ok'] for r in RESULTS)}/{len(RESULTS)} проверок, "
          f"{time.time() - t0:.0f} с")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
