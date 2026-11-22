# API

Справочник сгенерирован из OpenAPI-схемы приложения (`make api-doc`). Интерактивная документация — `GET /docs`
(Swagger UI) и `GET /openapi.json` на запущенном backend.

## Общие правила

- Базовый путь `/api`. Формат — JSON (UTF-8). Экспорт и `.patch` — текст или файл.
- **Аутентификация:** `Authorization: Bearer <access JWT>` (15 мин). Обновление — `POST /api/auth/refresh`
  с refresh-токеном (ротация, отзыв при выходе). Для CI — API-токены workspace (`/api/api-tokens`), передаются так же.
- **Workspace:** ресурсы принадлежат workspace. Список-эндпоинты принимают `?workspace_id=`; по умолчанию —
  личный workspace пользователя. Чужой объект → `404` (не раскрываем существование).
- **Роли:** `viewer` (чтение), `developer` (сценарии, запуски, AutoFix, использование секретов без чтения значений),
  `admin` (участники, настройки, секреты, allowlist, параметры score).
- **Ошибки:** всегда `{"error": {"code": "...", "message": "...", "details": ...}}`; `message` — по-русски,
  `code` — стабильный машинный код (`validation_error`, `not_found`, `forbidden`, `invalid_graph`,
  `ai_not_configured`, `write_forbidden`, …).
- **Живые события запуска:** `GET /api/runs/{id}/events` — Server-Sent Events (`node.status`, `node.log`,
  `edge.data`, `run.status`, …); при переподключении передайте `Last-Event-ID`.
- **Секреты** никогда не возвращаются: только `••••` + последние символы; во всех ответах работает маскирование.
- **CI-вердикт:** `GET /api/v1/ci/runs/{id}/verdict` — `200` PASS, `422` FAIL, `409` запуск не завершён.

## Эндпоинты


### Здоровье

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/healthz` | проверка живости (используется healthcheck Compose) |

### Аутентификация

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/auth/login` | вход (rate limit по IP+e-mail) |
| `POST` | `/api/auth/logout` | выход, отзыв refresh-токена |
| `GET` | `/api/auth/me` | текущий пользователь и его workspace |
| `PATCH` | `/api/auth/me` | имя, язык, тема |
| `POST` | `/api/auth/refresh` | ротация refresh-токена |
| `POST` | `/api/auth/register` | проверяет одноразовый код и создаёт аккаунт с личным workspace, возвращает access/refresh |
| `POST` | `/api/auth/registration-code` | отправляет на e-mail одноразовый код регистрации на 10 минут |

### Рабочие пространства и участники

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/invitations/accept` | принять приглашение |
| `GET` | `/api/workspaces` | workspace пользователя |
| `POST` | `/api/workspaces` | создать workspace |
| `GET` | `/api/workspaces/{workspace_id}` | карточка workspace |
| `PATCH` | `/api/workspaces/{workspace_id}` | переименовать, язык по умолчанию (admin) |
| `GET` | `/api/workspaces/{workspace_id}/audit` | журнал аудита (admin) |
| `GET` | `/api/workspaces/{workspace_id}/members` | участники и роли |
| `POST` | `/api/workspaces/{workspace_id}/members` | пригласить участника (admin) |
| `DELETE` | `/api/workspaces/{workspace_id}/members/{user_id}` | исключить участника (admin) |
| `PATCH` | `/api/workspaces/{workspace_id}/members/{user_id}` | сменить роль (admin) |

### Хранилище секретов

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/credentials` | список секретов (значения не возвращаются, только маска) |
| `POST` | `/api/credentials` | сохранить секрет (AES-256-GCM) |
| `DELETE` | `/api/credentials/{credential_id}` | удалить секрет |
| `PUT` | `/api/credentials/{credential_id}` | заменить значение/имя |
| `POST` | `/api/credentials/{credential_id}/telegram-chat` | находит ID личного чата по имени в недавних сообщениях бота |

### Настройки (allowlist)

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/settings/allowlist` | allowlist репозиториев (+ встроенный read-only репозиторий организаторов) |
| `PUT` | `/api/settings/allowlist` | изменить allowlist, `allow_write` (admin, аудит; для репозитория организаторов запрещено) |

### Проекты и загрузки

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/projects` | проекты |
| `POST` | `/api/projects` | создать проект (upload / git_url / path) |
| `DELETE` | `/api/projects/{project_id}` | удалить проект |
| `GET` | `/api/projects/{project_id}` | проект |
| `PATCH` | `/api/projects/{project_id}` | изменить проект |
| `POST` | `/api/uploads` | загрузить архив (zip/tar.gz; шифруется, TTL `APP_UPLOAD_RETENTION_HOURS`) |

### Каталог нод

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/nodes` | каталог нод: порты, JSON Schema параметров, описания RU/EN |
| `GET` | `/api/nodes/custom` | список пользовательских нод рабочего пространства |
| `POST` | `/api/nodes/custom` | создание именованной ноды преобразования JSON в рабочем пространстве |

### Сценарии и расписание

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/workflows` | сценарии |
| `POST` | `/api/workflows` | создать сценарий (граф валидируется) |
| `POST` | `/api/workflows/validate` | проверить черновик графа без сохранения |
| `DELETE` | `/api/workflows/{workflow_id}` | удалить сценарий |
| `GET` | `/api/workflows/{workflow_id}` | сценарий с графом |
| `PUT` | `/api/workflows/{workflow_id}` | сохранить граф/имя |
| `POST` | `/api/workflows/{workflow_id}/run` | запустить вручную (ставится в очередь воркера) |
| `GET` | `/api/workflows/{workflow_id}/schedule` | расписание (cron, часовой пояс) |
| `PUT` | `/api/workflows/{workflow_id}/schedule` | включить/изменить расписание |
| `POST` | `/api/workflows/{workflow_id}/validate` | проверить сохранённый граф |

### Запуски, находки, экспорт

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/runs` | история запусков с фильтрами |
| `GET` | `/api/runs/compare` | сравнение двух запусков (`?base=…&head=…`): новые / устранённые |
| `GET` | `/api/runs/{run_id}` | запуск: статусы нод, итоги, вердикт, score, артефакты |
| `GET` | `/api/runs/{run_id}/artifacts/{name}` | скачать артефакт (report.md/html, submission.json) |
| `POST` | `/api/runs/{run_id}/cancel` | отменить запуск |
| `GET` | `/api/runs/{run_id}/events` | живые события (SSE) |
| `GET` | `/api/runs/{run_id}/export/{fmt}` | экспорт: `submission.json`, `report.md`, `report.html` |
| `GET` | `/api/runs/{run_id}/findings` | находки запуска (маскированные сниппеты) |

### AI: провайдер, отчёты, генерация сценариев

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/ai/workflows/generate` | сценарий из текста (LLM строит граф, граф валидируется) |
| `GET` | `/api/ai/workflows/{workflow_id}/chat` | история чат-правок |
| `POST` | `/api/ai/workflows/{workflow_id}/chat` | предложить правку графа сообщением |
| `GET` | `/api/ai/workflows/{workflow_id}/chat/{msg_id}` | предпросмотр сохранённого предложения и проверка его актуальности |
| `POST` | `/api/ai/workflows/{workflow_id}/chat/{msg_id}/apply` | применить предложенную правку |
| `POST` | `/api/ai/workflows/{workflow_id}/chat/{msg_id}/reject` | отклонить правку |
| `GET` | `/api/runs/{run_id}/ai-report` | AI-отчёт с журналом валидатора |
| `GET` | `/api/settings/ai` | настройки AI-провайдера |
| `PUT` | `/api/settings/ai` | провайдер, base_url, модель, ключ (admin) |
| `POST` | `/api/settings/ai/diagnose` | диагностика LLM: по запросу через каждый прокси (для auto — по каждому протоколу) и напрямую; OK/FAIL, время, причина без секретов |
| `GET` | `/api/settings/ai/models` | список моделей провайдера |
| `POST` | `/api/settings/ai/test` | проверка соединения с LLM |

### Библиотека шаблонов

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/templates` | библиотека шаблонов: поиск, фильтры, сортировка |
| `POST` | `/api/templates` | опубликовать шаблон |
| `GET` | `/api/templates/{tid}` | шаблон |
| `PUT` | `/api/templates/{tid}` | обновить свой шаблон (новая версия) |
| `DELETE` | `/api/templates/{tid}/favorite` | убрать из избранного |
| `POST` | `/api/templates/{tid}/favorite` | в избранное |
| `POST` | `/api/templates/{tid}/hide` | скрыть шаблон (модерация) |
| `POST` | `/api/templates/{tid}/rate` | оценка 1–5 |
| `GET` | `/api/templates/{tid}/reviews` | отзывы |
| `POST` | `/api/templates/{tid}/reviews` | оставить отзыв |
| `DELETE` | `/api/templates/{tid}/reviews/{rid}` | удалить отзыв |
| `PUT` | `/api/templates/{tid}/reviews/{rid}` | изменить отзыв |
| `POST` | `/api/templates/{tid}/use` | создать сценарий из шаблона |

### CI/CD: токены, CLI, YAML, запуски из пайплайна

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/api-tokens` | API-токены для CI |
| `POST` | `/api/api-tokens` | выпустить токен (значение показывается один раз) |
| `DELETE` | `/api/api-tokens/{token_id}` | отозвать токен |
| `GET` | `/api/ci/cli` | скачать CLI `aisw_ci.py` (stdlib-only) |
| `GET` | `/api/ci/webhooks/status` | последние доставки вебхуков и отправленные статусы |
| `GET` | `/api/ci/yaml` | сгенерировать GitHub Actions / GitLab CI YAML |
| `POST` | `/api/v1/ci/runs` | запуск из пайплайна (архив + diff-контекст) |
| `GET` | `/api/v1/ci/runs/{run_id}` | статус запуска |
| `GET` | `/api/v1/ci/runs/{run_id}/report` | отчёт для артефакта CI |
| `GET` | `/api/v1/ci/runs/{run_id}/verdict` | вердикт: 200 PASS / 422 FAIL |

### Вебхуки GitHub/GitLab

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/v1/webhooks/github` | вебхук GitHub (HMAC `X-Hub-Signature-256`, идемпотентность по delivery id) |
| `POST` | `/api/v1/webhooks/gitlab` | вебхук GitLab (`X-Gitlab-Token`) |

### Security Score и дашборд

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/dashboard` | дашборд за период `7d` / `30d`: проверки, открытые/блокирующие находки, проверенные патчи, по типам и уровням, история запусков, Security Score, тренд, топ-3, AI-план |
| `GET` | `/api/projects/{project_id}/score/history` | история score, маркеры, тренд (7d/30d/90d) |
| `GET` | `/api/runs/{run_id}/score` | score запуска: разбивка штрафа, Priority Fix List, AI-план |
| `POST` | `/api/runs/{run_id}/sprint-plan` | AI-план на спринт (с валидацией чисел; без LLM — детерминированный) |
| `GET` | `/api/settings/score` | параметры формулы score |
| `PUT` | `/api/settings/score` | переопределить параметры (admin) |

### AI AutoFix

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/autofix/coverage` | покрытие правил AutoFix из метаданных |
| `GET` | `/api/autofixes/{autofix_id}` | исправление + доступность PR |
| `GET` | `/api/autofixes/{autofix_id}/patch` | скачать маскированный `.patch` |
| `POST` | `/api/autofixes/{autofix_id}/pull-request` | создать/обновить PR/MR (только `allow_write`, иначе 403) |
| `POST` | `/api/autofixes/{autofix_id}/recheck` | «Повторная проверка»: запуск сценария на копии проекта с применённым проверенным патчем (новый run, 202) |
| `GET` | `/api/runs/{run_id}/autofixes` | исправления запуска |
| `POST` | `/api/runs/{run_id}/findings/{finding_id}/autofix` | сгенерировать и проверить исправление (чеклист) |

### demo

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/demo/setup` | «Демо-данные»: идемпотентно создать демо-проект на учебном наборе и сценарий «Проверка перед merge» |
| `GET` | `/api/demo/training` | путь учебного набора организаторов (для «Источник проверки → Учебный проект») |

### repos

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/repos/attest` | «Это учебный / собственный проект»: публичный https-репозиторий добавляется в allowlist пространства (только чтение) с записью в аудит; приватные адреса отклоняются |

### checks

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/checks` | «Новая проверка» одним запросом: источник (ссылка / архив / учебный проект) + старт (готовый сценарий, шаблон, пустой граф или текст для AI); незаполненные параметры уведомлений возвращаются в needs_input |
| `GET` | `/api/checks/starters` | готовые сценарии для «С чего начать?»: полная проверка, только секреты, проверка PR |

Всего операций: 107.
