# CI/CD

Платформа встраивается в пайплайн двумя способами. Оба дают один результат: запуск сценария, вердикт PASS/FAIL,
отчёт-артефакт, статус коммита и комментарий в PR/MR.

| Способ | Как работает | Когда выбирать |
| --- | --- | --- |
| **CLI в пайплайне** | Job скачивает `aisw_ci.py` (только stdlib Python 3.8+), упаковывает рабочую копию и отправляет её в `POST /api/v1/ci/runs`, ждёт результат и завершается кодом 0/1. | Платформа недоступна для git-клона, приватный код, нужен «красный» job. |
| **Вебхук** | GitHub/GitLab присылает `push` / `pull_request` / `merge_request` в `/api/v1/webhooks/{github,gitlab}`. Платформа клонирует репозиторий из allowlist и запускает подписанные сценарии (нода `trigger.webhook`). | Платформа достижима из интернета, без изменений пайплайна. |

## 1. CLI в пайплайне

1. **Настройки → Интеграция:** выпустите API-токен workspace (значение показывается один раз) и скопируйте YAML.
   Генератор — `GET /api/ci/yaml?provider=github|gitlab&workflow_id=…`.
2. Положите в CI-переменные `AISW_URL` (адрес платформы) и `AISW_TOKEN` (секрет).
3. Включите защиту ветки. GitHub: Branch protection → «Require status checks to pass» → `aisw`. GitLab: «Pipelines
   must succeed».

```bash
python aisw_ci.py --url "$AISW_URL" --workflow <workflow_id> --out aisw-report [--base main] [--no-comment]
```

| Код выхода | Значение |
| --- | --- |
| `0` | PASS: нода `output.ci_gate` пропустила изменения (по умолчанию нет новых Critical). |
| `1` | FAIL: ворота закрыты, job красный, merge заблокирован защитой ветки. |
| `2` | Ошибка конфигурации или связи (нет токена, сценарий не найден, тайм-аут). |

- **Diff-aware.** CLI передаёт base-ветку (`--base`, иначе `GITHUB_BASE_REF` /
  `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`, иначе `main`). Платформа делит находки на `new` и `existing`, ворота
  обычно настраивают только на новые. Нужен полный clone: `fetch-depth: 0` / `GIT_DEPTH: 0` (генератор YAML ставит
  его сам).
- **Отчёт:** `aisw-report/report.md`, `submission.json` и вердикт. В GitHub отчёт также пишется в Step Summary.
- **Комментарий в PR/MR:** CLI сам обновляет один комментарий через `GITHUB_TOKEN` / `GITLAB_TOKEN` пайплайна
  (`--no-comment` отключает). Секреты в комментарии замаскированы.

## 2. Вебхук

1. **Настройки → Allowlist:** добавьте репозиторий. Для статусов и комментариев включите `allow_write` (admin,
   пишется в аудит) и сохраните токен `repo_write_token` в хранилище. Для репозитория организаторов `allow_write`
   запрещён кодом.
2. В сценарии используйте триггер `trigger.webhook`, выберите провайдера и события, укажите секрет вебхука из
   хранилища.
3. В репозитории: Settings → Webhooks → `https://<платформа>/api/v1/webhooks/github` с тем же секретом. GitHub
   проверяется по HMAC `X-Hub-Signature-256`, GitLab — по `X-Gitlab-Token`.

- **Идемпотентность:** повторная доставка с тем же `X-GitHub-Delivery` / `X-Gitlab-Event-UUID` новый запуск не
  создаёт.
- **Статус:** при создании запуска — `pending` с контекстом `aisw/security`, после завершения — `success` или
  `failure` со ссылкой на запуск.
- **Комментарий в PR/MR:** итоги, новые находки, вердикт. Один комментарий обновляется при каждом push (маркер в
  теле).
- **Журнал доставок и статусов:** Настройки → Интеграция (`GET /api/ci/webhooks/status`).

## 3. AutoFix → Pull Request

Для репозиториев с `allow_write` проверенное исправление можно открыть как PR/MR: ветка `autofix/<finding_id>`,
метка `security-autofix`, повторный вызов обновляет тот же PR. Для загруженных архивов, каталогов и репозитория
организаторов доступен только `.patch`. Подробности — [TEAM_FEATURES.md, раздел 3](TEAM_FEATURES.md).

## Демо без интернета

- **Compose, профиль `mock`.** Поднимает локальный GitHub/GitLab REST на `:8026` (журнал запросов —
  `GET /_requests`) и приёмник Telegram/Webhook/SMTP. Адреса `mock:8025` и `mock:8026` уже разрешены в
  `APP_SSRF_ALLOW_HOSTS`, поэтому статусы, комментарии и PR можно направлять на mock из UI.
- **Скриптовые демо** запускаются на dev-стеке (локальный `uvicorn`). Каждое создаёт временный git-репозиторий и
  поднимает свой mock GitHub (порт 18090):
  - `make demo-diff`: PR с новой уязвимостью → FAIL, статус и комментарий; исправление → PASS, комментарий обновлён;
  - `make demo-autofix`: AutoFix → PR на mock → повторный diff-aware прогон ветки исправления → PASS.

  Перед запуском API стартуйте с переменными окружения:

  ```bash
  APP_SCAN_ROOTS=$PWD/fixtures,/tmp/aisw-demo APP_SSRF_ALLOW_HOSTS=127.0.0.1:18090,127.0.0.1:18091 \
  APP_INPROCESS_WORKER=true backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000
  ```

  `/tmp/aisw-demo` — каталог по умолчанию из `tempfile.gettempdir()`. На macOS это `$TMPDIR/aisw-demo`, его можно
  задать явно через `AISW_DEMO_ROOT`.
