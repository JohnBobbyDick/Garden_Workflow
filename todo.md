# TODO — AI Security Workflow (Cyber Garden 2026, «Центр-инвест»)

Рабочий план исполнения `prompt.md`. Источник истины: `Garden Центр-инвест.pdf` > `prompt.md` > `TZ.md`.
Ссылки вида `§8.1` указывают на разделы `prompt.md`.

**Как пользоваться:** идти строго по фазам. Пункт отмечается `[x]` только после запущенной проверки (тест/curl/браузер) с видимым выводом. Гейт фазы не пройден, значит следующую фазу не начинать. После каждой фазы: запись в `docs/REPORT.md` (журнал фаз) и локальный коммит (без `push`).

---

## Сквозные правила (проверять в каждой фазе)

- [ ] Никаких заглушек: `TODO`, `pass # later`, `NotImplementedError`, моков в продуктовом коде, захардкоженных результатов, фейковых интеграций (§0.2, §2)
- [ ] Запрещены готовые workflow-платформы (n8n, Node-RED) и готовые сканеры/их правила (Semgrep, Gitleaks, Trivy, detekt-security, Bandit, Dependency-Check, Snyk, truffleHog, grype, osv-scanner) (§2)
- [ ] LLM только объясняет, ничего не обнаруживает (§2)
- [ ] Никакой подгонки под учебный репозиторий: нет проверок по имени файла/строке/классу/переменной из набора организаторов (§2, §20). Регулярная проверка: `grep -R "repairdesk\|RepairTicketReader\|WarrantyHeaders" backend/app` должен быть пустым
- [ ] Тестовые репозитории только для чтения: `fixtures/organizer-training/`, `fixtures/mutants/`, `github.com/TBagirov/training` не меняются; все записи (PR, комментарии, статусы) только на локальных mock GitHub/GitLab (§2)
- [ ] Сканируются только: репозиторий организаторов, загруженные архивы пользователя, собственные фикстуры (allowlist, §13)
- [ ] Секреты маскируются везде: логи, API, UI, отчёты, run_events, БД, промпты, уведомления (§2, §13)
- [ ] Git: локальные коммиты после каждой фазы, без push; в репозиторий не попадают `.env`/ключи, только `.env.example` (§0.4)
- [ ] Язык: код на английском; UI RU по умолчанию + EN; документация на русском; AI-отчёты на языке интерфейса (§0.6)
- [ ] Противоречия prompt.md и PDF фиксировать в список для `docs/REPORT.md`

---

## Фаза 0 — Исследование, план, скелет (§19)

### 0.1 Изучение входных данных
- [x] Прочитать `Garden Центр-инвест.pdf` целиком, выписать обязательные/дополнительные требования и расхождения с prompt.md
- [x] Прочитать `TZ.md` (чеклист разделов 1.1, 1.2.1–1.2.3, 1.3)
- [x] `git clone https://github.com/TBagirov/training` во временную директорию → скопировать содержимое без `.git` в `fixtures/organizer-training/`
- [x] Прочитать **все** файлы набора: каждый `.kt`, `application.yml`, `schema.sql`, `data.sql`, `build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`, `gradle.lockfile`
- [x] Прочитать `ground-truth/training-findings.json` + `.md` (15 findings, 6 controls, `alternateLocations`, `difficultyRationale`, `expectedDetection`)
- [x] Прочитать `docs/submission-format.md`, `docs/training-result-example.json`
- [x] Прочитать `vulnerability-database/vulnerabilities.json`, `schema.json`, `README.md`
- [x] Выписать для себя таблицу «находка эталона → какое общее правило её ловит» (без хардкода имён)

### 0.2 План и скелет
- [x] `docs/PLAN.md`: модули, порядок, риски (tree-sitter-kotlin на py3.12, PostgreSQL в тестах, Playwright, доступность LLM)
- [x] Структура каталогов по §5: `backend/`, `frontend/`, `cli/`, `fixtures/`, `docs/`, `scripts/`
- [x] `backend/pyproject.toml` (Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, tree-sitter, tree-sitter-kotlin, httpx, argon2/bcrypt, cryptography, aiosmtpd для тестов, pytest, pytest-asyncio)
- [x] `backend/app/main.py` с `GET /api/healthz`
- [x] `frontend/`: Vite + React 18 + TS + Tailwind + `@xyflow/react` + Zustand + TanStack Query + i18n; собирается `npm run build`
- [x] `Makefile`: заготовки `up`, `down`, `dev-backend`, `dev-frontend`, `test`, `test-eval`, `e2e`, `lint`, `seed`
- [x] `.env.example`, `.gitignore` (`.env`, `node_modules`, `__pycache__`, артефакты)
- [x] `docs/REPORT.md` с разделом «Журнал фаз»

### Гейт фазы 0
- [x] `make test` проходит (пустой/минимальный набор)
- [x] `curl /api/healthz` → 200
- [x] `frontend` собирается
- [x] План сверен с prompt.md
- [x] Коммит «phase 0: research, plan, skeleton»

---

## Фаза 1 — Анализаторы (§8, §9, §10, §3.1)

### 1.1 Общее (`analyzers/common/`)
- [x] `finding.py`: модель `Finding` со всеми полями §10 (id стабильный хэш category+rule+path+нормализованный контекст; SCA-поля; SECRET-поля `fingerprint`/`masked_value`; diff-поля; `autofix`)
- [x] `severity.py`: шкала LOW<MEDIUM<HIGH<CRITICAL, матрицы SCA/SECRET/SAST как таблица данных + функция «почему такой уровень» → `severity_reason` (§9)
- [x] `files.py`: обход файлов с исключениями (`build/`, `.git/`, `node_modules/`, бинарники, лимит размера), относительные пути с `/`
- [x] `kotlin_ast.py`: обёртка tree-sitter-kotlin (запасной regex-режим заменён устойчивым к ошибкам разбором tree-sitter — см. REPORT, решения)
- [x] Дедупликация: одна проблема = одна находка, выбирается самый специфичный `class`
- [x] Маскирование значений: `fingerprint` (8 hex SHA-256 + длина), маска `ab…(len=24)`, маскированный сниппет

### 1.2 Секреты (`analyzers/secrets/`, §8.1)
- [x] Набор расширений файлов + Dockerfile + текстовые; `.md`/`.txt`/`docs/` с подавлением плейсхолдеров
- [x] Слой 1, сигнатуры: AWS (AKIA/ASIA + secret рядом), GitHub PAT (`ghp_`, `github_pat_`, `gho_`…), Telegram bot token, Slack `xox[abpr]-`, Stripe `sk_live_`, Google `AIza`, JWT с проверкой base64url-заголовка, PEM private keys, URL с кредами, JDBC с паролем, Basic-auth
- [x] Слой 2, контекст имён: пары ключ→значение в yml/properties/json/env/kt/java; заголовки `X-Api-Key`, `Authorization: Bearer`; `setBearerAuth`, `header(...)`, `.password(...)`; именованные аргументы Kotlin; `const val`/`val`; `data class` с дефолтами; полный YAML-путь ключа
- [x] Слой 3, Kotlin-AST разрешение констант: локальные/файловые/классовые `val`/`const val`; `a + b`; шаблоны с константами; `StringBuilder.append`; `listOf(..).joinToString`; `String.format`/`.format`; `String(Base64...decode(...))`; `.reversed()`, `.trim()`, `.lowercase()` → `recoverable-token` с диапазоном строк ≤15
- [x] Слой 4, fallback: `System.getenv("X") ?: "lit"`, `env.getProperty("x","lit")`, `@Value("\${x:lit}")`, `${VAR:lit}` в YAML/properties, `getOrDefault`, `orElse` → `secret-fallback`
- [x] Слой 5, эвристика: энтропия Шеннона по алфавитам + длина + разнообразие классов + секретный контекст; не флагать UUID/хэши коммитов/версии/URL без кредов; пороги настраиваемые
- [x] Подавление FP: `${ENV}`, `#{…}`, `{{…}}`, `<…>`, `%…%`, `YOUR_*`, `xxx`, `changeme`/`example`/`dummy`/`sample`, `***`, пустые, `null`; значения из окружения без дефолта не секреты
- [x] Тестовые/документационные пути понижают confidence (не игнорируются); порог confidence для официальной выгрузки настраиваемый и задокументирован
- [x] Классы: `password`, `api-key`, `configuration-token`, `secret-fallback`, `recoverable-token`, `private-key`, `aws-access-key`, `github-token`, `telegram-token`, `jwt`, `db-credentials`, `generic-secret`
- [x] Контроли `YOUR_API_KEY` в README и `${INVENTORY_TOKEN}` без дефолта отброшены общим правилом
- [x] Юнит-тесты: каждый слой (позитив + «опасно похожий» негатив), подавления, маскирование

### 1.3 SCA (`analyzers/sca/`, §8.2)
- [x] `gradle_parser.py` (tree-sitter, не один regex): `implementation/api/compileOnly/runtimeOnly/testImplementation/kapt/annotationProcessor…`; `add("implementation", "g:a:v")` многострочный и с висячей запятой; `group=, name=, version=`; `platform(...)`/BOM; `libs.xxx`
- [x] Версии: литерал, `$var`/`${var}`, `val x = "…"`, `extra["x"]`/`ext`, `providers.gradleProperty("k").get()/.orNull`, `project.property("k")` → `gradle.properties`
- [x] Подмодули из `settings.gradle.kts` (`include(...)`); базовый Groovy `build.gradle`
- [x] `version_catalog.py`: `gradle/libs.versions.toml` (`[versions]`, `[libraries]`, `module=`/`group+name`, `version.ref`, алиасы)
- [x] `lockfile.py`: версия из `gradle.lockfile` побеждает объявленную; без версии (BOM, нет в lockfile) → пропуск с инфо-примечанием
- [x] Хранить `declared_version`, `resolved_version`, источник версии, строки объявления и определения переменной (`alternateLocations`)
- [x] Транзитивные: только при `include_transitive=true`, `scope=transitive`, не в официальную выгрузку по умолчанию
- [x] `versions.py`: numeric-dot-separated, `1.9 == 1.9.0`, `20230618` = один компонент; квалификаторы/динамические/пустые вне области с примечанием; интервалы `lower/lowerInclusive/upper/upperInclusive`
- [x] `vulndb.py`: загрузка + валидация по `schema.json` (громкая ошибка), индекс `group:artifact`; копия в `backend/vulndb/vulnerabilities.json`; подключение другого JSON той же схемы
- [x] `matcher.py`: одна запись справочника = одна находка; `advisoryId` — CVE из aliases, иначе GHSA; `fixedVersions` → «обновить до ≥ X» (ближайшая в ветке > текущей); `sources`
- [x] `cvss.py`: собственный калькулятор базовой оценки CVSS v3.x; сверка с severity справочника
- [x] `path` = файл объявления, `line` = строка объявления
- [x] Тесты: все формы объявления, version catalog, lockfile, граничные версии, CVSS на эталонных векторах, контроль `commons-lang3:3.20.0` → нет находки

### 1.4 SAST (`analyzers/sast/`, §8.3)
- [x] IR поверх tree-sitter: классы, функции, параметры с аннотациями, вызовы, шаблоны строк, присваивания, лямбды
- [x] `callgraph.py`: граф вызовов по конструкторным зависимостям (поле `private val x: T` → вызовы `x.m()`), межфайлово
- [x] Распознавание Spring-аннотаций (`@RestController`, `@*Mapping`, `@RequestParam`, `@PathVariable`, `@RequestBody`, `@RequestHeader`, `@PreAuthorize`, `@Secured`, `@CrossOrigin`, `@Configuration`, `@Bean`, `@Repository`, `@Service`, `@Query`)
- [x] `taint.py`: источники → распространение (присваивания, шаблоны, конкатенация, format, StringBuilder) → стоки
- [x] Каждая находка: `class`, `path`, `line`, `endLine` (≤15), маскированный сниппет, `title`, `description`, `severity`, `confidence`, `cwe`, `remediation`, `rule_id`
- [x] Правило 1 `sql-injection` (JdbcTemplate.*, Statement, EntityManager, NamedParameterJdbcTemplate, `@Query` со SpEL/конкатенацией, prepareStatement со строкой с подстановкой); параметризованный `?` рядом не срабатывает
- [x] Правило 2 `tls-verification` (HostnameVerifier→true, NoopHostnameVerifier, ALLOW_ALL, пустой TrustManager, TrustAllStrategy, setDefaultHostnameVerifier, OkHttp `.hostnameVerifier`); штатный HTTPS-клиент не срабатывает
- [x] Правило 3 `credentialed-cors` (`*` в origins/patterns/@CrossOrigin/отражение Origin + allowCredentials true); диапазон охватывает обе настройки; варианты WebMvcConfigurer и CorsConfigurationSource
- [x] Правило 4 `route-authorization` (`spring_security.py`): разбор `authorizeHttpRequests`/`antMatchers`/`mvcMatchers`; чувствительность по семантике пути + по содержимому обработчика + теневое правило; публичный каталог без ПДн не находка; строка = строка `permitAll`; `csrf.disable()` + cookie-сессия отдельным предупреждением; изменяющие методы без защиты — низкая уверенность
- [x] Правило 5 `object-authorization` (IDOR/BOLA): контроллер → сервис → репозиторий; нет Authentication/Principal/SecurityContextHolder/сравнения владельца/`@PreAuthorize #id`; запрос только по ID; основное место — доступ к данным, вызов контроллера в `alternate_locations`; одна находка на проблему
- [x] Правило 6 `hardcoded-credentials` (InMemoryUserDetailsManager, `.password("{noop}…")`)
- [x] Правило 7 `unsafe-deserialization`
- [x] Правило 8 `path-traversal`
- [x] Правило 9 `weak-crypto`
- [x] Правило 10 `missing-input-validation`
- [x] Правило 11 `insecure-endpoint` (включая конфиги actuator/h2/debug/stacktrace)
- [x] Правила 6–11 не дают FP на `training-project/`; иначе доработать или понизить confidence и исключить из официальной выгрузки
- [x] Метаданные правил: `autofix: llm|deterministic|none`
- [x] Тесты: позитив + негатив на каждое правило, межфайловый IDOR, цепочки `requestMatchers`, шаблоны строк

### 1.5 Экспорт и отчёты (`export/`, §3.1, §10)
- [x] `submission_json.py`: маппинг `Finding → запись` строго по `docs/submission-format.md` (category верхним регистром, относительный path без `..`, class, line, endLine ≤ line+14, SCA group/artifact/version/advisoryId); фильтр по confidence; без транзитивных; без diff/autofix-полей
- [x] Собственный валидатор формата организаторов; невалидный экспорт = ошибка; `training-result-example.json` проходит, невалидные случаи отклоняются (тест)
- [x] `markdown.py`, `html.py`: сводка, таблица по категориям, детали (файл:строки, координаты+версия+CVE/GHSA для SCA), severity, рекомендация; секреты скрыты
- [x] AI-раздел в markdown/html — подключён в фазе 4 (`export/ai_section.py`)

### 1.6 Eval-харнесс и мутанты (§17.2–17.3)
- [x] `backend/tests/eval/`: запуск трёх анализаторов на `training-project/`, сверка с ground truth (категория+путь+class+строка в диапазоне с учётом `alternateLocations`; SCA координаты+версия+advisory); падает на пропуске, контроле или необъяснённой лишней находке; печать таблицы recall/precision
- [x] `fixtures/mutants/` — минимум 3 мутанта: переименованные пакеты/классы/переменные/файлы, сдвинутые строки, другие приёмы (StringBuilder/joinToString/format; `?: "…"`/getProperty; ext/catalog/gradleProperty; другой порядок requestMatchers/antMatchers; IDOR через сервис; CORS через CorsConfigurationSource; TLS через TrustManager; SQL через String.format) + новые безопасные контроли
- [x] Для каждого мутанта файл ожидаемых находок; харнесс на мутантах с теми же требованиями
- [x] `make test-eval`

### 1.7 Документация
- [x] `docs/ANALYZERS.md`: каждое правило (что ищет, почему, как снижаются FP), шкала критичности, порог confidence

### Гейт фазы 1
- [x] Eval на учебном наборе: **15/15**, 0 контролей, 0 необъяснённых лишних
- [x] Все мутанты проходят
- [x] grep по запрещённым именам в `backend/app` пуст
- [x] Валидатор `submission.json` зелёный
- [x] Журнал в REPORT.md, коммит «phase 1: analyzers»

---

## Фаза 2 — Движок, ноды, БД, воркер (§6, §7, §14)

### 2.1 БД и модели
- [x] SQLAlchemy-модели (§5): user, workspace, project, workflow, run, run_event, finding, ai_report, template, review, credential, api_token, ci_*, autofix, repo_allowlist (+ schedule, audit)
- [x] Alembic-миграции; SQLite для юнит-тестов, отдельный прогон интеграционных на PostgreSQL

### 2.2 Ноды: контракт и реестр
- [x] `nodes/base.py`: `NodeSpec`, `Port`, `@register_node`, реестр с автообнаружением пакета `app.nodes`; метаданные type/category/title/description RU+EN, inputs/outputs, `config_schema` с `secret: true`/`credential_ref`, `async execute(ctx, inputs, config)`
- [x] `Envelope` {type, data, meta{node_id, produced_at, summary}}; типы портов trigger/repo/findings/report/json/text/bool/any
- [x] `GET /api/nodes` — каталог + JSON Schema

### 2.3 Движок (`engine/`)
- [x] `graph.py`: формат графа §6.1 (schema_version, nodes, edges с портами)
- [x] `validator.py`: ≥1 триггер, нет циклов, нет висящих обязательных входов, обязательные поля, совместимость портов, существование credentials, ветки IF; ошибки списком с `node_id`
- [x] `executor.py`: топологический обход, параллельные ветки на asyncio; IF/ELSE skip-распространение; ожидание активных входов; статусы нод/запуска; таймауты нод и запуска; отмена; ошибка ноды не роняет воркер, сообщение маскируется
- [x] `events.py`: запись в `run_events` (статусы, усечённые превью входов/выходов после маскирования, логи, длительность)
- [x] SSE `GET /api/runs/{id}/events` с `Last-Event-ID`
- [x] Снимок графа при старте запуска
- [x] `worker.py`: очередь в таблице (`SELECT … FOR UPDATE SKIP LOCKED`), отдельный процесс; в dev — внутри API
- [x] `scheduler.py`: cron / «каждый день в HH:MM», timezone (дефолт из workspace), хранение в БД, переживает рестарт, без дублей при нескольких воркерах (уникальный ключ слота)
- [x] Безопасный парсер выражений для `if_else` (без `eval`): `findings.count`, `severity.max`, `category`, `new_findings.count`, `verdict`, `score.value`, `score.delta`, сравнения, `and/or`
- [x] Безопасный шаблонизатор сообщений (`{{findings.count}}`, `{{severity.critical}}`, `{{new_findings.count}}`, `{{verdict}}`, `{{score.value}}`, `{{score.delta}}`, `{{run.url}}`, `{{ai.summary}}`), секреты не подставляются

### 2.4 Ноды §7 (каждая с тестом и описанием в NODES.md)
- [x] `trigger.manual`
- [x] `trigger.schedule`
- [x] `trigger.webhook` (provider, secret credential, events)
- [x] `source.repo` (upload zip/tar, git_url из allowlist, path внутри APP_SCAN_ROOTS, ref, project ref)
- [x] `scanner.secrets` (include/exclude, entropy threshold, heuristics)
- [x] `scanner.sca` (справочник, include_transitive, include_test_scopes)
- [x] `scanner.sast` (правила вкл/выкл, min confidence)
- [x] `logic.if_else` (порты true/false)
- [x] `logic.compare`
- [x] `logic.regex` (match/extract/filter, защита от ReDoS: таймаут/лимит длины)
- [x] `logic.severity_filter`
- [x] `logic.merge` (несколько findings-входов, дедуп)
- [x] `logic.set_value`
- [x] `output.report_export` (submission_json/markdown/html → артефакты запуска)
- [x] `output.ci_gate` (fail_on по умолчанию CRITICAL; опциональный вход verdict)
- [x] `notify.telegram`: сводка + топ находок + score + AI-вывод, `sendDocument` с `report.md`, резка по 4096
- [x] `notify.smtp`: HTML-письмо со сводкой и таблицей + вложения `report.html`/`report.md`; TLS/STARTTLS
- [x] `notify.webhook`: JSON со сводкой, маскированными находками, ссылками на экспорт; HMAC-подпись; SSRF-защита
- [ ] (`ai.report`, `ai.autofix`, `scanner.diff`, `analysis.security_score` — в фазах 4 и 6А)

### 2.5 История и API запусков (§14, §15)
- [x] Хранение: время/длительность, снимок графа, источник/ref/commit, инициатор, статусы/длительности нод, маскированные логи, находки (с run_id и node_id), артефакты, статус уведомлений, ошибки
- [x] API: workflows CRUD, `validate`, `run`, `schedule`; runs list/get/cancel/events/findings/export; `GET /runs/compare?base=&head=` (новые/устранённые/неизменные/изменения severity, сводка по категориям)
- [x] Единый формат ошибок `{"error":{"code","message","details"}}`

### 2.6 Тесты
- [x] Движок: валидатор, IF/skip, параллельность, таймауты, отмена, порядок событий, передача данных, планировщик (без дублей), восстановление после рестарта
- [x] Тест расширяемости: тестовая нода в отдельном файле без правок движка/API/фронта → видна в `/api/nodes`, исполняется
- [x] Уведомления на реальных локальных серверах: mock Telegram Bot API (HTTP), `aiosmtpd`, локальный webhook-приёмник с проверкой HMAC

### Гейт фазы 2
- [x] Все тесты движка и нод зелёные
- [x] End-to-end через API: `manual → source → [secrets, sca, sast] → merge → if_else → notify → export` на учебном проекте
- [x] Уведомления пришли на mock-серверы с отчётом внутри
- [x] REPORT.md (коммит «phase 2: engine and nodes» делает пользователь — по его указанию без коммитов)

---

## Фаза 3 — Безопасность платформы и многопользовательность (§13)

- [x] Регистрация/вход, argon2/bcrypt, JWT access (короткий) + refresh с ротацией и отзывом, `logout`, `GET /auth/me`
- [x] Rate limit на вход; CORS строго по списку origin
- [x] Workspaces, членство, роли `admin`/`developer`/`viewer`, приглашения, смена роли/удаление
- [x] Проверка принадлежности объекта в **каждом** эндпоинте; IDOR-тесты кросс-workspace
- [x] `core/crypto.py`: AES-256-GCM/Fernet, `APP_MASTER_KEY` (генерация в dev с предупреждением), версионирование ключа
- [x] Credentials API: значения только на запись, ответ `••••` + 2–4 последних символа
- [x] `core/masking.py`: центральный Masker (значения из credentials, конфига запуска, найденные сканером + паттерны) → логи, run_events, ошибки, ответы API, промпты, сниппеты, отчёты, уведомления
- [x] `core/ssrf.py`: только http/https, резолв DNS и проверка IP (loopback, private, link-local, 169.254.169.254, IPv6), защита от DNS-rebinding, лимит редиректов, таймауты, лимит размера ответа; явный allowlist хостов для Ollama/тестов
- [x] `core/repo_guard.py`: allowlist (по умолчанию только `https://github.com/TBagirov/training`), `path` только в `APP_SCAN_ROOTS`, безопасная распаковка (zip-slip, симлинки, zip-бомбы, лимиты), git только https (`GIT_ALLOW_PROTOCOL=https`, `GIT_TERMINAL_PROMPT=0`, `core.hooksPath=/dev/null`, аргументы списком, sha regex, ветки не с `-`), `--depth 1`, удаление рабочей копии
- [x] Флаг `allow_write` в allowlist (только admin, аудит); для репозитория организаторов и фикстур запрещён кодом
- [x] Анализаторы никогда не исполняют проверяемый код
- [x] Журнал аудита (вход, credentials, публикация шаблона, allowlist, API-токены); `GET /workspaces/{id}/audit`
- [x] Безопасные заголовки, лимиты тела, Pydantic-валидация
- [x] `GET/PUT /settings/allowlist`
- [x] Тесты: внедрённый секрет не находится grep-ом в логах/БД/ответах; в БД нет открытых значений; SSRF (loopback/private/metadata/redirect/rebinding); repo-guard (чужой URL, `file://`, zip-slip, `..`); ReDoS; `allow_write` для организаторов → отказ

### Гейт фазы 3
- [x] Тесты безопасности зелёные
- [x] Вручную: секрет не виден нигде; посторонний repo-URL отклонён
- [x] REPORT.md (коммит делает пользователь)

---

## Фаза 4 — LLM (§11)

- [x] `ai/providers/`: интерфейс `LLMProvider.chat(messages, response_schema, temperature, max_tokens, timeout)`; `openai_compat.py` (base_url, key, model, заголовки, `response_format` JSON или инструкция+разбор); `ollama.py` (`/api/chat`, `format: json`)
- [x] Таймауты, ретраи с backoff на 429/5xx, разбиение находок на пачки, ошибка провайдера → явная ошибка ноды
- [x] Настройки на workspace + override в ноде; ключи в зашифрованном хранилище; `GET/PUT /settings/ai`, `POST /settings/ai/test`, список моделей; по умолчанию ничего не включено, подсказки о бесплатных вариантах
- [x] `ai/schemas.py`: схема отчёта (summary, priority_order, findings[...] с explanation/impact/remediation_steps/safe_version/fix, global_recommendations)
- [x] `ai/prompts.py`: RU/EN, запрет выдумывать id/файлы/строки, примеры формата, только маски
- [x] `ai/validator.py`: (1) JSON-схема + одна попытка авто-исправления; (2) finding_id существует, без дублей, неизвестные отбрасываются; (3) `fix.path`/строки, `fix.before` буквально совпадает с файлом; (4) CVE/GHSA только из (справочник ∩ находки), иначе удалить + флаг `hallucinated_ids`; (5) `safe_version` по `fixedVersions`; (6) результаты валидации и метрики сохраняются
- [x] `ai/report_service.py` + нода `ai.report` (provider override, язык, `generate_fix_diff`, `fallback_to_deterministic` по умолчанию вкл., пометка `ai_generated: false`)
- [x] Хранение AI-отчётов с метаданными модели (провайдер, модель, токены); `GET /runs/{id}/ai-report`
- [x] Тесты: контрактные на локальном OpenAI-compatible HTTP-сервере (формат, JSON-режим, ретраи, таймаут, 429, невалидный JSON → авто-исправление); валидатор ловит подсаженные выдуманные CVE, несуществующий файл/строку, неверный `before`, неизвестный id; fallback
- [x] Проверить, доступна ли реальная LLM: НЕ доступна (Ollama/LM Studio не установлены, ключей нет) — честная запись в REPORT; живой прогон не выполнен

### Гейт фазы 4
- [x] Контрактные тесты зелёные
- [x] Честная запись о недоступности (живого прогона нет)
- [x] Смена провайдера только через настройки
- [x] REPORT.md (коммит делает пользователь)

---

## Фаза 5 — Frontend (§16)

### 5.1 Основа
- [x] Дизайн-система: токены цветов dark (по умолчанию)/light, типографика, состояния hover/focus/disabled/error
- [x] i18n RU/EN (все строки), даты/числа по локали; переключатели языка и темы
- [x] API-клиент (TanStack Query), auth-флоу с refresh, Zustand-сторы
- [x] Пустые состояния, скелетоны, тосты, понятные ошибки с действиями, адаптив до планшета, клавиатурная навигация, WCAG AA контраст, aria

### 5.2 Страницы
- [x] Вход/регистрация
- [x] Dashboard: карточки (проекты, workflow, запуски, уязвимости по severity), график находок по запускам, последние запуски, быстрые действия (score/тренд/топ-3/AI-план — в 6А)
- [x] Проекты
- [x] Список workflow
- [x] Редактор (см. 5.3)
- [x] Живой запуск
- [x] История запусков с фильтрами (workflow, статус, период, инициатор) + сравнение двух запусков
- [x] Детали запуска: граф с итоговыми статусами, таблица находок с фильтрами/сортировкой, AI-отчёт с diff-фиксами и копированием, индикатор доверия валидатора, логи, артефакты/экспорт
- [x] Настройки: AI-провайдер с тестом, credentials, allowlist, участники/роли, расписания, язык/тема
- [x] Библиотека шаблонов, Интеграция CI/CD (фаза 6)

### 5.3 Редактор (обязательно всё)
- [x] Палитра нод по категориям с поиском, drag-and-drop
- [x] Соединение портов с подсветкой допустимых целей и валидацией (типы, циклы, дубли) с сообщением
- [x] Zoom/pan, миникарта, сетка/привязка, авто-раскладка
- [x] Боковая панель: форма из JSON Schema (строки, числа, enum, boolean, массивы, селектор credentials, cron-конструктор с человекочитаемым описанием, редактор IF-выражений с подсказками), валидация на лету
- [x] Контекстное меню (дублировать, удалить, отключить, копировать/вставить), горячие клавиши, множественное выделение, Undo/Redo, копирование фрагмента
- [x] Автосохранение черновика + явное сохранение, индикатор несохранённого, импорт/экспорт JSON
- [~] Кнопки «Запусти   ть», «Проверить граф» (подсветка ошибок) — готово; «AI-ассистент» — в фазе 6.3
- [x] Режим запуска: статусы в реальном времени по SSE (цвета/иконки/спиннер), анимация данных по рёбрам, счётчики, панель логов/входов/выходов, итоговое время

### 5.4 Тесты
- [x] vitest: валидация соединений, undo/redo, генерация форм из схемы, i18n
- [x] Playwright e2e: регистрация → workflow перетаскиванием → настройка → запуск на учебном проекте → живые статусы → находки/AI-отчёт → сравнение запусков (→ шаблоны после фазы 6)
- [x] Скриншоты dark/light × RU/EN в `docs/screens/`

### Гейт фазы 5
- [x] vitest + Playwright зелёные
- [x] Скриншоты сохранены
- [x] Ручной прогон в браузере
- [x] REPORT.md (коммит делает пользователь)

---

## Фаза 6 — Задачи со звёздочкой (§12)

### 6.1 Библиотека шаблонов (§12.1)
- [x] Публикация: название, описание, категория (Secrets/SAST/SCA/Full Security Audit/CI/CD/Notifications/Custom), теги, версия, автор; вычистка секретов/credential-ссылок/URL репозиториев/chat_id → параметры шаблона (имя, тип, описание, дефолт)
- [x] Каталог: карточки, поиск (название/описание/теги), фильтры (категория, рейтинг, автор, избранное, мои), сортировка (новые, популярные, рейтинг)
- [x] Просмотр: описание, автор, использования, средний рейтинг, read-only React Flow-превью, список нод и параметров, отзывы
- [x] «Использовать»: мастер подстановки параметров, независимая копия, `usage_count++`, `forked_from`, полная редактируемость
- [x] Рейтинг 1–5 (одна оценка, можно менять), отзывы (CRUD своих), избранное
- [x] Модерация: снять с публикации / обновить версию; скрытие админом
- [x] Seed (автор «System»): «Проверка секретов», «SCA зависимостей», «SAST Kotlin/Spring», «Полный аудит + AI + Telegram», «CI gate: упасть на Critical», «Ежедневная проверка + e-mail», «Проверка по webhook + Webhook-уведомление»; `make seed`
- [x] API §15 templates; UI страницы каталога, карточки, публикации, избранного
- [x] Тесты: публикация → вычистка → поиск/фильтры → использование → правка копии → рейтинг/избранное/отзывы

### 6.2 CI/CD (§12.2)
- [x] API-токены (хэш, показ один раз, отзыв, ограничение по workflow); `GET/POST/DELETE /api-tokens`
- [x] `POST /api/v1/ci/runs` (multipart-архив или git_url из allowlist + метаданные), `GET /api/v1/ci/runs/{id}` (статус, gate, severity-сводка, ссылки), `GET /api/v1/ci/runs/{id}/report`; long-poll
- [x] `cli/aisw_ci.py` (только stdlib, один файл): пакует, загружает, опрашивает, печатает сводку, пишет `report.md`/`submission.json`, exit 0/1/2
- [x] `ci/yaml_generator.py` + `GET /ci/yaml?provider=…&workflow_id=…`: GitHub Actions (push+PR, `fetch-depth: 0`, `secrets.AISW_TOKEN`, `AISW_URL`, `$GITHUB_STEP_SUMMARY`, артефакты, комментарий PR, падение при Critical, инструкция branch protection); GitLab CI (stage, rules push/MR, `GIT_DEPTH: 0`, переменные, артефакты, `allow_failure: false`, комментарий MR, «Pipelines must succeed»)
- [x] Вебхуки `POST /api/v1/webhooks/github|gitlab`: подписи (`X-Hub-Signature-256`, `X-Gitlab-Token`), push/PR/MR (opened/synchronize/reopened), сопоставление с `trigger.webhook`, клон из allowlist, идемпотентность по delivery id, лимит тела
- [x] Возврат статуса: GitHub Commit Statuses/Checks, GitLab Commit Status (`pending → success/failed` + ссылка)
- [x] UI «Интеграция»: генератор YAML с копированием, токены, статус webhook
- [x] Тесты: mock GitHub/GitLab (настоящие HTTP-серверы), проверка заголовков/тел/подписей; неверная подпись → 401/403; YAML парсится и содержит триггеры/шаги/gate; CLI реально вызывает тестовый API

### 6.3 AI-генерация и чат-правка workflow (§12.3)
- [x] `ai/workflow_gen.py`: каталог нод из реестра + правила графа в промпт; ответ по JSON-схеме графа
- [x] Валидация `engine/validator.py` + цикл исправления до 3 попыток; при провале показать ошибки, ничего не применять
- [x] Секретные поля — только ссылки на credentials/параметры; незаполняемые параметры подсвечены «требуют заполнения»
- [x] Отрисовка в редакторе с авто-раскладкой, можно сразу запустить/править
- [x] `ai/chat.py` + `POST /ai/workflows/{id}/chat` (+GET истории): операции `add_node/update_node/remove_node/connect/disconnect/set_schedule` → применение к копии → валидация → превью-diff → «Применить/Отклонить» → undo/redo; история хранится с workflow
- [x] Эталонные примеры как тест-кейсы: PDF «каждый день в 14:00 … секреты … на почту» → `schedule(0 14 * * *) → source.repo → scanner.secrets → report_export → notify.smtp`; TZ.md «… секреты и зависимости … Critical или High → Telegram» → schedule + secrets + sca + merge + if_else(severity.max ≥ HIGH) + notify.telegram на true
- [x] Тесты на локальном OpenAI-compatible сервере (валидный граф, ошибочный → исправление → отказ, чат-операции применить/откатить); живая проверка не выполнена — реальной LLM в окружении нет (запись в REPORT)

### Гейт фазы 6
- [x] Тесты звёздочек зелёные
- [x] Демонстрация на запущенном стеке: 12.1 и 12.2 вживую (шаблоны, CLI exit 0/1, вебхук → статусы на mock GitHub); 12.3 — только контрактные тесты (нет LLM)
- [x] Playwright дополнен сценарием публикации/использования шаблона
- [x] REPORT.md (коммит делает пользователь)

---

## Фаза 6А — Фичи команды (§12А), порядок: diff → score → autofix

### 6А.1 Diff-aware scan (§12А.1)
- [x] `analyzers/diff/git.py`: контекст из вебхуков (GitHub PR base/head, push before/after, `000…0` → merge-base; GitLab diff_refs/last_commit), ручной запуск (base по умолчанию `main`), CLI `diff_context` (git diff, `git show base:file` для файлов сборки, `git blame --porcelain`); git через repo_guard, только чтение; fetch base/head sha с `--deepen` до merge-base с лимитом
- [x] `on_missing_diff`: `fail` (по умолчанию) | `treat_all_as_new`
- [x] `hunks.py`: `git diff --unified=0 --find-renames <merge_base>...<head>` (три точки), globs по умолчанию, переименования, `ignore_whitespace` (`-w --ignore-blank-lines`), приведение путей к корню проекта
- [x] `classifier.py`: SECRET/SAST new если диапазон задевает new_lines (или любое `alternate_location` для межфайловых)
- [x] `sca_diff.py`: SCA-парсер на base и head, ключ `(group, artifact, advisoryId)`, `version_changed`, `fixed_in_diff`
- [x] `blame.py`: `introduced_in_commit`, `author` (не в LLM, не в шаблоны)
- [x] Вердикт FAIL/PASS по порогу (дефолт CRITICAL), `report_only`
- [x] Нода `scanner.diff` (входы repo+findings; выходы new_findings, existing_findings, verdict)
- [x] `output.ci_gate` учитывает verdict (только новые)
- [x] `GET /api/v1/ci/runs/{id}/verdict` → 200/422; поле verdict в `GET /ci/runs/{id}`; CLI exit 0/1/2
- [x] Commit status `failure` «N new critical»; комментарий в PR/MR с маркером `<!-- aisw-report -->`, upsert без спама; в CLI-режиме — `$GITHUB_STEP_SUMMARY` + публикация при наличии токена
- [x] `scripts/demo_diff.sh`: временный git-репо из копии training-project, ветка со сгенерированным AWS-ключом (не EXAMPLE, не коммитится в наш репо) → FAIL + комментарий → удаление ключа → PASS + обновлённый комментарий; 15 старых = existing
- [x] UI: бейдж PASS/FAIL, переключатель Новые/Существующие/Все с diff_hunk/коммитом/автором
- [x] Тесты: парсер hunks (несколько, новые/удалённые/переименованные/бинарные, whitespace-only), три точки vs две, классификация (изменённая строка, нетронутый файл, многострочный диапазон, межфайловый IDOR), SCA-diff (через gradle.properties → new; без изменений → existing; фикс → fixed_in_diff), пороги/report_only, 200/422, exit codes, upsert комментария GitHub/GitLab, инъекции аргументов git отклоняются

### 6А.2 Security Score (§12А.2)
- [x] `scoring/formula.py`: penalty = Σ weight×novelty (по confidence ≥ порога), weight 10/5/2/1, novelty 1.5/1.0, S = S0 × max(1, sqrt(LOC/1000)), score = round(100·exp(−penalty/S)); S0=50 по умолчанию; калибровка на учебном наборе и мутантах; параметры в настройках workspace; `score_formula_version`
- [x] Детерминированность и независимость от порядка
- [x] `trend.py`: score, delta (к предыдущему успешному с той же `scanner_set_signature`), findings_by_severity, verdict, loc, commit; МНК-тренд 7/30 дней, «недостаточно данных» при <3 точек; маркеры смены формулы/набора сканеров
- [x] `priority.py`: priority = weight×novelty/fix_effort; fix_effort из LLM (валидируется) или таблицы по class; источник ai/default; ожидаемый +score детерминированно (накопительно для топ-N)
- [x] AI-план на спринт: схема `{summary, plan, defer, projected_score}`; валидатор id; пересчёт projected_score, расхождение >1 → замена + `corrected_numbers`; фильтр CVE; fallback без LLM с `ai_generated: false`
- [x] Score считается сервисом в конце каждого запуска с находками; нода `analysis.security_score` для графа
- [x] API: `GET /projects/{id}/score/history?period=`, `GET /runs/{id}/score`, `POST /runs/{id}/sprint-plan`; `/dashboard` с score/трендом/топ-3
- [x] UI: Dashboard (score + дельта + тренд, график с маркерами коммитов, топ-3, карточка AI-плана); вкладка Score в деталях запуска; оговорка «метрика внутреннего тренда»
- [x] `docs/TEAM_FEATURES.md`: формула и калибровка
- [x] Тесты: ручные примеры, детерминированность, порядок, LOC, novelty, регрессия, ожидаемый +score, валидатор AI-плана (неверный projected_score → исправлен; неизвестный id → отброшен), fallback

### 6А.3 AI AutoFix (§12А.3)
- [x] Метаданные `autofix` у каждого правила; покрытие «N из M» считается из метаданных
- [x] `autofix/sca_bump.py`: детерминированный bump до ближайшей fixedVersion в месте определения версии (литерал, val, gradle.properties, catalog, extra) + правка lockfile + пометка про `--write-locks`
- [x] `autofix/context.py`: правило, сниппет ±10, объемлющая функция/класс (tree-sitter, лимит токенов), связанные функции по графу вызовов; всё маскировано; ответ `{file, start_line, end_line, old_snippet, new_snippet, explanation, requires_config}`
- [x] `autofix/validator.py` (чеклист в UI): схема → файл/строки → `old_snippet` совпадает с маскированным файлом (маски сопоставляются по позициям) → `new_snippet` без масок/секретов/новых литералов-секретов → применение к копии → tree-sitter без новых ERROR (без компиляции/Gradle) → самопроверка всеми тремя анализаторами (находка исчезла, новых нет) → validated/rejected; одна повторная попытка
- [x] `autofix/pr/github.py`: refs → contents (sha blob) → pulls; `autofix/pr/gitlab.py`: branches → commits → merge_requests; идемпотентность; без auto-merge; только `allow_write=true`; токен `repo_write_token`; описание PR по шаблону, label `security-autofix`; аудит
- [x] Для организаторов/архивов — diff в UI + скачивание `.patch`
- [x] Восстановление исходников на точном коммите или из зашифрованного архива с TTL `APP_UPLOAD_RETENTION_HOURS` (72)
- [x] Таблица `autofixes`; нода `ai.autofix`; API `POST /runs/{id}/findings/{fid}/autofix`, `GET /autofixes/{id}`, `GET /autofixes/{id}/patch`, `POST /autofixes/{id}/pull-request`
- [x] UI: кнопка AutoFix, чеклист, diff было/стало, requires_config, «Создать PR» (только при allow_write), «Скачать .patch», покрытие правил
- [x] Тесты на mock LLM: корректный → validated; нет old_snippet → reject; не убирает находку → reject; добавляет находку → reject; ломает синтаксис → reject; секрет в new_snippet → reject; SCA-bump для каждой формы версии; PR на mock GitHub/GitLab (последовательность, заголовки, тела, идемпотентность); `allow_write=false` → 403; маски не попадают в тело PR

### Гейт фазы 6А
- [x] Тесты 12А зелёные
- [x] Eval 15/15 и `submission.json` не изменились
- [x] Демо 12А.1–12А.3 выполнены на запущенном стеке с mock GitHub/GitLab
- [ ] REPORT.md, коммит «phase 6A: diff-aware, security score, autofix» (REPORT.md — готово; коммит делает пользователь)

---

## Фаза 7 — Упаковка и документация (§18)

- [x] `docker-compose.yml`: postgres, backend, worker, frontend (nginx/vite preview), профиль `ollama`, профиль `mock` (Telegram/SMTP/GitHub/GitLab); healthchecks, тома, Alembic при старте, понятные порты
- [x] Makefile: все цели работают
- [x] `README.md` (RU): что это; быстрый старт за 5 команд; настройка LLM (Ollama, OpenAI-compatible, бесплатные варианты); уведомления; демо; тесты; структура; как добавить ноду (пример ~20 строк); подключение CI; ограничения
- [x] `docs/ARCHITECTURE.md` (Mermaid + поток данных)
- [x] `docs/NODES.md` (все ноды, порты, параметры, формат данных)
- [x] `docs/ANALYZERS.md` (актуализировать)
- [x] `docs/API.md`
- [x] `docs/CI_CD.md`
- [x] `docs/AI.md` (провайдеры, промпты, схема, валидатор, метрики)
- [x] `docs/SECURITY.md` (модель угроз, шифрование, маскирование, SSRF, allowlist)
- [x] `docs/TEAM_FEATURES.md` (diff-aware, формула score с калибровкой, AutoFix, покрытие)
- [x] `docs/PRESENTATION_NOTES.md`: проблема и пользователь; как закрыта цель; все ноды; алгоритмы; классификация; передача данных; LLM и данные; проверка ответа с реальными примерами и метриками; архитектура и «добавить ноду/сервис/переключить на локальную LLM за минуту»; звёздочки; фичи команды с обоснованием; собственный движок как осознанный выбор; планы; пошаговый сценарий демо

### Гейт фазы 7
- [x] Холодный старт: удалить тома/кэш, следовать только README → стек поднимается, демо проходит
- [x] REPORT.md (коммит «phase 7: packaging and docs» — делает пользователь)

---

## Фаза 8 — Финальная верификация (§17.11, §21, §22)

- [x] Полный `make test` (сохранить сводку и число тестов)
- [x] Интеграционные тесты хотя бы один раз на PostgreSQL
- [x] `make e2e`
- [x] Eval на учебном наборе + всех мутантах (таблица)
- [x] Сквозной демо-сценарий §21 на `docker compose up`, вывод/скриншоты в REPORT.md:
  - [x] 1. Регистрация → workspace → настройка AI и Telegram/SMTP
  - [x] 2. Проект: git_url организаторов или загрузка архива
  - [x] 3. Сборка workflow перетаскиванием (manual → source → [secrets, sca, sast] → merge → if_else(≥HIGH) → ai.report → telegram + report_export; false → webhook)
  - [x] 4. Запуск: живые статусы, 15 находок, 0 контролей, AI-отчёт с diff-фиксами, индикатор доверия, уведомление доставлено, `submission.json` валиден
  - [x] 5. Правка уязвимости → повторный запуск → сравнение «устранено 1»
  - [x] 6. Публикация шаблона → поиск → использование → правка копии
  - [x] 7. YAML GitHub/GitLab; CLI → exit 1 на Critical; webhook с подписью → статус на mock GitHub
  - [ ] 8. AI-генерация примера → граф → «добавь e-mail» в чате → запуск
  - [x] 9. Diff-aware: PR с AWS-ключом → FAIL + комментарий → ключ убран → PASS; старые existing
  - [x] 10. Score: первый прогон → починили 2 → зелёная дельта, обновлённый Priority Fix List и AI-план
  - [x] 11. AutoFix: хардкод пароля → чеклист + diff → PR на mock GitHub → прогон ветки `autofix/…`: 0 новых
- [x] Финальный grep на запрещённые имена в `backend/app` и на `TODO`/`NotImplementedError` в продуктовом коде
- [x] `docs/REPORT.md`:
  - [x] (1) журнал фаз с результатами гейтов
  - [x] (2) вывод `make test`, таблица eval (учебный + мутанты)
  - [x] (3) чеклист по каждому пункту `TZ.md` 1.1, 1.2.1–1.2.3, 1.3 + требования PDF + каждый пункт 12А: статус DONE/PARTIAL/NOT DONE, где реализовано, чем подтверждено
  - [x] (4) честный список ограничений и непроверенного (реальная LLM, реальный Telegram и т.п.), противоречия prompt.md vs PDF, собственный движок как решение команды
  - [x] (5) планы развития
- [ ] Финальный коммит «phase 8: final verification report» — делает пользователь

## Расширение палитры нод

- [x] Группировка и ранжирование находок, преобразование JSON по путям и условиям. Проверено тестами нод.
- [x] Создание нод в рабочем пространстве, разграничение прав и миграция базы. Проверено API-тестами и Alembic на SQLite.
- [x] Добавление сохранённой ноды на холст после перезагрузки и выполнение графа. Проверено в Chrome через Playwright.
- [x] Расширить каталог до 35 встроенных типов. Исполнение десяти новых нод проверено в одном графе через API и воркер.
- [x] Найти новые ноды в палитре и скачать CSV выбранных находок из полного отчёта. Проверено в Chrome.
- [x] Вывести покрытие AI-отчёта в JSON для IF/ELSE. Проверены полное и частичное покрытие, резервный отчёт, пустой набор и поиск ноды в палитре.
- [x] Проверить содержимое контрольного ответа NVIDIA и пройти граф с реальным Nemotron на одной синтетической находке. Результат записан в разделе 8 отчёта.
- [x] Проверить выбор единственного ключа из пула NVIDIA, повторное сохранение настроек AI, права на диагностику и код завершения CLI при выводе в Windows. Результаты повторного прогона — в разделе 9 отчёта.

## Просмотр графа и подтверждение регистрации

- [x] Перетащить ноду на холсте запуска, проверить раскладку после перезагрузки, передвинуть ноды в отчёте и шаблоне. Проверено в Chrome.
- [x] Пройти регистрацию с доставкой одноразового кода по SMTP. Проверить истечение срока, ограничение попыток и повторную выдачу кода.

## NVIDIA через прокси

- [x] Передать пул из корневого `.env` в Compose и проверить в тестах смену прокси после ошибки.
- [x] Воспроизвести некорректный ответ SOCKS5 и проверить переход ко второму прокси, обработку двух отказов и повторное использование обнаруженного протокола HTTP.
- [x] Подключить публичный Telegram Bot API к общему пулу. Проверить повтор до отправки и обрыв при ожидании ответа.
- [x] Добавить в корень диагностику ключа NVIDIA и проверить успешный ответ через тестовый прокси и отказ в доступе при прямом запросе.
- [x] Запустить диагностику из системного Python 3.14 и получить от NVIDIA контрольный ответ по прямому HTTPS с ключом из окружения проекта.
- [ ] Получить контрольный ответ NVIDIA через каждый из двух настроенных прокси. При проверке оба маршрута завершились таймаутом.

## Результаты запуска и исправленный проект

- [x] Открыть AI-отчёт во время запуска и получить готовый отчёт во вкладке. Проверено в Vitest для запуска с промежуточным отчётом и без него.
- [x] Применить одиночный патч, исправить остальные доступные находки и скачать ZIP. Проверено в Chrome на учебном проекте.
- [x] Перепроверить готовые патчи, если провайдер недоступен для другой находки. Проверено тестом «Исправить все».
- [x] Изменить выбранную ноду через Nemotron и сверить сохранённый граф. В браузере отдельно проверено открытие истории на экране шириной 390 пикселей и применение без повторного обращения к модели.
- [x] Открыть палитру кнопкой «+» под выбранной нодой, добавить следующую ноду с автоматической связью и запустить граф. Проверено в Chromium.
