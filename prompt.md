# PROMPT ДЛЯ CLAUDE OPUS — «AI Security Workflow» (Cyber Garden 2026, банк «Центр-инвест»)

Ты — ведущий инженер, который в одиночку и автономно строит законченный продукт. Ниже полное задание. Читай целиком до начала работы. Всё, что здесь написано как «должен», «обязан», «запрещено», — жёсткие требования, а не пожелания.

Рабочая директория: корень репозитория (`/Users/whoisniknek/PycharmProjects/Lampochki_CG`, git-репозиторий, ветка `main`). В корне лежат исходные документы: `Garden Центр-инвест.pdf` (официальное ТЗ кейса) и `TZ.md` (чеклист). Если что-то в этом промпте противоречит PDF, прав PDF, но противоречие нужно явно отметить в итоговом отчёте.

---

## 0. Как ты работаешь

1. **Автономно, по фазам** (раздел 19). После каждой фазы прохождение гейта обязательно: тесты зелёные, приложение/модуль реально запущен и проверен руками (curl, браузер/Playwright), только потом следующая фаза. Не останавливайся и не спрашивай подтверждения между фазами. Спрашивай пользователя только если упёрся в то, что невозможно решить самому (например, нет доступа к LLM вообще).
2. **Никаких заглушек.** Запрещены `TODO`, `pass # later`, `NotImplementedError`, моки вместо реальной логики в продуктовом коде, захардкоженные «результаты сканирования», фейковые интеграции. Если часть функциональности невозможно проверить в окружении (нет сети, нет LLM, нет Telegram-бота), реализуй её по-настоящему, проверь на локальном тестовом сервере с реальным HTTP/SMTP-обменом и честно напиши в отчёте, что именно проверено, а что нет.
3. **Правда важнее красивого отчёта.** Если тест падает или пункт ТЗ не выполнен — так и пиши. Не помечай пункт готовым без запущенной проверки и показанного вывода.
4. **Git:** делай локальные коммиты после каждой фазы (осмысленные сообщения). Не делай `push`. Не добавляй в репозиторий реальные секреты, `.env`, ключи; только `.env.example`.
5. Перед началом фазы 0 изучи содержимое корня репозитория и клонированный набор организаторов (раздел 3). Составь план в `docs/PLAN.md` (кратко: модули, порядок, риски), затем реализуй.
6. Язык: код и идентификаторы на английском; UI — русский по умолчанию с переключателем RU/EN; документация (`README.md`, `docs/*`) — на русском; AI-отчёты формируются на языке интерфейса пользователя.

---

## 1. Продукт

**AI Security Workflow** — визуальная платформа автоматизации проверок безопасности кода. Пользователь без написания кода собирает из блоков (нод) сценарий (workflow): триггер → получение кода → собственные сканеры (секреты, SCA, SAST для Kotlin/Spring Boot/Gradle) → логика (IF/ELSE, сравнение, regex) → AI-объяснение и рекомендации → уведомление (Telegram / SMTP / HTTP Webhook). Выполнение сценария отображается в реальном времени. Целевой пользователь: разработчик небольшой команды или стартапа, у которого нет корпоративных сканеров.

Платформа должна:
- автоматически **выявлять** уязвимости **собственными** анализаторами (не LLM, не чужие сканеры);
- объяснять простым языком, где и почему угроза, насколько она критична и что делать (**LLM только объясняет и обобщает**);
- встраиваться в CI/CD (GitHub Actions, GitLab CI) и ломать сборку при Critical;
- давать библиотеку шаблонов сценариев и AI-генерацию сценария по тексту.

Ориентир по UX визуального подхода: n8n (но n8n и Node-RED **нельзя** использовать в качестве основы или компонента).

---

## 2. Жёсткие ограничения (нарушение = провал)

- ❌ Не использовать готовые workflow-платформы (n8n, Node-RED и аналоги) как основу. PDF разрешает графовые библиотеки визуализации (React Flow, Rete.js) и готовые движки исполнения (Flowable, Temporal, Conductor), но мы **осознанно** выбираем **собственный движок** (раздел 6). Это решение команды, а не требование PDF; так и укажи в REPORT и презентации.
- ❌ Не использовать Semgrep, Gitleaks, Trivy, detekt с security-правилами, Bandit, OWASP Dependency-Check, Snyk, truffleHog, grype, osv-scanner и любые другие готовые сканеры или их движки, а также чужие наборы правил (в том числе копирование правил Semgrep/Gitleaks). Разрешено: regex, собственные парсеры, tree-sitter (грамматика Kotlin), собственные эвристики, библиотеки сравнения версий (или свой сравнитель), справочники уязвимостей.
- ❌ LLM **не** обнаруживает уязвимости. Она только объясняет, агрегирует, предлагает исправления по уже найденным анализаторами находкам.
- ❌ Никаких фиктивных результатов сканирования и фиктивных интеграций.
- ❌ **Не подгонять сканеры под учебный репозиторий:** запрещены проверки по имени файла, номеру строки, имени класса/переменной из набора организаторов, жёстко зашитые ожидания. Финальная проверка пройдёт на **скрытой вариации** проекта с теми же классами проблем, но другими именами, файлами, строками и немного другими приёмами. Правила обязаны быть общими (раздел 8, раздел 17 про мутантов).
- ❌ Не сканировать ничего, кроме: (а) репозитория организаторов (`https://github.com/TBagirov/training`), (б) загруженных пользователем архивов/файлов своих учебных проектов, (в) собственных синтетических фикстур. Сканирование произвольных внешних систем и репозиториев запрещено — реализуй технический запрет (allowlist, раздел 13).
- ❌ **Тестовые репозитории только для чтения.** Репозиторий организаторов (`https://github.com/TBagirov/training`), `fixtures/organizer-training/` и `fixtures/mutants/` служат только для оценки точности нашего проекта. В них **ничего не записывается**: никаких push, веток, коммитов, PR/MR, комментариев, commit statuses, правок файлов фикстур. Все сценарии записи (AutoFix PR, комментарии в PR, возврат статуса в CI) реализуются через настоящие вызовы GitHub/GitLab API, а проверяются и демонстрируются **только на локальных mock-серверах GitHub/GitLab**. Если для демо нужен git-репозиторий с историей, он создаётся во временной директории из копии фикстур.
- ❌ Не раскрывать секреты в логах, ответах API, UI, отчётах, событиях выполнения, БД-находках (значения секретов маскируются везде, раздел 13).
- ❌ Не считать модуль завершённым без запущенной проверки.

---

## 3. Входные данные организаторов

Организаторы дали публичный учебный репозиторий: **https://github.com/TBagirov/training** (Kotlin / Spring Boot 4 / Gradle Kotlin DSL; приложение «Repair Desk»; только синтетические данные; намеренно уязвимо). Финальная проверка — на скрытой вариации с теми же классами проблем.

**Первым делом (фаза 0):** склонируй его и скопируй содержимое (без `.git`) в `fixtures/organizer-training/` в нашем репозитории (это тестовый набор и демо-данные; лицензия/назначение — учебные). Структура набора:

- `training-project/` — проверяемый проект (корень проверки = эта папка): `build.gradle.kts`, `gradle.properties`, `gradle.lockfile`, `settings.gradle.kts`, `src/main/kotlin/lab/repairdesk/**`, `src/main/resources/{application.yml,schema.sql,data.sql}`.
- `vulnerability-database/vulnerabilities.json` + `schema.json` — справочник Maven-уязвимостей (вход для SCA).
- `ground-truth/training-findings.json` (+ `.md`) — эталон: 15 находок (`findings`) и 6 безопасных контролей (`controls`), которые **не должны** попасть в отчёт.
- `docs/submission-format.md`, `docs/training-result-example.json` — **обязательный формат выгрузки результатов**.

Перед проектированием анализаторов **прочитай все файлы набора целиком**, особенно: каждый `.kt` файл, `application.yml`, `build.gradle.kts`, `gradle.properties`, `gradle.lockfile`, `ground-truth/training-findings.json` (включая `alternateLocations`, `difficultyRationale`, `expectedDetection`), `docs/submission-format.md`, `vulnerability-database/README.md`.

### 3.1 Что организаторы требуют от результата

Платформа обязана уметь формировать **два отчёта из одного и того же набора находок**:
1. **Единый JSON** (UTF-8) `{"findings":[...]}` строго по `docs/submission-format.md`:
   - общие поля: `category` (`SECRET`|`SAST`|`SCA`, верхний регистр), `path` (относительно корня проверяемого проекта, `/`, без абсолютных путей, без `..`, регистр как в проекте), необязательные `severity` (`LOW|MEDIUM|HIGH|CRITICAL`), `description`, `remediation`;
   - SECRET/SAST: `class` (код типа), `line` (целое, с 1), необязательный `endLine` (`line ≤ endLine ≤ line+14`);
   - SCA: `group`, `artifact`, `version` (точная, из lockfile если есть), `advisoryId` (**один** идентификатор: `id` записи справочника `GHSA-…` или её CVE из `aliases`); `path` = файл объявления зависимости (`build.gradle.kts`); если одной версии соответствует несколько разных уязвимостей — отдельная находка на каждую; если CVE и GHSA об одной уязвимости — один идентификатор.
   - Коды `class` для учебных типов (используй **точно** эти строки): SECRET: `password`, `api-key`, `configuration-token`, `secret-fallback`, `recoverable-token`; SAST: `sql-injection`, `tls-verification`, `credentialed-cors`, `route-authorization`, `object-authorization`. Для других типов допускаются свои коды (например `private-key`, `aws-access-key`, `jwt`, `db-credentials`, `path-traversal`, `unsafe-deserialization`, `weak-crypto`…).
2. **Читаемый отчёт** (таблица в UI + экспорт в Markdown и HTML): категория, название, краткое описание, место (файл:строки; для SCA — файл объявления, координаты с версией, CVE/GHSA), severity, рекомендация. Значения секретов скрыты в обоих отчётах.

Это закладывается как нода `report-export` (раздел 7) и API-эндпоинты экспорта запуска. JSON-экспорт должен проходить встроенный валидатор формата (напиши его по спецификации), невалидный экспорт — ошибка, а не молчаливая выдача.

### 3.2 Что в учебном наборе нужно обнаруживать (по эталону; ориентир качества)

15 находок: SECRET ×5 (`password` в коде; `api-key` в заголовке `X-Api-Key`; `configuration-token` bearer-токен в `application.yml`; `secret-fallback` — токен по умолчанию, когда нет переменной окружения; `recoverable-token` — токен собирается конкатенацией двух строковых констант), SCA ×5 (commons-text 1.9, jsoup 1.14.1, commons-compress 1.25.0 с версией через `val`, commons-net 3.8.0 объявленный через `add("implementation", …)` в несколько строк, org.json с версией из `providers.gradleProperty(...)` ← `gradle.properties`), SAST ×5 (SQL-инъекция через строковый шаблон Kotlin; отключённая проверка имени хоста TLS; CORS «любой origin + credentials»; `permitAll` на служебной выгрузке в `SecurityFilterChain`; чтение чужой заявки по ID без проверки владельца — межфайловый случай).

6 контролей, которые **не** должны сработать: документационный плейсхолдер `YOUR_API_KEY` в README; токен `${INVENTORY_TOKEN}` из окружения без значения по умолчанию; параметризованный SQL (`?`) рядом с уязвимым; публичный `GET /api/catalog/services` (каталог без персональных данных) в `permitAll`; обычный HTTPS-клиент со штатной проверкой; `commons-lang3:3.20.0` выше границы advisory.

Целевые метрики на учебном наборе: **15/15 находок** (категория+путь+класс, строка попадает в диапазон эталона, для SCA — координаты+версия+advisory), **0 срабатываний на контролях**, **0 дополнительных ложных находок** в `training-project/` (если дополнительные находки легитимны — проверь вручную и опиши в отчёте, а не прячь).

---

## 4. Принятые решения (не пересматривать)

| Область | Решение |
|---|---|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS, редактор — **React Flow (`@xyflow/react`)**, state — Zustand, запросы — TanStack Query, i18n RU/EN, темы Dark (по умолчанию) + Light с переключателем |
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic, Pydantic v2 |
| БД | PostgreSQL (в Docker Compose). Тесты могут идти на SQLite, если схема совместима, но обязательно один прогон интеграционных тестов на PostgreSQL |
| Очередь/исполнение | **Без Celery/Redis.** Собственный воркер: очередь запусков в таблице БД (`SELECT … FOR UPDATE SKIP LOCKED`), отдельный процесс `worker` в Compose (в dev допускается запуск в процессе API). События выполнения пишутся в таблицу `run_events` и отдаются клиенту по **SSE** |
| Анализаторы | Python, собственные. Kotlin: **tree-sitter + tree-sitter-kotlin**, запасной режим на regex; лёгкий межпроцедурный taint-анализ (раздел 8) |
| LLM | Единый адаптер **OpenAI-compatible API** (OpenRouter, Gemini compat-endpoint, vLLM, LM Studio…) + нативный **Ollama**; провайдер, URL, модель и ключ переключаются в настройках, без правки кода |
| Многопользовательность | Регистрация/вход (JWT access+refresh), рабочие пространства (workspaces), членство с ролями `admin`/`developer`/`viewer`, приглашение участников |
| Уведомления | Telegram, SMTP, HTTP Webhook — все три, каждый отдельным плагином-нодой |
| Развёртывание | `docker compose up` поднимает всё; отдельно описан dev-режим без Docker (uvicorn + vite) |
| Язык | RU по умолчанию + EN-переключатель (UI, AI-отчёты на языке интерфейса) |
| Режим | Полный продукт с качественным UX, но строго по фазам с гейтами |
| Фичи команды сверх ТЗ | Diff-aware scan, Security Score + тренд + Priority Fix List, AI AutoFix + PR (раздел 12А) — обязательны, реализуются после звёздочек |

---

## 5. Архитектура и структура проекта

Модульность — оценочный критерий: **добавление нового типа ноды = один новый файл с классом-плагином + (опционально) иконка**, без правок движка, API и редактора. Форма настройки ноды на фронтенде **генерируется из JSON Schema**, которую отдаёт бэкенд; фронтенд не знает конкретных нод.

```
/
├── prompt.md, TZ.md, Garden Центр-инвест.pdf          # исходники (не менять)
├── README.md                                           # запуск, обзор, скриншоты/сценарий демо
├── docker-compose.yml, .env.example, Makefile
├── fixtures/
│   ├── organizer-training/                             # копия набора организаторов (раздел 3)
│   └── mutants/                                        # ваши мутации учебного проекта (раздел 17)
├── backend/
│   ├── pyproject.toml, alembic/, app/
│   │   ├── main.py, config.py, db.py, deps.py
│   │   ├── core/ (security.py, crypto.py, masking.py, ssrf.py, repo_guard.py, errors.py)
│   │   ├── models/ (user, workspace, project, workflow, run, run_event, finding, ai_report, template, review, credential, api_token, ci_*, autofix, repo_allowlist)
│   │   ├── api/ (auth, workspaces, projects, workflows, runs, templates, credentials, settings, ci, webhooks, ai, dashboard, nodes)
│   │   ├── engine/ (graph.py, validator.py, executor.py, scheduler.py, events.py, context.py, worker.py)
│   │   ├── nodes/                                      # ПЛАГИНЫ НОД (автообнаружение пакета)
│   │   │   ├── base.py (NodeSpec, Port, registry, @register_node)
│   │   │   ├── triggers/ (manual.py, schedule.py, ci_webhook.py)
│   │   │   ├── source/ (repo_source.py)
│   │   │   ├── scanners/ (secrets_scan.py, sca_scan.py, sast_scan.py)
│   │   │   ├── logic/ (if_else.py, compare.py, regex_match.py, severity_filter.py, merge.py, set_value.py)
│   │   │   ├── analysis/ (diff_scan.py, security_score.py)
│   │   │   ├── ai/ (ai_report.py, autofix.py)
│   │   │   └── output/ (notify_telegram.py, notify_smtp.py, notify_webhook.py, report_export.py, ci_gate.py)
│   │   ├── analyzers/
│   │   │   ├── common/ (finding.py, severity.py, kotlin_ast.py, files.py)
│   │   │   ├── secrets/ (rules.py, entropy.py, kotlin_consts.py, config_files.py, detector.py)
│   │   │   ├── sca/ (gradle_parser.py, version_catalog.py, lockfile.py, resolver.py, versions.py, vulndb.py, cvss.py, matcher.py)
│   │   │   ├── sast/ (rules/*.py, taint.py, spring_security.py, callgraph.py, detector.py)
│   │   │   └── diff/ (git.py, hunks.py, classifier.py, sca_diff.py, blame.py)
│   │   ├── scoring/ (formula.py, trend.py, priority.py)
│   │   ├── autofix/ (context.py, generator.py, sca_bump.py, apply.py, validator.py, pr/{github.py,gitlab.py})
│   │   ├── ai/ (providers/{openai_compat.py,ollama.py}, prompts.py, schemas.py, validator.py, report_service.py, workflow_gen.py, chat.py)
│   │   ├── ci/ (yaml_generator.py, providers/{github.py,gitlab.py}, status.py, gate.py)
│   │   ├── export/ (submission_json.py, markdown.py, html.py)
│   │   └── seed/ (builtin_templates.py)
│   ├── tests/ (unit/, integration/, eval/, e2e_api/)
│   └── vulndb/ (vulnerabilities.json — копия справочника организаторов, используется по умолчанию)
├── cli/aisw_ci.py                                      # stdlib-only клиент для CI (раздел 12.2)
├── frontend/ (src/{pages,components,editor,store,api,i18n,theme}, tests/, e2e/)
└── docs/ (PLAN.md, ARCHITECTURE.md, NODES.md, ANALYZERS.md, API.md, CI_CD.md, AI.md, SECURITY.md, PRESENTATION_NOTES.md, REPORT.md)
```

Требования к расширяемости (проверяются в тесте): тест регистрирует тестовую ноду в отдельном файле, не изменяя ни одного файла движка/API/фронтенда; нода появляется в `GET /api/nodes`, форма строится из схемы, нода исполняется. Аналогично — новый AI-провайдер через новый класс в `ai/providers/`, новый канал уведомлений — новая нода.

---

## 6. Workflow-движок (собственный)

### 6.1 Формат графа (JSON, хранится в БД и экспортируется)
```json
{
  "schema_version": 1,
  "nodes": [{"id":"n1","type":"trigger.manual","position":{"x":0,"y":0},"config":{},"label":"Старт"}],
  "edges": [{"id":"e1","source":"n1","source_port":"out","target":"n2","target_port":"in"}]
}
```

### 6.2 Контракт ноды (`nodes/base.py`)
Каждая нода — класс с метаданными: `type` (например `scanner.secrets`), `category`, `title/description` (RU+EN), `inputs`/`outputs` (порты с типами данных), `config_schema` (JSON Schema, с пометками `secret: true` для секретных полей, `credential_ref` для ссылок на хранилище секретов), `async execute(ctx, inputs, config) -> outputs`. Реестр собирает ноды автообнаружением пакета `app.nodes`.

### 6.3 Формат данных между нодами
Единый конверт (`Envelope`): 
```json
{"type":"findings|repo|report|json|text|trigger|bool","data":{...},"meta":{"node_id":"…","produced_at":"…","summary":"найдено 7"}}
```
Типы портов: `trigger`, `repo` (ссылка на подготовленную рабочую директорию с файловым манифестом), `findings` (список единых `Finding`, раздел 10), `report`, `json`, `text`, `any`. Совместимость портов проверяет валидатор (редактор не даёт соединить несовместимые, бэкенд перепроверяет). Выходы IF/ELSE — два порта `true`/`false`. Нода-слияние `merge` принимает несколько `findings`-входов.

### 6.4 Исполнение
- Валидация перед запуском: ровно ≥1 триггер, нет циклов, нет висящих обязательных входов, все обязательные поля конфигурации заполнены, порты совместимы, ссылки на credentials существуют. Ошибки возвращаются списком с `node_id` (используются и редактором, и AI-генерацией).
- Топологический обход с параллельным исполнением независимых веток (`asyncio`); ветка, не выбранная IF/ELSE, помечается `skipped` вместе со всем, что зависит только от неё; нода с несколькими входами ждёт все *активные* входы.
- Статусы ноды: `pending → running → success | failed | skipped | cancelled`; статус запуска: `queued → running → success | failed | cancelled`. Таймаут ноды и запуска, отмена запуска, ошибка ноды не роняет воркер и записывается с маскированным сообщением.
- Каждое изменение статуса, входы/выходы (усечённое превью **после маскирования**), логи ноды и длительность — события в `run_events`; SSE `GET /api/runs/{id}/events` (с `Last-Event-ID` для догрузки). На фронтенде узлы раскрашиваются в реальном времени, на рёбрах видна передача данных (счётчик/превью), справа панель логов/данных выбранной ноды.
- **Планировщик:** собственный цикл (cron-выражения через допустимую библиотеку разбора cron либо своё), расписания хранятся в БД, переживают рестарт, не создают дубли при нескольких воркерах (блокировка/уникальный ключ слота). Часовой пояс настраивается (по умолчанию из настроек workspace).
- Повторяемость: запуск сохраняет **снимок графа** на момент старта (чтобы история не ломалась после правки сценария).

---

## 7. Реестр нод (обязательный минимум; все реализованы и протестированы)

| type | Назначение | Основные параметры |
|---|---|---|
| `trigger.manual` | Запуск по кнопке | — |
| `trigger.schedule` | Запуск по расписанию | cron или «каждый день в HH:MM», timezone |
| `trigger.webhook` | Запуск из CI/внешнего вызова (раздел 12) | provider, secret (credential), events |
| `source.repo` | Подготовка проверяемого кода | `mode`: `upload` (zip/tar), `git_url` (https, только allowlist), `path` (только внутри разрешённых корней), `ref`, project reference |
| `scanner.secrets` | Собственный поиск секретов | include/exclude globs, entropy threshold, режим `heuristics` on/off |
| `scanner.sca` | Собственная проверка зависимостей | путь к справочнику (по умолчанию встроенный), `include_transitive` (по умолчанию false), `include_test_scopes` |
| `scanner.sast` | Собственный SAST Kotlin/Spring | набор правил (вкл/выкл по id), min confidence |
| `logic.if_else` | Ветвление по условию | выражение над данными: поля `findings.count`, `severity.max`, `category`, `new_findings.count`, `verdict`, `score.value`, `score.delta`, сравнения, `and/or` — через собственный безопасный парсер выражений (без `eval`) |
| `logic.compare` | Сравнение значений/чисел/строк | left, operator, right |
| `logic.regex` | Регулярные выражения | pattern, flags, поле, режим match/extract/filter; защита от катастрофического бэктрекинга (таймаут/лимит длины) |
| `logic.severity_filter` | Фильтр находок по критичности/категории | min_severity, categories |
| `logic.merge` | Объединение наборов находок с дедупликацией | — |
| `ai.report` | AI-объяснения, последствия, исправления, общий отчёт | provider override, язык, `generate_fix_diff` |
| `notify.telegram` | Сообщение в Telegram | bot_token (credential), chat_id, шаблон |
| `notify.smtp` | Письмо | host, port, TLS/STARTTLS, user/password (credential), from, to[], шаблон |
| `notify.webhook` | HTTP Webhook | URL (SSRF-защита), method, headers (секретные — credential), тело-шаблон, подпись HMAC |
| `output.report_export` | Выгрузка отчёта | форматы `submission_json`, `markdown`, `html`; сохраняется в артефакты запуска |
| `output.ci_gate` | Итоговый статус для CI | `fail_on` (по умолчанию `CRITICAL`), политика; необязательный вход `verdict` от `scanner.diff` (тогда gate считается только по **новым** находкам); формирует `gate: pass|fail` для CI |
| `scanner.diff` | Diff-aware: делит находки на новые и существующие, выносит вердикт для PR (раздел 12А.1) | base branch, порог блокировки, include/exclude globs, режим `block`/`report_only`, `ignore_whitespace`, `on_missing_diff` |
| `analysis.security_score` | Security Score 0–100, дельта, тренд, Priority Fix List (раздел 12А.2) | веса (по умолчанию из настроек workspace) |
| `ai.autofix` | AI-патч для находки, самопроверка сканером, создание PR/MR (раздел 12А.3) | `auto_create_pr`, `max_findings`, `min_severity`, `target_branch`, шаблон описания PR |

Шаблоны сообщений поддерживают подстановки (`{{findings.count}}`, `{{severity.critical}}`, `{{new_findings.count}}`, `{{verdict}}`, `{{score.value}}`, `{{score.delta}}`, `{{run.url}}`, `{{ai.summary}}`) в безопасном шаблонизаторе; секреты в сообщение не подставляются.

**Уведомление обязано содержать отчёт** (PDF: «отправлять итоговое уведомление с отчётом о потенциальных уязвимостях»), а не только «проверка завершена»: SMTP — HTML-письмо со сводкой и таблицей находок + вложения `report.html`/`report.md`; Telegram — сводка (severity, топ находок, score, AI-вывод) + `sendDocument` с `report.md`; Webhook — JSON со сводкой, маскированными находками и ссылками на экспорт. Длинные отчёты корректно режутся по лимитам канала (4096 символов Telegram).

---

## 8. Собственные анализаторы

Общее: вход — каталог проекта (`repo`), выход — список `Finding` (раздел 10). Обходи файлы с учётом `.gitignore`-подобных исключений (`build/`, `.git/`, `node_modules/`, бинарники, лимит размера файла). Все пути в находках — относительные к корню проекта, нормализованные `/`. **Дедуплицируй**: одна проблема — одна находка (не дублируй один и тот же секрет по нескольким правилам, выбирай наиболее специфичный `class`). Объясни в `docs/ANALYZERS.md` каждое правило: что ищет, почему, как снижаются ложные срабатывания.

### 8.1 Поиск секретов (`analyzers/secrets`)

**Файлы:** `.kt .kts .java .properties .yml .yaml .json .xml .env* .toml .gradle .sh .sql .conf`, `Dockerfile`, прочие текстовые. README/документацию (`.md`, `.txt`, `docs/`) сканировать **можно**, но с подавлением плейсхолдеров (см. ниже).

**Слои обнаружения:**
1. **Сигнатуры известных токенов:** AWS Access Key (`AKIA/ASIA…` + рядом secret key), GitHub PAT (`ghp_`, `github_pat_`, `gho_`…), Telegram Bot Token (`\d{8,10}:[A-Za-z0-9_-]{35}`), Slack (`xox[abpr]-`), Stripe (`sk_live_`), Google API (`AIza…`), JWT (`eyJ….….…` + проверка base64url-структуры заголовка), блоки приватных ключей (`-----BEGIN (RSA|EC|OPENSSH|PGP|…)PRIVATE KEY-----`), URL с учётными данными (`scheme://user:pass@host`), JDBC-URL с паролем, Basic-auth в строках.
2. **Контекст имён:** пары «ключ → значение» в `yml/properties/json/env/kt/java`, где имя ключа/переменной соответствует секретной семантике (`password|passwd|pwd|secret|token|api[_-]?key|apikey|auth(orization)?|bearer|credential|private[_-]?key|access[_-]?key|client[_-]?secret`) и значение — непустая литеральная строка. Учитывай заголовки (`X-Api-Key`, `Authorization: Bearer …`), вызовы вида `setBearerAuth("…")`, `header("X-Api-Key", "…")`, `.password("…")`, именованные аргументы Kotlin, `const val`/`val` на уровне файла/класса, `data class` с дефолтами, `application.yml` вложенность (путь ключа собирается из YAML-структуры).
3. **Kotlin-AST (tree-sitter):** *разрешение констант*: локальные и файловые/классовые `val`/`const val` со строковыми литералами; конкатенация (`a + b`), строковые шаблоны с константами, `StringBuilder.append`, `listOf(..).joinToString`, `String.format`/`"…".format`, `String(Base64.getDecoder().decode("…"))`, `.reversed()`, `.trim()`, `.lowercase()`. Вычисленное значение проверяется теми же правилами, что и обычная строка; находка (`recoverable-token`) указывает диапазон строк от первого фрагмента до использования (в пределах 15 строк), в отчёт попадает только маска.
4. **Fallback-секреты:** `System.getenv("X") ?: "literal"`, `env.getProperty("x", "literal")`, `@Value("\${x:literal}")` и `${VAR:literal}` в YAML/properties, `?: "literal"` после чтения настроек, `getOrDefault("…","literal")`, `orElse("…")` — если имя секретной семантики или значение похоже на секрет → класс `secret-fallback`.
5. **Эвристика неизвестных секретов:** энтропия Шеннона (по алфавиту: hex, base64, смешанный) + длина + «разнообразие классов символов» + секретный контекст имени; пороги настраиваются; строки-идентификаторы (UUID без секретного контекста, хэши коммитов, версии, URL без кредов) не флагаются.

**Подавление ложных срабатываний (обязательно, это критерий оценки):** `${ENV}`/`#{…}`/`{{…}}`/`<…>`/`%…%` как значения; плейсхолдеры (`YOUR_*`, `<token>`, `xxx…`, `changeme`/`example`/`dummy`/`sample` как *значение документации*, `***`, пустые строки, `null`); тестовые/документационные пути понижаются в уверенности, но **не** игнорируются молча (в JSON-выгрузку попадают находки с confidence ≥ порога, остальные видны в UI как «низкая уверенность» и в выгрузку официального формата не идут — порог настраивается и документирован); значения, вычисляемые из окружения, не секреты. Контроли из раздела 3.2 должны быть корректно отброшены **общим правилом**, не по пути.

**Классы** (`class`): `password`, `api-key`, `configuration-token` (токен/Authorization в конфиге), `secret-fallback`, `recoverable-token`, а также `private-key`, `aws-access-key`, `github-token`, `telegram-token`, `jwt`, `db-credentials`, `generic-secret` (эвристика).
**Маскирование:** значение не сохраняется; хранится `fingerprint` (первые 8 hex SHA-256 от значения + длина) и маска вида `ab…(len=24)`. Сниппет кода в находке хранится с замаскированным значением.

### 8.2 SCA (`analyzers/sca`)
Источники объявлений: `build.gradle.kts` (корень и подмодули из `settings.gradle.kts`: `include(...)`), `build.gradle` (Groovy — базовая поддержка), `gradle/libs.versions.toml` (version catalog: `[versions]`, `[libraries]`, `module=`/`group+name`, `version.ref`, алиасы `libs.xxx`), `gradle.properties`, `gradle.lockfile`.

**Разбор Kotlin DSL (через tree-sitter, а не одним regex):**
- конфигурации: `implementation`, `api`, `compileOnly`, `runtimeOnly`, `testImplementation`, `kapt`, `annotationProcessor`… и общий вызов `add("implementation", "g:a:v")` (в том числе многострочный и с висячей запятой); форма `group = "…", name = "…", version = "…"`; `platform("…")`/BOM; `libs.xxx` через каталог.
- версии: литерал; `$var`/`${var}` в строке; `val x = "…"` (в файле); `extra["x"]`/`ext`; `providers.gradleProperty("k").get()/.orNull` и `project.property("k")` → значение из `gradle.properties`; `gradle/libs.versions.toml`.
- **Разрешённая версия:** если есть `gradle.lockfile` — используй запись `group:artifact:version` оттуда (оно побеждает объявленную), иначе — вычисленную из объявления; версия без значения (управляется BOM Spring Boot и не найдена в lockfile) — пропускать с информационным примечанием. Храни: `declared_version`, `resolved_version`, источник версии, путь и строки объявления, строки определения переменной (`alternateLocations`).
- **Транзитивные:** по умолчанию SCA проверяет **явно объявленные** зависимости (это область оценки). Записи lockfile, которых нет в явных объявлениях, считаются транзитивными: проверяются только при `include_transitive=true`, помечаются `scope=transitive` и **не** попадают в официальную JSON-выгрузку по умолчанию.
- `path` находки = файл, где объявлена зависимость, строка = строка объявления зависимости.

**Сравнение версий (`versions.py`)**: формат справочника `numeric-dot-separated`; сравнение по числовым компонентам слева направо, `1.9 == 1.9.0`, `20230618` — один числовой компонент. Версии с квалификаторами (`-SNAPSHOT`, `-rc1`, `.RELEASE`), динамические (`1.+`, `[1,2)`), пустые — вне области: не создавай находок, добавляй информационное примечание «версия не поддерживается снимком». Диапазон `ranges`: `lower` (может быть `null`), `lowerInclusive`, `upper`, `upperInclusive`; версия уязвима, если входит хотя бы в один интервал. Валидируй загруженный справочник по `schema.json` и ошибайся громко.

**Справочник:** по умолчанию — копия `fixtures/organizer-training/vulnerability-database/vulnerabilities.json` (`backend/vulndb/`), можно подключить другой JSON той же схемы (параметр ноды/настройка workspace). Индексируй по `group:artifact`. Для каждой находки: `advisoryId` (предпочитай CVE из `aliases` если есть, иначе GHSA `id`; одна запись справочника = одна находка; в отчёте один идентификатор), `fixedVersions` → рекомендация «обновить до ≥ X» (выбирай ближайшую исправленную версию ветки, которая больше текущей), `cvss` (разбери вектор CVSS v3.x и **посчитай базовую оценку** своим калькулятором `cvss.py`; сверь с `severity` справочника), `sources`.

**Контроль:** `commons-lang3:3.20.0` выше границы — находки быть не должно; покажи это тестом.

### 8.3 SAST для Kotlin / Spring Boot (`analyzers/sast`)
Парсинг: tree-sitter-kotlin → собственный лёгкий IR (классы, функции, параметры с аннотациями, вызовы, строковые шаблоны, присваивания, лямбды). Межпроцедурный анализ — через «граф вызовов» по конструкторным зависимостям (поле `private val reader: RepairTicketReader` → вызовы `reader.read(...)`). Spring-аннотации: `@RestController`, `@Controller`, `@RequestMapping/@GetMapping/@PostMapping/…`, `@RequestParam`, `@PathVariable`, `@RequestBody`, `@RequestHeader`, `@PreAuthorize`, `@Secured`, `@CrossOrigin`, `@Configuration`, `@Bean`, `@Repository`, `@Service`, `@Query`.

Каждая находка: `class`, `path`, `line`, `endLine` (≤15 строк), сниппет (маскированный), `title`, `description` (что/где/последствия), `severity`, `confidence`, `cwe`, `remediation`, `rule_id`.

**Правила (минимум; все обязательны, каждое с позитивными и негативными тестами):**

1. **`sql-injection`** — taint: источники (параметры обработчиков с `@RequestParam/@PathVariable/@RequestBody/@RequestHeader`, `HttpServletRequest.getParameter/getHeader`, параметры публичных методов контроллеров, значения, прошедшие через присваивания, `val`, строковые шаблоны `"…$x…"`/`"…${expr}…"`, конкатенацию, `String.format`, `StringBuilder`) → стоки (`JdbcTemplate.query*/queryForList/queryForObject/update/execute/batchUpdate`, `Statement.execute*`, `EntityManager.createNativeQuery/createQuery`, `NamedParameterJdbcTemplate`, `@Query` со SpEL/конкатенацией, `connection.prepareStatement(строка с подстановкой)`). Безопасно: SQL — константа без подстановок; значения передаются как параметры (`?`, `:name`, `MapSqlParameterSource`, `PreparedStatement.setX`); подстановка только констант/enum. Должно срабатывать на уязвимом методе и **не** срабатывать на соседнем параметризованном (контроль).
2. **`tls-verification`** — отключение проверки: `HostnameVerifier { _, _ -> true }` и любой верификатор, всегда возвращающий `true`, `NoopHostnameVerifier`, `ALLOW_ALL_HOSTNAME_VERIFIER`, `TrustManager` с пустым `checkServerTrusted`/`checkClientTrusted`, `TrustAllStrategy`, `SSLContext` с доверием ко всему, `setDefaultHostnameVerifier`, `.hostnameVerifier { _, _ -> true }` (OkHttp), `X509TrustManager` не бросающий исключений, `-Dtrust_all`. Штатный клиент (контроль) не срабатывает.
3. **`credentialed-cors`** — `allowedOrigins("*")`/`allowedOriginPatterns("*")`/`addAllowedOrigin("*")`/`@CrossOrigin(origins=["*"])`/отражение заголовка `Origin` в `Access-Control-Allow-Origin` **вместе с** `allowCredentials(true)`/`allowCredentials = true`/`setAllowCredentials(true)`. Диапазон строк охватывает обе настройки.
4. **`route-authorization`** — разбор цепочки `authorizeHttpRequests { requestMatchers(...).permitAll()/hasRole()/authenticated()/denyAll() }` (а также старый `antMatchers`/`mvcMatchers`, `anyRequest().permitAll()`, `csrf.disable()` в сочетании с cookie-сессией — отдельное предупреждение). Логика: определить для каждого `permitAll` эффективную чувствительность маршрута: (а) по семантике пути (`export`, `admin`, `internal`, `customer`, `ticket`, `order`, `user`, `pickup`, `actuator`, `report`…) против заведомо публичных (`catalog`, `health`, `login`, `static`, `public`, `docs`), (б) по **содержимому обработчика**, найденного по маршруту среди контроллеров (возвращает ли персональные данные/состояние заказов, есть ли у него `@PreAuthorize`), (в) по **теневому правилу**: более общий защищённый шаблон (`/api/pickup/**` → `hasRole`) перекрывается более ранним `permitAll` на частный маршрут. Публичный каталог услуг без персональных данных — **не** находка (контроль). Строка находки — строка `permitAll`-правила. Дополнительно: контроллеры с изменяющими методами без `@PreAuthorize`/правил в цепочке — предупреждение меньшей уверенности.
5. **`object-authorization`** — IDOR/BOLA: обработчик (или сервис/репозиторий, достижимый из него по графу вызовов) читает/изменяет объект по идентификатору из запроса (`@PathVariable id`, `@RequestParam`), при этом (а) в цепочке до доступа к данным нет проверки владельца: нет использования `Authentication`/`Principal`/`@AuthenticationPrincipal`/`SecurityContextHolder`, нет сравнения `owner/customerId == currentUser`, (б) SQL/запрос выбирает **только** по идентификатору объекта без условия по владельцу, (в) нет `@PreAuthorize("… #id …")`/`@PostAuthorize`. Рассуждай межфайлово: контроллер → сервис → репозиторий. Основное место находки — оператор доступа к данным по ID без ограничения владельца (в учебном эталоне это строки репозитория, а вызов контроллера — в `alternateLocations`; сверься с эталоном для формата, но реализуй общий алгоритм). Находка выпускается **один раз** на проблему.
6. **`hardcoded-credentials`** (в SAST дополняет SECRET): в `SecurityFilterChain`/`UserDetailsService`/`InMemoryUserDetailsManager` пароли и роли литералами (`.password("{noop}admin")`, `User.withUsername(...).password("…")`).
7. **`unsafe-deserialization`**: `ObjectInputStream(...).readObject()` на данных из запроса/файла, `enableDefaultTyping`/`activateDefaultTyping`, `Yaml().load` (SnakeYAML без SafeConstructor), `XMLDecoder`, `@JsonTypeInfo(use = Id.CLASS)` на недоверенном вводе.
8. **`path-traversal`**: пользовательский ввод попадает в `File(...)`, `Paths.get(...)`, `Path.resolve`, `FileInputStream`, `ResourceUtils`, `MultipartFile.transferTo` без нормализации и проверки `startsWith(base)`/`toRealPath`.
9. **`weak-crypto`**: `MessageDigest.getInstance("MD5"|"SHA-1")` для паролей/подписей, `Cipher.getInstance("DES"|"RC4"|"AES/ECB/…")`, статический IV/ключ, `java.util.Random` для токенов, `NoOpPasswordEncoder`, `{noop}`.
10. **`missing-input-validation`**: `@RequestBody` без `@Valid`/`@Validated` для типов с полями, попадающими в сохранение/ответ; числовые параметры, прямо используемые как размеры/индексы; небезопасные `@RequestMapping` без ограничения метода (изменяющие операции на GET).
11. **`insecure-endpoint`**: изменяющая операция по GET, `actuator` без защиты (`management.endpoints.web.exposure.include=*` в конфиге), `management.endpoint.*.show-details=always`, отладочные настройки (`spring.h2.console.enabled=true`, `debug=true`, `server.error.include-stacktrace=always`), отключённый HTTPS-redirect при чувствительных данных.

**Баланс правил:** первые пять правил — обязательный минимум точности (оценка идёт по ним); остальные добавляются при условии, что на `training-project/` не появляется ложных срабатываний (проверь прогоном; правило со сломанной точностью — доработай или понизь confidence и исключи из официальной выгрузки по умолчанию).

---

## 9. Классификация критичности

Единая шкала `LOW < MEDIUM < HIGH < CRITICAL`. Правила определяются в `analyzers/common/severity.py`, документируются в `docs/ANALYZERS.md`:
- **SCA:** основа — посчитанный CVSS v3.x base score (≥9.0 CRITICAL, 7.0–8.9 HIGH, 4.0–6.9 MEDIUM, <4.0 LOW; если вектор отсутствует — `severity` записи справочника); модификаторы только понижают уверенность, но не меняют балл молча; в находке хранятся и балл, и вектор.
- **SECRET:** матрица класс × контекст: приватные ключи, облачные ключи, пароли БД/служебных учёток в коде — HIGH/CRITICAL; API-ключи/токены сервисов — HIGH/MEDIUM; токены в конфигурации — MEDIUM/HIGH; fallback-секреты — MEDIUM/HIGH; эвристические (`generic-secret`) — LOW/MEDIUM; повышение при `prod`-контексте (имя файла/профиля `prod`), понижение для test-путей.
- **SAST:** матрица правило × достижимость (обработчик доступен без аутентификации — повышение; внутри защищённой области — базовый уровень): `sql-injection` CRITICAL (неаутентифицированный)/HIGH; `route-authorization`, `object-authorization` HIGH; `credentialed-cors` HIGH/MEDIUM; `tls-verification` HIGH/MEDIUM; `unsafe-deserialization` CRITICAL/HIGH; `path-traversal` HIGH; `weak-crypto` MEDIUM; `missing-input-validation`/`insecure-endpoint` MEDIUM/LOW. Матрицу реализуй таблицей данных + функцией-объяснением «почему такой уровень», текст объяснения хранится в находке и показывается в UI.
- **Политика CI:** по умолчанию `fail_on = CRITICAL`; настраивается (`HIGH`, `MEDIUM`, none).

---

## 10. Единая модель находки и отчёты

`Finding`: `id` (стабильный хэш от category+rule+path+нормализованный контекст — для сравнения запусков), `category`, `class`, `rule_id`, `title`, `description`, `remediation`, `severity`, `severity_reason`, `confidence`, `path`, `line`, `end_line`, `snippet` (маскированный), `cwe`, `alternate_locations[]`, SCA: `group/artifact/version/declared_version/advisory_id/aliases[]/cvss{score,vector}/fixed_versions[]/scope/direct`, SECRET: `fingerprint`, `masked_value`; diff-aware (раздел 12А.1, заполняются только при наличии diff-контекста): `diff_status` (`new|existing`), `diff_hunk`, `introduced_in_commit`, `author`; `autofix` (`llm|deterministic|none`, из метаданных правила).

Поля diff-aware и autofix **не** попадают в официальный `submission.json`, если `docs/submission-format.md` явно не разрешает дополнительные поля. Официальный формат не должен меняться из-за фич команды.

Сохрани все находки запуска в БД (`findings`), связанные с `run_id` и `node_id`.

**Экспорт:**
- `GET /api/runs/{id}/export/submission.json` — **официальный формат** (раздел 3.1): маппинг `Finding → запись`, фильтрация по порогу confidence, только SCA области «явные зависимости» (если не включён `include_transitive`), валидация перед выдачей, `description` и `remediation` без секретов.
- `GET /api/runs/{id}/export/report.md` и `report.html` — читаемый отчёт (сводка, таблица по категориям, детали, AI-раздел, ссылки на файл:строку; секреты скрыты).
- Нода `output.report_export` сохраняет те же артефакты в запуск.

---

## 11. Интеграция LLM

### 11.1 Провайдеры
Абстракция `LLMProvider.chat(messages, response_schema=None, temperature, max_tokens, timeout)`: `openai_compat` (`base_url`, `api_key`, `model`, дополнительные заголовки; поддержка `response_format` JSON, если сервер умеет, иначе — инструкция + разбор) и `ollama` (`/api/chat`, `format: json`). Настройки на уровне workspace + переопределение в ноде; API-ключи — в зашифрованном хранилище; кнопка «проверить соединение»; список моделей (если провайдер отдаёт). По умолчанию: ничего не включено, пока пользователь не настроит провайдер (UI подсказывает: бесплатные варианты — Ollama локально, OpenRouter free-модели, Gemini через OpenAI-compatible endpoint). Таймауты, ретраи с backoff на 429/5xx, лимит контекста (разбиение находок на пачки по токенам/размеру), ошибка провайдера → явная ошибка ноды (не «молчаливая» подмена).

### 11.2 Что делает AI (и только это)
Вход — **готовые находки анализаторов** (id, категория, класс, файл, строки, сниппет **с маскированными секретами**, severity, SCA-метаданные из справочника). Выход (строго по JSON-схеме, `ai/schemas.py`):
```json
{
  "summary": "…общий вывод простым языком…",
  "priority_order": ["finding_id", "…"],
  "findings": [{
    "finding_id": "…", "explanation": "…простыми словами…", "impact": "…возможные последствия…",
    "remediation_steps": ["…"], "safe_version": "… (для SCA, из справочника)",
    "fix": {"path":"…","start_line":N,"end_line":M,"before":"…","after":"…"}   // необязательно
  }],
  "global_recommendations": ["…"]
}
```
Генерация исправленного кода (`fix`) отображается в UI как **diff** с кнопкой копирования. Применение патча с проверкой и созданием PR/MR — это отдельная фича **AI AutoFix** (раздел 12А.3), со своим валидатором.

### 11.3 Проверка достоверности ответа (обязательно, показывается на демо)
`ai/validator.py` после каждого ответа:
1. Валидация по JSON-схеме; невалидный JSON → одна попытка автоматического исправления (повторный запрос с описанием ошибки), затем ошибка.
2. Каждый `finding_id` существует во входном наборе; нет дубликатов; неизвестные id отбрасываются и учитываются в метрике.
3. Ссылки на файл/строки (`fix.path`, строки в тексте, если извлекаются) совпадают с реальной находкой/файлом; `fix.before` **буквально** совпадает с текстом файла в указанных строках (с учётом нормализации пробелов), иначе fix отбрасывается.
4. **Выдуманные CVE:** все идентификаторы вида `CVE-\d{4}-\d{4,}`/`GHSA-…` в ответе должны входить в множество (справочник ∩ находки данного запуска); посторонние — удаляются из текста/помечаются как непроверенные, ответ получает флаг `hallucinated_ids`.
5. `safe_version` для SCA проверяется по `fixedVersions` справочника.
6. Результат валидации (по каждому пункту: принято/отброшено/исправлено) сохраняется вместе с отчётом, показывается в UI («доверие к ответу»), метрики (`valid_items/total_items`, `dropped`, `hallucinated_ids`) попадают на панель и в `PRESENTATION_NOTES.md`.
7. Если LLM недоступна или после ретраев ответ невалиден: нода `ai.report` завершается ошибкой, **либо** (опция `fallback_to_deterministic`, по умолчанию включена) формирует детерминированный отчёт из данных анализаторов (шаблонные объяснения по правилам, без выдумок) с явной пометкой `ai_generated: false` в UI и в уведомлении. Никакой тихой подмены.

Промпты — в `ai/prompts.py` (RU/EN), с запретом выдумывать идентификаторы/файлы/строки, с примерами формата; секреты в промпты не попадают (только маски).

---

## 12. Задачи со звёздочкой (все три — обязательны)

### 12.1 Публичная библиотека шаблонов
- Публикация workflow из workspace в общий каталог: название, описание назначения, категория (`Secrets`, `SAST`, `SCA`, `Full Security Audit`, `CI/CD`, `Notifications`, `Custom`), теги, версия, автор. При публикации из графа **вычищаются** секреты/credential-ссылки/конкретные URL репозиториев/chat_id → заменяются **параметрами шаблона** (объявляются: имя, тип, описание, значение по умолчанию).
- Каталог: карточки, **поиск** (название/описание/теги), **фильтры** (категория, рейтинг, автор, «избранное», «мои»), сортировка (новые, популярные по числу использований, по рейтингу).
- Просмотр шаблона: описание, автор, число использований, средний рейтинг, **структура сценария** (read-only React Flow-превью + список нод и параметров), отзывы.
- **Копирование в рабочее пространство** («Использовать»): мастер подстановки параметров (репозиторий/расписание/каналы/credentials из хранилища), создаёт независимую копию, инкремент `usage_count`; копия полностью редактируется в редакторе; сохраняется ссылка на источник (`forked_from`).
- Рейтинг (1–5, одна оценка на пользователя, можно менять), **отзывы** (текст, редактирование/удаление своего), **избранное** (добавить/убрать, список избранного).
- Модерация: владелец может снять шаблон с публикации/обновить версию; admin workspace-платформы может скрыть шаблон.
- Предзаполненные встроенные шаблоны (seed, с автором «System»): «Проверка секретов», «SCA зависимостей», «SAST Kotlin/Spring», «Полный аудит безопасности + AI + Telegram», «CI gate: упасть на Critical», «Ежедневная проверка + e-mail», «Проверка по webhook + Webhook-уведомление».

### 12.2 Интеграция в CI/CD (GitHub Actions и GitLab CI)
- **API запуска:** токены API (на workspace/workflow; хранятся в виде хэша, показываются один раз, отзываются, с ограничением по workflow), `POST /api/v1/ci/runs` (workflow_id, метаданные: provider, repo, ref, commit sha, pr/mr id, источник кода — загруженный архив `multipart` или `git_url` из allowlist), `GET /api/v1/ci/runs/{id}` (статус, `gate`, сводка по severity, ссылки), `GET /api/v1/ci/runs/{id}/report` (JSON/Markdown/submission.json). Ожидание результата: long-poll/опрос.
- **CLI `cli/aisw_ci.py`** (только stdlib, один файл): пакует рабочую копию (учитывая исключения), загружает, запускает workflow, опрашивает, печатает сводку, пишет `report.md/submission.json` артефактами, возвращает **exit code 1 при `gate=fail` (по умолчанию — наличие Critical)**, 0 при pass, 2 при ошибке платформы. Загрузка кода из CI снимает проблему доступа платформы к приватным репозиториям.
- **Генерация YAML** (`ci/yaml_generator.py`, эндпоинт и экран «Интеграция»):
  - GitHub Actions: `on: push` + `pull_request` (ветки настраиваются), checkout, запуск CLI с `secrets.AISW_TOKEN`, `AISW_URL`, job summary (отчёт в `$GITHUB_STEP_SUMMARY`), загрузка артефактов, комментарий к PR (опционально, через `GITHUB_TOKEN`), падение шага при Critical; инструкция по **branch protection → required status check**, чтобы проблемный код не попал в основную ветку.
  - GitLab CI: job в stage `test`/`security`, `rules` для `push` и `merge_request_event`, переменные `AISW_URL`/`AISW_TOKEN`, артефакты, `allow_failure: false`, комментарий в MR (опционально) и инструкция «Pipelines must succeed».
  Сгенерированный YAML проверяй тестом (парсится валидным YAML; содержит нужные триггеры, шаги и gate; прогон шагов эмулируется локально — CLI реально вызывает API тестового сервера).
- **Webhook-режим:** `POST /api/v1/webhooks/github` и `/gitlab` с проверкой подписи (`X-Hub-Signature-256` HMAC SHA-256, `X-Gitlab-Token`), обработка `push` и `pull_request`/`merge_request` (opened/synchronize/reopened), сопоставление с workflow по подписке (триггер `trigger.webhook`), запуск проверки (код получаем клоном по `git_url` из allowlist с токеном доступа из credentials, либо по данным события), **возврат статуса в провайдер**: GitHub Commit Statuses/Checks API, GitLab Commit Status API (`pending → success/failed` + ссылка на запуск), защита от повторной доставки (идемпотентность по delivery id), лимиты размера тела.
- Проверка в тестах: поднимай локальные mock-серверы GitHub/GitLab API (настоящие HTTP-серверы в тестах), проверяй реальные запросы с правильными заголовками/телами и корректные подписи; подпись неверная → 401/403.
- Результат для CI: `gate` вычисляется нодой `output.ci_gate`; в ответе API — severity-сводка и ссылки на экспорт.
- **Diff-контекст для CI** (нужен для раздела 12А.1): сгенерированный GitHub Actions YAML использует `actions/checkout` с `fetch-depth: 0`, GitLab CI — `GIT_DEPTH: 0` (или fetch целевой ветки). CLI вычисляет diff локально и загружает его вместе с архивом. Вебхук передаёт `base_sha`/`head_sha` из события. Подробности в 12А.1.

### 12.3 AI-генерация и диалоговая правка workflow
- Поле ввода описания на естественном языке (RU/EN). Обязательные эталонные примеры (оба проходят как тест-кейсы):
  - из PDF: *«Каждый день в 14:00 проверяй код из репозитория на наличие секретов и отправляй отчет на почту»* → `trigger.schedule(0 14 * * *) → source.repo → scanner.secrets → output.report_export → notify.smtp`;
  - из TZ.md: *«Каждый день в 14:00 проверяй мой Kotlin-проект на секреты и уязвимые зависимости. Если найдёшь Critical или High — отправь уведомление в Telegram.»* → расписание + secrets + sca + merge + `if_else(severity.max ≥ HIGH)` + `notify.telegram` на ветке `true`.
- `ai/workflow_gen.py`: в промпт LLM передаётся **каталог нод из реестра** (type, назначение, порты, схема конфигурации с примерами) и правила графа; LLM возвращает граф (нодные типы, связи, конфигурация, расписание/cron, условия IF, каналы уведомлений) строго по JSON-схеме графа.
- **Валидация сгенерированного графа** тем же `engine/validator.py` (типы нод существуют, обязательные параметры заполнены, порты совместимы, нет циклов, есть триггер, ветки IF подключены, секретные поля — только ссылки на credentials/параметры, не значения). При ошибках — автоматический цикл исправления (до 3 попыток: ошибки валидатора возвращаются в LLM); если не удалось — показываем ошибки пользователю, ничего не применяем.
- **Мгновенная отрисовка:** валидный граф открывается в редакторе (авто-раскладка слоёв), пользователь может запустить его сразу или править вручную. Параметры, которые нельзя угадать (токен бота, chat_id, путь к репозиторию), подсвечиваются как «требуют заполнения».
- **Диалоговый режим:** панель чата рядом с редактором; пользователь пишет «добавь отправку на email», «замени Telegram на webhook», «запускай только по будням»; LLM возвращает **список операций над графом** (`add_node`, `update_node`, `remove_node`, `connect`, `disconnect`, `set_schedule`), бэкенд применяет их к копии графа, валидирует, фронтенд показывает превью-diff (что добавится/изменится/удалится) с кнопками «Применить»/«Отклонить»; применённые правки попадают в undo/redo; история диалога хранится с workflow.
- Тесты: с реальным HTTP-обменом против локального OpenAI-compatible тестового сервера (контрактные тесты формата запроса/ответа, ретраев, ошибок) и — если в окружении доступна реальная LLM (Ollama или бесплатный API) — живая проверка на примере выше; результат живой проверки отражается в `docs/REPORT.md` (если LLM недоступна — так и написать).

---

## 12А. Фичи команды сверх ТЗ (обязательны)

Делаются в фазе 6А, после того как все пункты ТЗ прошли гейты. Требования те же: без заглушек, с тестами, с проверкой на запущенном стеке. **Фичи не должны ломать обязательные пункты:** официальный `submission.json`, eval 15/15 и поведение существующих нод не меняются, если новые ноды не подключены в граф.

### 12А.1 Diff-aware scan: сканирование изменений и блокировка PR

**Зачем (для жюри):** небольшая команда не может сразу починить сотни старых находок. Если сканер блокирует всё, его отключают. Принцип: «за старый код не отвечаем, но новое не пропустим». Блокируют только находки, появившиеся в этом diff.

**1. Контекст diff (`analyzers/diff/git.py`):**
- Вебхук: GitHub `pull_request.base.sha/head.sha`, push `before/after` (если `before` = `000…0`, т.е. новая ветка, base = merge-base с веткой по умолчанию); GitLab MR — `diff_refs`/target branch + `last_commit`, push — `before/after`. Если base sha нет, merge-base с целевой веткой вычисляется локально.
- Ручной запуск: base-ветка из параметра ноды (по умолчанию `main`), head = текущий ref.
- CLI в CI: CLI сам выполняет `git diff` (см. п. 2) и `git show <base>:<file>` для файлов сборки (`build.gradle(.kts)`, `settings.gradle.kts`, `gradle.properties`, `gradle.lockfile`, `gradle/libs.versions.toml`) и `git blame --porcelain` по изменённым диапазонам. Загружает это как `diff_context` вместе с архивом. Сгенерированный YAML ставит `fetch-depth: 0` / `GIT_DEPTH: 0`.
- `git_url` и `path` с `.git`: команды git выполняются на стороне платформы, только чтение, через `repo_guard` (раздел 13).
- Загрузка без git-контекста: параметр `on_missing_diff` = `fail` (по умолчанию, понятная ошибка ноды) | `treat_all_as_new`.

**2. Карта изменений (`hunks.py`):** `git diff --unified=0 --find-renames <merge_base>...<head> -- <globs>`. Обязательно **три точки**: diff от merge-base, иначе в diff попадут чужие коммиты из base. Globs по умолчанию: `*.kt *.kts *.gradle *.properties *.yml *.yaml *.toml gradle.lockfile`, настраиваются. Результат: `{path: {new_lines: set[int], hunks: [{old_start, old_count, new_start, new_count, header}], renamed_from}}`. Переименования: строки, перенесённые без изменений, не считаются новыми. `ignore_whitespace` (по умолчанию `true`) → `-w --ignore-blank-lines`: переформатирование не делает строки новыми. Пути diff (от корня репозитория) приводятся к путям находок (от корня проверяемого проекта, например с отрезанием префикса `training-project/`).

**3. Анализаторы** работают **по полным файлам**, иначе теряется контекст (константа на строке 10, использование на 50). Классифицируется уже готовый набор находок.

**4. Классификация (`classifier.py`, `sca_diff.py`):**
- SECRET/SAST: `new`, если хотя бы одна строка диапазона `[line, end_line]` входит в `new_lines` файла. Для межфайловых находок (`object-authorization` и др.) `new` ставится, если diff задевает основное место **или** любое из `alternate_locations`. Иначе `existing`. Неизменённый файл → `existing`.
- SCA — **по версиям, а не по строкам**: тот же SCA-парсер запускается на base-версиях файлов сборки и на head. Ключ: `(group, artifact, advisoryId)`. `new` — если такой уязвимости не было в base: зависимость добавлена или версия попала в уязвимый диапазон, в том числе через изменение только `gradle.properties`/`val`/каталога/lockfile. `existing` — если уязвимость была в base, даже если версия изменилась (`version_changed: true`). Уязвимости, которые были в base и исчезли, попадают в информационный список `fixed_in_diff`.
- Атрибуция новых находок: `introduced_in_commit`, `author` из `git blame --porcelain -L l,l <head> -- <path>`. `author` — персональные данные: видны только участникам workspace, не передаются в LLM и не попадают в публичные шаблоны.

**5. Вердикт:** `FAIL`, если есть хотя бы одна `new`-находка с severity ≥ порога (по умолчанию `CRITICAL`, тот же порог, что у `ci_gate`). Иначе `PASS`. Режим `report_only`: вердикт всегда `PASS`, но причина «было бы FAIL» записывается.

**Нода `scanner.diff`:** входы `repo` (несёт git/diff-контекст) и `findings` (от сканеров/`merge`). Выходы: `new_findings` (findings), `existing_findings` (findings), `verdict` (json: `verdict`, `threshold`, `new_counts_by_severity`, `existing_count`, `fixed_in_diff`, `base_sha`, `head_sha`, `merge_base`).

**Возврат в пайплайн:** `GET /api/v1/ci/runs/{id}/verdict` → HTTP **200** (PASS) / **422** (FAIL) + JSON (вердикт, новые находки с маскированными сниппетами, число существующих, ссылки на отчёт). Поле `verdict` также есть в `GET /api/v1/ci/runs/{id}`. CLI: exit code **0** PASS / **1** FAIL / **2** ошибка платформы. Commit status: `failure` с описанием «N new critical». **Комментарий в PR/MR:** в вебхук-режиме его пишет платформа (GitHub `POST /repos/{o}/{r}/issues/{n}/comments`, GitLab `POST /projects/:id/merge_requests/:iid/notes`). Один комментарий на PR **обновляется** при каждом push (маркер `<!-- aisw-report -->`), без спама. Содержимое: таблица новых находок (файл:строка, severity, коммит), вердикт, «N существующих находок не блокируют», ссылка на запуск. В CLI-режиме тот же Markdown пишется в `$GITHUB_STEP_SUMMARY` и, при наличии `GITHUB_TOKEN`/`GITLAB_TOKEN`, публикуется в PR/MR.

Пример находки в API/UI (в `submission.json` эти поля не попадают, раздел 10):
```json
{"id":"f_8a3c","category":"SECRET","class":"aws-access-key","rule_id":"SEC-AWS-KEY","severity":"CRITICAL",
 "path":"src/main/kotlin/Config.kt","line":42,"snippet":"val key = \"AK…(len=20)\"",
 "diff_status":"new","diff_hunk":"@@ -40,3 +42,1 @@","introduced_in_commit":"a1b2c3d","author":"dev@example.com"}
```

**Демо:** скрипт `scripts/demo_diff.sh` создаёт во **временной директории** локальный git-репозиторий из копии `training-project` (сами фикстуры не меняются) (base-коммит с 15 эталонными находками) и ветку, в которой в Kotlin-файл добавлен синтетический AWS-ключ. Ключ **генерируется скриптом** и не коммитится в наш репозиторий; ключи с `EXAMPLE` не подходят, их гасит подавление плейсхолдеров. Сценарий: вебхук PR на mock GitHub → FAIL, комментарий «🔴 Новый critical-секрет в …:N, коммит …, PR заблокирован» → ключ удалён, новый push → PASS, комментарий обновлён → 15 старых находок помечены `existing`.

**Тесты:** парсер hunks (несколько hunks, новые/удалённые/переименованные/бинарные файлы, whitespace-only); три точки vs две (коммиты в base после точки ветвления не попадают в diff); классификация (секрет в изменённой строке → new; тот же секрет в нетронутом файле → existing; многострочный диапазон; межфайловый IDOR); SCA-diff (повышение версии до уязвимой только через `gradle.properties` → new; без изменений → existing; обновление до исправленной → `fixed_in_diff`); пороги и `report_only`; 200/422; exit codes CLI; upsert комментария на mock GitHub/GitLab; инъекции аргументов git (ветка `--upload-pack=…`, невалидный sha) отклоняются.

### 12А.2 Security Score, тренд и Priority Fix List

**Формула (`scoring/formula.py`, должна быть объяснимой — жюри спросит):**
```text
penalty = Σ weight(severity) × novelty(f)     # по находкам с confidence ≥ порога официального экспорта
weight:  CRITICAL=10, HIGH=5, MEDIUM=2, LOW=1  (информационные примечания = 0)
novelty: new=1.5, existing=1.0                 # без diff-контекста все = 1.0 (связка с 12А.1)
S       = S0 × max(1, sqrt(LOC / 1000))        # нормировка на размер; LOC = непустые строки кода/конфигов в области сканирования
score   = round(100 × exp(−penalty / S))       # 0..100, плавно, никогда не уходит в 0
```
`S0` по умолчанию 50. Откалибруй один раз на учебном наборе и мутантах: проект без находок даёт 100, учебный проект попадает в «красную, но не нулевую» зону. Зафиксируй значение в настройках и опиши калибровку в `docs/TEAM_FEATURES.md`. Веса, novelty и `S0` хранятся в настройках workspace. С каждым запуском сохраняется `score_formula_version`; смена формулы отмечается маркером на графике. Нормировка на LOC нужна, чтобы маленький проект с одной находкой не получал 0, а большой с десятью — 90.

**Детерминированность:** score зависит только от набора находок и LOC, без LLM, не зависит от порядка. Тест: тот же коммит дважды → тот же score.

**История и тренд (`trend.py`):** в запуске хранятся `score`, `score_delta` (относительно предыдущего успешного запуска того же проекта с той же `scanner_set_signature`), `findings_by_severity`, `verdict`, `loc`, `commit`. Тренд за 7/30 дней — линейная регрессия (МНК) по точкам `(время, score)` → «📈 +2.3/нед»; при < 3 точек — «недостаточно данных». Если набор сканеров изменился, график показывает разрыв/маркер. **Оговорка в UI и в презентации:** score — метрика внутреннего тренда проекта, а не рейтинг между проектами.

**Priority Fix List (`priority.py`):** `priority = weight × novelty / fix_effort`, где `fix_effort ∈ 1..5` (1 — заменить строку, 5 — переписать модуль). Источник `fix_effort`: LLM (валидируется: целое 1–5, `finding_id` существует) или детерминированная таблица по `class`, если LLM нет или ответ отброшен (например, SCA-bump = 1, секреты = 1, `recoverable-token` = 2, `sql-injection`/`tls-verification`/`credentialed-cors`/`route-authorization` = 2, `object-authorization` = 3). В UI показан источник (`ai`/`default`). **Ожидаемый +score** считается детерминированно: пересчёт score без этой находки, а для топ-N — накопительно. Колонки: #, находка (файл:строка или координаты), severity, «почему сейчас» (новая/старая + оценка трудозатрат словами), ожидаемый +score. Топ-3 на дашборде, полный список в деталях запуска.

**AI-план на спринт:** вход (маскированный) `{score, delta, trend, top_findings:[{finding_id, class, severity, novelty, fix_effort, expected_gain}]}` → выход строго по схеме `{summary, plan:[{finding_id, action, reason}], defer:[{finding_id, reason}], projected_score}`. Валидатор: id существуют; `projected_score` **пересчитывается детерминированно** по позициям `plan`. Если число LLM расходится больше чем на 1, оно заменяется расчётным, ответ получает флаг `corrected_numbers`. Посторонние CVE отбрасываются тем же валидатором из 11.3. Без LLM — детерминированный план из Priority Fix List с пометкой `ai_generated: false`.

**Интеграция:** score вычисляется сервисом в конце **каждого** запуска с находками, даже без ноды, чтобы тренд был непрерывным. Нода `analysis.security_score` отдаёт его в граф (для `if_else` по `score.value`/`score.delta` и шаблонов уведомлений).

**Тесты:** формула на ручных примерах, детерминированность и независимость от порядка, нормировка LOC, novelty, регрессия тренда, ожидаемый +score, валидатор AI-плана (подсаженное неверное `projected_score` → исправлено, неизвестный id → отброшен), fallback.

### 12А.3 AI AutoFix: патч + самопроверка сканером + Pull Request

**Применимость:** у каждого правила в метаданных есть `autofix: llm | deterministic | none`. `deterministic` — SCA: обновление до ближайшей `fixedVersion` ветки в **месте определения версии** (литерал, `val`, `gradle.properties`, version catalog, `extra`) плюс правка записи lockfile; в PR пометка «перегенерируйте локи `./gradlew dependencies --write-locks`». `llm` — секреты (вынос в env без значения по умолчанию), SQL (параметризация), TLS, CORS, route/object-authorization и др. `none` — архитектурные проблемы, только рекомендации. Покрытие («AutoFix доступен для N из M правил») **считается из метаданных**, а не пишется вручную.

**1. Контекст для LLM (`autofix/context.py`):** правило, класс, описание, severity; сниппет ±10 строк; объемлющая функция/класс через tree-sitter (не весь файл, с лимитом токенов); для межфайловых находок — связанные функции по графу вызовов. **Все секреты маскированы.** Ответ строго JSON: `{file, start_line, end_line, old_snippet, new_snippet, explanation, requires_config:[{name, description}]}`.

**2. Валидация (`autofix/validator.py`; каждый шаг записывается и показывается в UI чеклистом):**
1. JSON-схема.
2. `file` — путь находки или связанный файл из контекста; строки в пределах файла.
3. `old_snippet` **буквально** (с нормализацией пробелов) совпадает с указанными строками **маскированного** представления файла (защита от галлюцинаций). При применении к реальному файлу маски в `old_snippet` сопоставляются с исходным текстом по позициям.
4. `new_snippet` не содержит артефактов маски, исходного значения секрета и новых литералов, на которые срабатывает детектор секретов.
5. Патч применяется к **копии** проекта во временной директории.
6. Синтаксис: tree-sitter-парсинг пропатченного файла не даёт новых `ERROR`-узлов по сравнению с исходным. Компиляция и Gradle **не запускаются**: проверяемый код никогда не исполняется (раздел 13).
7. **Самопроверка (ключевой момент для демо):** повторный запуск всех трёх анализаторов на пропатченной копии всего проекта (межфайловые правила). Исходная находка должна исчезнуть, новых находок появиться не должно.
8. Итог `validated` или `rejected(reason)`. Одна повторная попытка с ошибками валидатора в LLM, затем отказ. Только `validated` может стать PR.

**3. Создание PR/MR (`autofix/pr/*`, через REST, без `git push` с токеном в URL):**
- В продукте разрешено только для репозитория пользователя с `allow_write=true` в allowlist (раздел 13). Токен — credential `repo_write_token` из хранилища, в логи не попадает. Репозиторий организаторов и фикстуры **никогда** не получают `allow_write`: это запрещено кодом, а не только настройкой. Для них и для загруженных архивов вместо PR предлагаются **diff в UI и скачивание `.patch`**. Создание PR в разработке, тестах и демо проверяется **только на локальных mock-серверах GitHub/GitLab**.
- GitHub: sha base-ветки → `POST /repos/{o}/{r}/git/refs` (`refs/heads/autofix/<finding_id>`) → `PUT /repos/{o}/{r}/contents/{path}` (с sha blob) → `POST /repos/{o}/{r}/pulls`. GitLab: `POST /projects/:id/repository/branches` → `POST /projects/:id/repository/commits` (actions `update`) → `POST /projects/:id/merge_requests`.
- Идемпотентность: если ветка или PR уже есть — обновление, а не дубль. **Никакого auto-merge**, никаких коммитов в base/защищённую ветку.
- Описание PR (по шаблону): находка (маскированная), объяснение, отчёт валидации («самопроверка пройдена: находка устранена, 0 новых»), `requires_config` (какие env-переменные задать), ссылка на запуск, label `security-autofix`. Создание PR пишется в журнал аудита.
- PR запускает обычный CI/вебхук-поток → diff-aware-проверка ветки `autofix/…` → ожидается PASS и 0 новых находок.

**4. Нода `ai.autofix`:** вход `findings`. Параметры: `auto_create_pr` (по умолчанию `false`), `max_findings` (по умолчанию 3), `min_severity`, `target_branch` (по умолчанию base-ветка), шаблон PR. Выход json: `[{finding_id, status, reason, patch, pr_url}]`. Из UI AutoFix запускается кнопкой на находке.

**5. Восстановление исходников:** рабочие копии удаляются после запуска, поэтому AutoFix из UI заново получает код **на точном коммите запуска** (`git_url` через `repo_guard`) или из загруженного архива. Архив хранится артефактом запуска в зашифрованном виде с TTL `APP_UPLOAD_RETENTION_HOURS` (по умолчанию 72) и затем удаляется.

**6. Хранение:** таблица `autofixes` (`run_id`, `finding_id`, провайдер/модель, patch, шаги валидации, статус, `pr_url`, автор действия).

**Тесты:** mock LLM-сервер возвращает: корректный фикс → `validated`; `old_snippet` нет в файле → reject; фикс не убирает находку → reject на самопроверке; фикс добавляет новую находку → reject; ломающий синтаксис → reject; `new_snippet` с секретом → reject. SCA-bump — для каждой формы объявления версии из 8.2. Создание PR на mock GitHub и GitLab: правильная последовательность запросов, заголовки, тела, идемпотентность. `allow_write=false` → 403. Маскированные значения никогда не попадают в тело PR.

**Демо:** находка «хардкод пароля» → AutoFix → чеклист валидации + diff «было/стало» (пароль вынесен в env) → «Создать PR» → PR на локальном mock GitHub → diff-aware прогон ветки `autofix/…` (на временной копии): 0 новых находок. Для репозитория организаторов показать «Скачать .patch».

---

## 13. Безопасность

- **Аутентификация:** регистрация/вход, пароли — argon2/bcrypt, JWT access (короткий) + refresh с ротацией и отзывом, ограничение попыток входа (rate limit), CORS строго по списку origin из конфигурации.
- **Авторизация:** все ресурсы привязаны к workspace; роли `admin` (всё, участники, настройки, credentials), `developer` (workflows, запуски, шаблоны, использование credentials без чтения значений), `viewer` (только просмотр). Проверка принадлежности объекта в **каждом** эндпоинте (никаких IDOR в самом нашем продукте); тесты на кросс-workspace доступ.
- **Шифрование секретов:** хранилище credentials (токены Telegram, SMTP-пароли, API-ключи LLM, токены доступа к репозиториям, секреты webhook) — AES-256-GCM (или Fernet) с мастер-ключом из переменной окружения (`APP_MASTER_KEY`, генерация при первом запуске в dev с предупреждением), шифрованные значения в БД, версионирование ключа. API **никогда** не возвращает значения секретов (только `••••` + последние 2–4 символа), в UI поля секретов маскируются, «показать» недоступно после сохранения.
- **Исключение секретов из логов и событий:** центральный `Masker`, регистрирующий известные значения секретов (из credentials, конфигурации запуска и обнаруженных сканерами) и паттерны; применяется к логам приложения, событиям `run_events`, ошибкам, ответам API, AI-промптам, сохранённым сниппетам, отчётам и уведомлениям. Тест: специально внедрённый секрет не встречается нигде (grep по логам/БД/ответам).
- **Защита от SSRF:** единый `core/ssrf.py` для исходящих запросов (notify.webhook, git clone, провайдеры LLM, CI-статусы): только `http/https`, резолв DNS и проверка итогового IP (блок loopback, private, link-local, metadata 169.254.169.254, IPv6-эквиваленты), защита от DNS-rebinding (повторная проверка по соединению), ограничение редиректов, таймауты, лимит размера ответа. Для локального Ollama и локальных тестов — явный список разрешённых хостов в настройках (по умолчанию `localhost:11434` для Ollama допускается только в настройках LLM).
- **Запрет сканирования посторонних репозиториев** (`core/repo_guard.py`): `source.repo` в режиме `git_url` разрешает только URL из allowlist workspace/платформы (по умолчанию содержит **только** `https://github.com/TBagirov/training`; админ может добавить собственные учебные репозитории, добавление фиксируется в аудите); режим `path` — только внутри `APP_SCAN_ROOTS`; режим `upload` — размер/количество файлов ограничены, безопасная распаковка (защита от zip-slip, симлинков, zip-бомб); git-клон: только `https`, без `file://`/`ext::`/`--upload-pack` инъекций (аргументы списком, `GIT_ALLOW_PROTOCOL=https`, `GIT_TERMINAL_PROMPT=0`, `core.hooksPath=/dev/null`, sha проверяются regex `^[0-9a-f]{7,40}$`, имена веток не могут начинаться с `-`). По умолчанию `--depth 1`; для diff-aware — fetch конкретных `base`/`head` sha с ограниченной глубиной и `--deepen` до нахождения merge-base (с лимитом). Таймаут, лимит размера, отдельная временная директория; после запуска рабочая копия удаляется.
- **Право записи в репозиторий** (для AI AutoFix, 12А.3): у записи allowlist есть отдельный флаг `allow_write` (по умолчанию `false`, ставит только admin, фиксируется в аудите). Репозиторий организаторов — только чтение: попытка выставить ему `allow_write` отклоняется (тест). Создание веток/PR разрешено только в репозитории с `allow_write=true`, токеном из хранилища credentials.
- **Изоляция проектов:** каждая рабочая копия в собственной временной директории с правами владельца процесса; анализаторы **никогда не исполняют** проверяемый код (никаких `gradlew`, `import`, `eval` над содержимым репозитория).
- **Прочее:** безопасные заголовки, валидация входа Pydantic, лимиты размера тела, защита от ReDoS в пользовательских regex-нодах, журнал аудита (вход, изменение credentials, публикация шаблона, добавление в allowlist, создание API-токенов), секреты только из окружения, `.env.example` без реальных значений.

---

## 14. История запусков, результаты, сравнение

- Для каждого запуска хранятся: время старта/окончания и длительность, workflow и **снимок графа**, проект/источник кода (ref/commit), инициатор (пользователь/расписание/CI), статусы и длительности нод, логи нод (маскированные), все находки, AI-отчёт (+ результаты валидации и метаданные модели: провайдер, модель, токены), ошибки, артефакты экспорта, статус уведомлений (доставлено/ошибка), **Security Score** (score, delta, разбивка по severity, LOC, `score_formula_version`, `scanner_set_signature`), **verdict** diff-aware (если был), созданные AutoFix/PR.
- Экран истории: фильтры (workflow, статус, период, инициатор), открытие деталей запуска (граф с итоговыми статусами, таблица находок с фильтрами/сортировкой, AI-отчёт с diff-фиксами, логи, артефакты).
- **Сравнение двух запусков:** по стабильным `Finding.id` — «новые», «устранённые», «неизменные», изменения severity; сводка по категориям; доступно из UI и API (`GET /api/runs/compare?base=&head=`); выводится также в нотификациях (опционально).

---

## 15. API (REST, JSON, OpenAPI на `/docs`)

Префикс `/api`. Минимальный контракт (детали уточни и зафиксируй в `docs/API.md`; все ответы с единым форматом ошибок `{"error":{"code","message","details"}}`):

- `POST /auth/register|login|refresh|logout`, `GET /auth/me`
- `GET/POST /workspaces`, `GET/PATCH /workspaces/{id}`, `POST /workspaces/{id}/members` (+ изменение роли/удаление), `GET /workspaces/{id}/audit`
- `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}` (источник кода: upload/git_url из allowlist)
- `GET /nodes` (каталог нод + JSON-схемы) 
- `GET/POST /workflows`, `GET/PUT/DELETE /workflows/{id}`, `POST /workflows/{id}/validate`, `POST /workflows/{id}/run`, `GET/PUT /workflows/{id}/schedule`
- `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/cancel`, `GET /runs/{id}/events` (SSE), `GET /runs/{id}/findings`, `GET /runs/{id}/ai-report`, `GET /runs/{id}/export/{submission.json|report.md|report.html}`, `GET /runs/compare`
- `GET/POST/DELETE /credentials` (значения только на запись)
- `GET/PUT /settings/ai`, `POST /settings/ai/test`, `GET/PUT /settings/allowlist`
- `POST /ai/workflows/generate`, `POST /ai/workflows/{id}/chat` (+ `GET` истории)
- `GET/POST /templates`, `GET /templates/{id}`, `POST /templates/{id}/use`, `POST /templates/{id}/rate`, `POST|DELETE /templates/{id}/favorite`, `GET/POST /templates/{id}/reviews`
- `GET /dashboard` (агрегаты, включая score/тренд/топ-3 фиксов)
- Security Score: `GET /projects/{id}/score/history?period=7d|30d` (точки + регрессия), `GET /runs/{id}/score` (score, delta, breakdown, priority list), `POST /runs/{id}/sprint-plan` (AI-план)
- AutoFix: `POST /runs/{id}/findings/{finding_id}/autofix` (генерация + валидация), `GET /autofixes/{id}` (patch, шаги валидации), `GET /autofixes/{id}/patch` (скачать `.patch`), `POST /autofixes/{id}/pull-request`
- CI: `/v1/ci/runs`, `GET /v1/ci/runs/{id}/verdict` (200 PASS / 422 FAIL), `/v1/webhooks/github|gitlab`, `GET /ci/yaml?provider=github|gitlab&workflow_id=…`, `GET/POST/DELETE /api-tokens`
- `GET /healthz`

---

## 16. Frontend и UX/UI

**Страницы:** вход/регистрация; **Dashboard** (карточки: проекты, workflow, запуски за период, найденные уязвимости по severity; **Security Score** проекта с дельтой и трендом «📈 +2.3/нед», график score по времени с маркерами коммитов, **топ-3 Priority Fix** и карточка AI-плана на спринт; график динамики находок по запускам; последние запуски; быстрые действия; графики — Recharts или аналог, доступные цвета в обеих темах); Проекты; Список workflow; **Редактор**; **Живой запуск**; История запусков + **сравнение**; Детали запуска (находки, AI-отчёт, diff-фиксы, логи, экспорт); **Библиотека шаблонов** (каталог, детальная карточка, публикация, избранное, отзывы); Интеграция CI/CD (YAML-генератор с копированием, токены, статус webhook); Настройки (AI-провайдер с тестом, credentials-хранилище, allowlist репозиториев, участники/роли, расписания, язык/тема).

**Редактор (обязательные возможности):**
- панель палитры нод по категориям с поиском; drag-and-drop на холст; соединение портов мышью с подсветкой допустимых целей и **валидацией неправильных соединений** (типы портов, циклы, дубль соединений) с понятным сообщением;
- масштабирование, перемещение холста, миникарта, сетка/привязка, авто-раскладка;
- боковая панель настройки выбранной ноды (форма из JSON Schema: строки, числа, enum, boolean, массивы, селектор credentials, cron-конструктор с человекочитаемым описанием, редактор выражений IF с подсказками), валидация на лету;
- контекстное меню (дублировать, удалить, отключить ноду, копировать/вставить), горячие клавиши, множественное выделение, **Undo/Redo** (история изменений), копирование/вставка фрагмента;
- сохранение (автосохранение черновика + явное сохранение, индикатор несохранённых изменений), импорт/экспорт JSON графа;
- кнопки «Запустить», «Проверить граф» (подсветка ошибок на нодах), «AI-ассистент» (панель чата и генерация по описанию, раздел 12.3);
- режим просмотра запуска: статусы нод в реальном времени (цвета/иконки/спиннер), анимация потока данных по рёбрам, счётчики объектов, панель с логами и входами/выходами выбранной ноды, итоговое время.

**Детали запуска — фичи команды:** бейдж вердикта PASS/FAIL и переключатель «Новые / Существующие / Все» (с `diff_hunk`, коммитом и автором новой находки); вкладка Security Score (разбивка штрафа, Priority Fix List с ожидаемым +score, AI-план); у находки с `autofix ≠ none` кнопка **AutoFix**: шаги валидации (чеклист), diff «было/стало», `requires_config`, кнопки «Создать PR» (активна только при `allow_write`) и «Скачать .patch». В UI честно указано покрытие: «AutoFix доступен для N из M правил».

**Качество UX (оценивается жюри):** единая дизайн-система (токены цветов для dark/light, типографика, состояния hover/focus/disabled/error), пустые состояния и скелетоны загрузки, понятные ошибки с действиями, тосты, адаптивность хотя бы до планшета, доступность (клавиатурная навигация по основным действиям, контраст WCAG AA, aria-атрибуты у интерактива), все строки через i18n (RU/EN), даты/числа по локали. Секреты в UI всегда маскированы. Выглядеть должно как профессиональный security-продукт, а не как прототип.

---

## 17. Тестирование и оценка качества (всё запускается одной командой `make test`)

1. **Юнит-тесты анализаторов:** для каждого правила — позитивные и негативные фикстуры (включая «опасно похожие» безопасные конструкции): секреты (все слои, подавления), SCA (парсер Gradle во всех формах из раздела 8.2, version catalog, lockfile, сравнитель версий на граничных случаях, CVSS-калькулятор на эталонных векторах), SAST (каждое правило, межфайловый IDOR, цепочки `requestMatchers`, шаблоны строк).
2. **Eval-харнесс на учебном наборе** (`backend/tests/eval/`): запускает три анализатора на `fixtures/organizer-training/training-project/`, сверяет с `ground-truth/training-findings.json` по правилам оценки: категория+путь → `class`+строка в диапазоне (допуск диапазона по `alternateLocations`) для SECRET/SAST; `group/artifact/version/advisoryId` для SCA; **падает**, если пропущена хотя бы одна из 15, сработал любой из 6 контролей или есть лишние находки без объяснённой причины. Печатает таблицу recall/precision.
3. **Анти-оверфиттинг — мутанты** (`fixtures/mutants/`, минимум 3 вариации учебного проекта, которые ты **сам** создаёшь, имитируя скрытую вариацию организаторов): переименованные пакеты/классы/переменные/файлы; сдвинутые строки; другие приёмы той же проблемы (конкатенация через `StringBuilder`/`joinToString`/`format` вместо `+`; fallback через `?: "…"` и `getProperty(…, "…")`; версия через `ext`/version catalog/`gradleProperty`; цепочка `requestMatchers` в другом порядке/с `antMatchers`-аналогами; IDOR через сервисный слой вместо репозитория; CORS через `CorsConfigurationSource` вместо `WebMvcConfigurer`; TLS-отключение через `TrustManager` вместо `HostnameVerifier`; SQL через `String.format`), а также **новые контроли** (безопасные похожие конструкции). Для каждого мутанта — свой файл ожидаемых находок; харнесс на мутантах обязан проходить с теми же требованиями (все ожидаемые найдены, контролей нет). Это главный гарант качества на скрытой вариации.
4. **Тесты движка:** валидатор графа (циклы, порты, обязательные поля), ветвление IF/skip-логика, параллельные ветки, таймауты, отмена, события и порядок, передача данных между нодами, планировщик (расписание, отсутствие дублей), восстановление после рестарта.
5. **Тесты нод:** каждый тип ноды; уведомления — реальные обмены: Telegram (локальный HTTP-сервер, имитирующий Bot API; проверка тела/маскирования), SMTP (локальный SMTP-сервер, например `aiosmtpd`, проверка полученного письма), Webhook (локальный приёмник, проверка HMAC-подписи и SSRF-запретов).
6. **Тесты API:** аутентификация, роли, изоляция workspace (IDOR-тесты на нас самих), CRUD, экспорт `submission.json` + **валидатор формата организаторов** (пример из `docs/training-result-example.json` проходит, невалидные случаи отклоняются), библиотека шаблонов (публикация → вычистка секретов → поиск/фильтры → использование → правка копии → рейтинг/избранное/отзывы), CI (токены, запуск, статус, gate, вебхуки с подписью и без, возврат статуса на mock-сервер), история и сравнение запусков.
7. **Тесты безопасности:** маскирование (внедрённый секрет нигде не светится), шифрование (в БД нет открытого значения; API не отдаёт значение), SSRF (loopback/private/metadata/redirect/DNS-rebinding блокируются), repo-guard (посторонний git-URL, `file://`, zip-slip, `..` в пути блокируются), ReDoS-защита.
8. **AI-тесты:** контрактные тесты провайдеров на локальном OpenAI-compatible тестовом сервере (формат запроса, JSON-режим, ретраи, таймаут, 429, невалидный JSON → авто-исправление), валидатор ответа (выдуманный CVE, несуществующий файл/строка, несоответствующий `before`, неизвестный `finding_id`), AI-генерация графа (валидный граф, ошибочный граф → цикл исправления → отказ), диалоговые операции (применение/откат). Если доступна реальная LLM — живой прогон и фиксация качества (сколько ответов прошло валидатор без правок).
9. **Frontend:** vitest для логики (валидация соединений, undo/redo, генерация форм из схемы, i18n); **Playwright e2e**: регистрация → создание workflow перетаскиванием нод → настройка → запуск на `fixtures/organizer-training` → наблюдение статусов в реальном времени → просмотр находок/AI-отчёта → сравнение запусков → публикация и использование шаблона; проверка тёмной/светлой темы и переключения языка (скриншоты в `docs/screens/`).
10. **Фичи команды (раздел 12А)** — перечень обязательных тестов указан в каждом подразделе 12А.1–12А.3.
11. **Сквозной сценарий (обязательный гейт):** на запущенном стеке (`docker compose up`) выполнить демо-сценарий (раздел 21) и сохранить вывод/скриншоты в `docs/REPORT.md`.

---

## 18. Docker, запуск, документация

- `docker-compose.yml`: `postgres`, `backend` (API), `worker`, `frontend` (статика через nginx или vite preview), опциональный профиль `ollama` (локальная LLM) и профиль `mock` (локальные mock-серверы Telegram/SMTP/GitHub/GitLab для демо без интернета). Healthchecks, тома, миграции Alembic при старте, `.env.example`, понятные порты.
- `Makefile`: `make up`, `make down`, `make dev-backend`, `make dev-frontend`, `make test`, `make test-eval`, `make e2e`, `make lint`, `make seed`.
- `README.md` (RU): что это; быстрый старт за 5 команд; настройка LLM (Ollama и OpenAI-compatible, бесплатные варианты); настройка уведомлений; демо-сценарий; тесты; структура проекта; как добавить новую ноду (пример в 20 строк); как подключить CI; ограничения и честные оговорки.
- `docs/`: `ARCHITECTURE.md` (диаграмма компонентов в Mermaid + поток данных), `NODES.md` (все ноды, порты, параметры, формат данных), `ANALYZERS.md` (алгоритмы, правила, подавление FP, шкала критичности), `API.md`, `CI_CD.md`, `AI.md` (провайдеры, промпты, схема, валидатор, метрики качества), `SECURITY.md` (модель угроз, шифрование, маскирование, SSRF, allowlist), `TEAM_FEATURES.md` (diff-aware, формула score с калибровкой, AutoFix: алгоритмы, ограничения, покрытие правил), `PRESENTATION_NOTES.md` (см. ниже), `REPORT.md` (итоговый отчёт по чеклисту — раздел 22).
- `PRESENTATION_NOTES.md` готовит материал под презентацию организаторов: проблема и пользователь; как решение закрывает цель; список **всех** реализованных нод; алгоритмы secrets/SCA/SAST; классификация находок; передача данных между нодами; какая LLM использована и как передаются данные; проверка ответа (схема, файлы/строки, отсутствие выдуманных CVE) с реальными примерами и оценкой полезности; архитектура и «как за минуту добавить ноду / внешний сервис / переключить на локальную LLM»; реализованные звёздочки; **фичи команды с обоснованием для жюри** (diff-aware: «не виноваты в старом коде, но не пропустим новое»; score — метрика внутреннего тренда, а не рейтинг между проектами; AutoFix «проверен нашим же анализатором»); планы развития; пошаговый сценарий живой демонстрации на тестовом репозитории.

---

## 19. Фазы работы и гейты

Каждая фаза заканчивается проверкой; результаты коротко записываются в `docs/REPORT.md` (журнал фаз). Не переходи дальше при красных тестах.

- **Фаза 0 — Исследование и план.** Клонировать набор организаторов в `fixtures/organizer-training/`; прочитать все его файлы; прочитать `Garden Центр-инвест.pdf`/`TZ.md`; создать скелет проекта, `docs/PLAN.md`, базовый CI-скрипт тестов. *Гейт:* скелет запускается (`make test` проходит пустой набор, backend/health, frontend собирается), план согласован с этим промптом.
- **Фаза 1 — Анализаторы.** Общая модель `Finding`, severity, secrets, SCA (+CVSS, версии, Gradle/lockfile), SAST правила 1–5 затем 6–11, экспорт `submission.json` + валидатор формата, Markdown/HTML-отчёт, eval-харнесс, мутанты. *Гейт:* eval на учебном наборе 15/15, 0 контролей, 0 неоправданных лишних; все мутанты проходят.
- **Фаза 2 — Движок и ноды.** Реестр нод, граф-валидатор, исполнитель (ветвление/параллельность/таймауты/отмена), события и SSE, планировщик, все ноды раздела 7, воркер/очередь, БД и миграции, история запусков. *Гейт:* тесты движка и нод зелёные; CLI/API-запуск «ручной триггер → source → три сканера → IF → notify → export» на учебном репозитории работает end-to-end; уведомления доходят до локальных mock-серверов.
- **Фаза 3 — Безопасность платформы и многопользовательность.** Аутентификация/роли/workspaces, хранилище credentials, шифрование, маскирование, SSRF-защита, repo-guard, аудит, rate limit. *Гейт:* тесты безопасности зелёные; ручная проверка: секрет нигде не виден, посторонний repo-URL отклонён.
- **Фаза 4 — LLM.** Провайдеры (OpenAI-compatible, Ollama), настройки, `ai.report`, валидатор достоверности, fix-diff, детерминированный fallback с пометкой. *Гейт:* контрактные тесты зелёные; живой прогон на реальной LLM, если доступна (иначе честная запись); валидатор ловит подсаженные выдуманные CVE/строки в тестах.
- **Фаза 5 — Frontend.** Дизайн-система, страницы, редактор со всеми возможностями, живой запуск, история и сравнение, настройки, i18n, темы. *Гейт:* vitest + Playwright e2e зелёные; скриншоты обеих тем и языков; ручной прогон в браузере.
- **Фаза 6 — Звёздочки.** Библиотека шаблонов (бэкенд+UI+seed), CI/CD (API, токены, CLI, YAML, вебхуки, возврат статуса, gate), AI-генерация + чат-правка. *Гейт:* тесты звёздочек зелёные; демонстрация каждой на запущенном стеке.
- **Фаза 6А — Фичи команды (раздел 12А).** Diff-aware scan → Security Score → AI AutoFix (в этом порядке: score использует novelty из diff, AutoFix-демо опирается на diff-aware проверку PR). *Гейт:* тесты 12А зелёные; eval 15/15 и `submission.json` не изменились; демо-сценарии 12А.1–12А.3 выполнены на запущенном стеке (mock GitHub/GitLab).
- **Фаза 7 — Упаковка и документация.** Docker Compose целиком, Makefile, README, `docs/*`, `PRESENTATION_NOTES.md`. *Гейт:* «холодный старт» по README на чистом окружении (удали тома/кэш, следуй только документации) — приложение поднимается, демо-сценарий проходит.
- **Фаза 8 — Финальная верификация.** Полный `make test`, e2e, eval на учебном наборе и мутантах, сквозной демо-сценарий, заполнить чеклист соответствия ТЗ с доказательствами (раздел 22).

---

## 20. Критерии готовности модулей (Definition of Done)

- **Анализаторы:** eval 15/15 и 0 контролей на учебном наборе; все мутанты проходят; каждое правило покрыто позитивным и негативным тестом; документация алгоритмов; нет жёстко зашитых путей/строк/имён из набора организаторов (проверь поиском по коду `grep -R "repairdesk\|RepairTicketReader\|WarrantyHeaders" backend/app` → пусто).
- **Движок:** граф сохраняется/валидируется/исполняется; ветвление и параллельность работают; события приходят по SSE в правильном порядке; тест расширяемости (новая нода одним файлом) зелёный.
- **Ноды:** все из раздела 7 реализованы, имеют схемы, тесты и описание в `NODES.md`; уведомления доходят до mock-серверов (Telegram/SMTP/Webhook) с проверкой содержимого.
- **LLM:** смена провайдера — только настройками; валидатор отсекает подсаженные ошибки; все AI-отчёты хранятся и показываются; fallback помечен.
- **Безопасность:** все пункты раздела 13 подтверждены тестами.
- **Frontend:** все возможности редактора из раздела 16 работают; e2e зелёный; RU/EN и dark/light.
- **Звёздочки:** каждый пункт подпунктов `TZ.md` (разделы 1.2.1–1.2.3) отмечен с доказательством (тест/эндпоинт/скриншот).
- **История:** запуски, находки, AI-отчёты сохраняются; сравнение корректно показывает новые/устранённые.
- **Diff-aware:** new/existing классифицируются верно (включая переименования, whitespace, SCA по версиям, межфайловые находки); PR блокируется только новыми находками ≥ порога; 200/422 + exit code; комментарий в PR/MR обновляется, а не дублируется.
- **Security Score:** детерминирован (один и тот же вход даёт один и тот же score), формула и калибровка задокументированы, тренд и Priority Fix List на дашборде, AI-план проходит валидацию чисел.
- **AutoFix:** только патчи, прошедшие самопроверку, доходят до PR; PR создаётся на mock GitHub и GitLab; без `allow_write` — отказ; покрытие правил считается из метаданных и показывается честно.
- **Запуск:** холодный старт по README проходит.

---

## 21. Демо-сценарий (должен работать и быть записан в README/REPORT)

1. `docker compose up` → регистрация → создание workspace → настройка AI (Ollama или OpenAI-compatible) и Telegram/SMTP (mock или реальные, по доступности).
2. Проект: источник `https://github.com/TBagirov/training` (клонируется, allowlist разрешает) либо загрузка `fixtures/organizer-training/training-project` архивом.
3. Сборка workflow в редакторе перетаскиванием: `trigger.manual → source.repo → [secrets, sca, sast] → merge → if_else(severity.max ≥ HIGH) → ai.report → notify.telegram (+ output.report_export)`; ветка `false` → notify.webhook.
4. Запуск; живая подсветка нод, потоки данных; результаты: 15 находок, контролей нет; AI-отчёт с diff-фиксами; индикатор доверия валидатора; уведомление доставлено; экспорт `submission.json` проходит валидатор формата.
5. Повторный запуск после правки уязвимости (например, параметризация SQL) → **сравнение запусков** показывает «устранено 1».
6. Публикация сценария как шаблона → поиск в библиотеке → использование → правка копии.
7. Раздел «Интеграция»: сгенерированный GitHub Actions/GitLab CI YAML; запуск CLI из «пайплайна» → `exit 1` на Critical; webhook push/PR с подписью → статус возвращён на mock GitHub.
8. AI-генерация: ввести пример из раздела 12.3 → граф отрисован → правка через чат («добавь e-mail») → запуск.
9. Diff-aware (12А.1): PR с синтетическим AWS-ключом → FAIL, комментарий в PR (mock GitHub) → ключ убран → PASS; существующие находки помечены `existing` и не блокируют.
10. Security Score (12А.2): первый прогон → «починили» 2 находки → второй прогон: зелёная дельта на графике, обновлённый Priority Fix List и AI-план.
11. AI AutoFix (12А.3): находка «хардкод пароля» → AutoFix → чеклист валидации + diff → «Создать PR» на локальном mock GitHub → diff-aware прогон ветки `autofix/…`: 0 новых находок.

---

## 22. Финальный отчёт и чеклист соответствия ТЗ

В конце создай `docs/REPORT.md`: (1) журнал фаз с результатами гейтов; (2) вывод `make test` (сводка, число тестов), таблица eval (учебный набор + мутанты); (3) **чеклист по каждому пункту ТЗ** — все пункты из разделов 1.1, 1.2 (все три звёздочки), 1.3 `TZ.md` и все обязательные/дополнительные требования PDF (прототип, собственные модули, LLM-интеграция, интерфейс, ограничения безопасности, модульность, закрытый контур, шифрование/маскирование, история), а также **каждый пункт фич команды из раздела 12А** — для каждого: статус `DONE / PARTIAL / NOT DONE`, где реализовано (файл/эндпоинт) и чем подтверждено (тест/скриншот/команда); (4) честный список ограничений и непроверенного (что не удалось проверить из-за окружения, например реальная LLM или реальный Telegram); (5) планы развития.

**Главное правило:** не объявляй работу завершённой, пока каждый пункт не реализован, проверен запуском и подтверждён тестом. Если пункт нельзя выполнить полностью — отметь его `PARTIAL`/`NOT DONE` и объясни причину. Никаких «готово» без доказательств.
