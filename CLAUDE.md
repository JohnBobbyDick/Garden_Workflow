# CLAUDE.md — AI Security Workflow (Cyber Garden 2026, кейс «Центр-инвест»)

Память проекта для Claude Code. Зеркало для Codex — `AGENTS.md` (держите оба файла в синхроне).

## Что это
Визуальная платформа автоматизации проверок безопасности кода: граф нод (триггер → источник кода → собственные
сканеры SECRET/SCA/SAST для Kotlin/Spring/Gradle → логика → AI-объяснение → уведомления/экспорт/CI gate).
Собственный движок исполнения, собственные анализаторы, LLM только объясняет.

## Источники истины (по приоритету)
1. `Garden Центр-инвест.pdf` (официальное ТЗ) → 2. `prompt.md` (детальная постановка, разделы `§N`) → 3. `TZ.md` (чеклист).
- `todo.md` — рабочий план по фазам 0–8 с чекбоксами; отмечать `[x]` только после запущенной проверки.
- `docs/REPORT.md` — журнал фаз (что сделано, гейты, решения, честные ограничения). Дописывать после каждой фазы.
- `.superpowers/sdd/todo/progress.md` — леджер исполнения (rulings/решения), git-ignored.

## Жёсткие правила (нарушение = провал кейса)
- Никаких заглушек в продуктовом коде: `TODO`, `pass # later`, `NotImplementedError`, моки, фейковые результаты/интеграции.
- Запрещены готовые workflow-платформы (n8n, Node-RED) и чужие сканеры/правила (Semgrep, Gitleaks, Trivy, Bandit, Snyk, …).
- LLM ничего не обнаруживает — только объясняет готовые находки; ответ LLM проходит валидатор (`app/ai/validator.py`).
- Не подгонять под учебный репозиторий: `grep -R "repairdesk\|RepairTicketReader\|WarrantyHeaders" backend/app` должен быть пуст.
- `fixtures/organizer-training/`, `fixtures/mutants/`, `github.com/TBagirov/training` — только чтение. Запись (PR, комментарии,
  статусы) — только на локальных mock-серверах GitHub/GitLab. Запрет `allow_write` для репо организаторов зашит в коде.
- Секреты маскируются везде (логи, API, run_events, БД, промпты, отчёты, уведомления). Проверка — тест-канарейка
  `backend/tests/security/test_platform_security.py`.
- Сканировать можно только: репо организаторов, загруженные архивы, собственные фикстуры (allowlist + `APP_SCAN_ROOTS`).
- **Git: не коммитить и не пушить** — пользователь коммитит сам. `.env`/ключи в репозиторий не попадают (только `.env.example`).
- Язык: код/идентификаторы — английский; UI — RU по умолчанию + EN; документация (`README.md`, `docs/*`) — русский.

## Структура
- `backend/app/analyzers/{common,secrets,sca,sast,diff}` — собственные анализаторы (tree-sitter-kotlin), модель `Finding`.
- `backend/app/engine/` — граф, валидатор, исполнитель (asyncio, IF/skip, таймауты, отмена), события+SSE, очередь в БД
  (`FOR UPDATE SKIP LOCKED`), воркер, планировщик (уникальный слот), безопасные выражения/шаблоны.
- `backend/app/nodes/**` — ноды-плагины: **одна нода = один файл** с `@register_node`, автообнаружение пакета.
  `docs/NODES.md` генерируется: `make nodes-doc`.
- `backend/app/core/` — crypto (AES-256-GCM, версии ключа), masking, ssrf, repo_guard, security (JWT/argon2), audit, errors.
- `backend/app/ai/` — провайдеры NVIDIA Nemotron (`nvidia`) и Ollama (`ollama`), промпты, схемы,
  валидатор достоверности, детерминированный fallback.
- `backend/app/api/` — REST под `/api`, единый формат ошибок `{"error":{"code","message","details"}}`.
- `frontend/src/` — React 18 + TS + Vite + Tailwind + `@xyflow/react` **v13** + Zustand + TanStack Query + i18next.
  Редактор: `src/editor/`, формы из JSON Schema: `src/editor/SchemaForm.tsx` + `src/lib/schemaForm.ts`.
- `scripts/mock_services.py` — локальные mock Telegram/SMTP/Webhook для демо; `scripts/gen_nodes_doc.py`.

## Команды (Windows: venv в `backend/.venv/Scripts`, Linux/macOS: `bin`; Makefile определяет сам)
- Установка: `cd backend && uv venv -p 3.12 .venv && uv pip install -e ".[dev]"`; `cd frontend && npm ci`.
- Тесты backend: `cd backend && .venv/Scripts/pytest -q` (≈480 тестов, ~1.5 мин). Eval точности: `pytest -m eval -s tests/eval`
  (учебный набор 15/15 + 3 мутанта). PostgreSQL: `make test-pg` (docker, порт 55432).
- Lint: `.venv/Scripts/ruff check app tests ../scripts`; `cd frontend && npx tsc -b --noEmit`.
- Frontend: `npx vitest run`; e2e: `npx playwright test` (использует системный Edge, поднимает свой backend+vite).
- Dev-стек: `alembic upgrade head` → `APP_INPROCESS_WORKER=true uvicorn app.main:app --port 8000`; `cd frontend && npx vite`.
- Миграции: после изменения моделей — `alembic revision --autogenerate`, затем тест `tests/integration` (`alembic check`).

## Подводные камни (выучено на практике)
- `Finding.id` должен быть стабилен между запусками — нельзя класть в `context_key` адреса узлов tree-sitter (`node.id`).
- Лог-фильтр маскирования не должен ломать `record.args` (uvicorn access-лог распаковывает 5 аргументов); не-строковые
  аргументы (например `httpx.URL` с токеном бота) маскируются через `str()`.
- `socket.getfqdn()` на этой машине ~12 с: в SMTP задавать `local_hostname`/`server_hostname` явно.
- `@xyflow/react` v13: нет `applyNodeChanges` — изменения применяются `changes.applyTo(nodes)`; нет пропа `colorMode`.
- Windows без прав на symlink: тесты используют `symlink_or_skip` из `backend/tests/conftest.py`.
- Тестовое окружение изолируется в `backend/tests/conftest.py` (свой `APP_DATA_DIR`, ключи).
- macOS: Playwright — `PW_CHANNEL=chrome npx playwright test` (системный Chrome); после `git pull` синхронизировать
  окружение (`uv pip install -e ".[dev]"`, `npm ci`). `ruff` запускать из `backend/` (там конфиг), иначе `--fix` снимает нужные `noqa`.
- `git ls-tree` в подкаталоге выдаёт пути от cwd — для `git show <rev>:<path>` нужен `--full-name`.
- Официальный порог выгрузки `submission.json`: `OFFICIAL_MIN_CONFIDENCE = 0.6`.
- `Masker.mask()` эвристически маскирует `password…[:=] значение` — на коде это ломает `val password: String`.
  Для проверенного кода (AutoFix `new_snippet`, «+»-строки патча) использовать `Masker.mask_known()`.
- Фикстура `scm` (tests/ci) делает `get_settings.cache_clear()` — запрашивать её **до** фикстур, которые патчат
  `get_settings()` (например `project_dir`), иначе патч теряется.
- Живой прогон Nemotron на синтетической находке описан в разделе 8 `docs/REPORT.md`. Автотесты используют локальные HTTP-серверы.
- Docker: на этой машине порт 8080 занят посторонним traefik — для Compose `FRONTEND_PORT=8088` (+`APP_PUBLIC_URL`,
  `APP_CORS_ORIGINS`). Compose-backend занимает :8000 — перед `npx playwright test` делать `docker compose down`.
- Свежий клон: каталог SQLite создаёт `app.db.ensure_sqlite_dir` (и в `alembic/env.py`) — не убирать.
- `docs/API.md` генерируется (`make api-doc`); новый эндпоинт → русская строка в `scripts/gen_api_doc.py::RU`.
- UI = одно рабочее пространство (спека `docs/superpowers/specs/2026-11-21-workspace-redesign-design.md`):
  - каркас `frontend/src/workspace/` (левая колонка, панели `?panel=history|templates|ci|overview|settings|compare`,
    «Новая проверка» `?new=1`, смена источника `?source=1`);
  - холст `frontend/src/editor/CanvasPage.tsx`, итоги запуска `frontend/src/results/`;
  - старые страницы рендерятся в панелях через `EmbeddedContext` (`components/layout/embedded.ts`);
  - старые адреса редиректит `workspace/routes.ts::legacyRedirect`; `/runs/:id` обязан работать.
- Анимации выполнения — только CSS в `frontend/src/editor/neon.css`. Не анимировать CSS `transform` у SVG-групп
  React Flow (`.react-flow__edge-textwrapper`): это сбивает позицию подписи.
- Провайдер платформы по умолчанию — NVIDIA Nemotron (`NVIDIA_API_KEY`). Локальный вариант — `LLM_PROVIDER=ollama`,
  `OLLAMA_URL` и `OLLAMA_MODEL`. Тесты отключают провайдер платформы через `LLM_ENABLED=false`.
- E2E: ноду из палитры перетаскивать через поиск «Найти блок…»; перенос ноды на холсте — `page.mouse` со `steps`.
  В headless-браузере здесь `requestAnimationFrame` на паузе — FPS так не измерить.
- Windows: подпроцесс в тестах — `sys.executable` (не `python3`, это заглушка Store) и окружение родителя
  (без `SYSTEMROOT` не инициализируется SSL).
- `path` находки — от корня **проекта**, не репозитория (замечание ментора: `src/main/…`, не `training-project/src/…`).
  Корень определяет `app/analyzers/common/project_root.py` в ноде `source.repo`, если `subdir` пуст; найденный корень
  пишется в `run.source.subdir` (+`subdir_detected`) — по нему же AutoFix и PR пересобирают исходники.
  Точность (`tests/eval`) мерить и при корне = весь репозиторий: `tests/api/test_project_root_detection.py`.
- Оценка полезности AI на всём наборе: `python -m app.ai.eval_report` (нужен ключ модели; без него — код 2).

## Процесс
Работа по фазам из `todo.md` с гейтами (тесты зелёные + ручная проверка на запущенном стеке), TDD (тест → красный →
код → зелёный), после фазы — запись в `docs/REPORT.md` и отметки в `todo.md`. Решения/отступления — строкой `Ruling:` в леджере.
