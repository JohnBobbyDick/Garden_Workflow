# Ноды AI Security Workflow

> Файл сгенерирован `scripts/gen_nodes_doc.py` из реестра нод (`make nodes-doc`). Не редактируйте вручную.

## Как устроены ноды

Нода — один класс-плагин в одном файле внутри `backend/app/nodes/**`, помеченный `@register_node`. Реестр находит
модули автоматически; движок, API (`GET /api/nodes`) и редактор (форма строится из `config_schema`) менять не нужно.

```python
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class Shout(BaseNode):
    type = "logic.shout"
    category = "logic"
    title = {"ru": "Крик", "en": "Shout"}
    description = {"ru": "Переводит текст в верхний регистр", "en": "Upper-cases text"}
    inputs = [Port("in", "text")]
    outputs = [Port("out", "text")]
    config_schema = obj({"suffix": prop("string", "Суффикс", "Suffix", default="!")})

    async def execute(self, ctx, inputs, config):
        text = inputs["in"].data["text"].upper() + config["suffix"]
        return {"out": Envelope.make("text", {"text": text}, ctx.node_id, "готово")}
```

### Данные между нодами

Каждое ребро передаёт конверт `Envelope`:

```json
{"type": "findings", "data": {"findings": [...]}, "meta": {"node_id": "sast", "produced_at": "…", "summary": "найдено 5"}}
```

| Тип порта | Содержимое `data` |
|---|---|
| `trigger` | параметры запуска: `trigger_type`, `source` (переопределение источника из CI/вебхука), событие |
| `repo` | `root` (рабочая копия), `files`, `loc`, `source` (`mode`, `url`, `ref`, `commit`), `project_name`, `diff_context` |
| `findings` | `findings[]` — единая модель `Finding` (секреты только маскированные) |
| `report` | `artifacts[]` (имя, ссылка, тип), `summary`, `exported` |
| `json` | произвольный объект (вердикт gate/diff, значения `set_value`, результат regex) |
| `text` | `text` |
| `bool` | `value` |
| `any` | принимает/отдаёт любой тип |

Совместимость: тип выхода должен совпадать с типом входа, `any` совместим со всем. Вход с `multiple` принимает
несколько рёбер (например, `logic.merge`). У IF/ELSE активна только одна ветка: невыбранная ветка и всё, что
зависит только от неё, получают статус `skipped`; нода-слияние ждёт только активные входы.

### Выражения `logic.if_else`

Собственный безопасный парсер (без `eval`): `findings.count`, `severity.max`, `severity.critical|high|medium|low`,
`category`/`categories`, `classes`, `new_findings.count`, `existing_findings.count`, `verdict`, `gate`,
`score.value`, `score.delta`, `data.<поле>` (JSON-входы). Операторы: `== != > >= < <= in contains`, `and or not`,
скобки. Уровни критичности сравниваются по рангу: `severity.max >= HIGH`.

### Шаблоны сообщений

`{{findings.count}}`, `{{severity.critical}}`, `{{new_findings.count}}`, `{{verdict}}`, `{{score.value}}`,
`{{score.delta}}`, `{{run.url}}`, `{{ai.summary}}`, `{{project.name}}`, `{{workflow.name}}` — только подстановка
значений из подготовленного контекста; значения секретов в контекст не попадают, результат дополнительно маскируется.

## Каталог

- **Триггеры**: `trigger.manual`, `trigger.schedule`, `trigger.webhook`
- **Источник кода**: `source.repo`
- **Сканеры**: `scanner.sast`, `scanner.sca`, `scanner.secrets`
- **Логика**: `logic.compare`, `logic.if_else`, `logic.merge`, `logic.regex`, `logic.set_value`, `logic.severity_filter`
- **AI**: `ai.report`
- **Вывод**: `output.ci_gate`, `output.report_export`
- **Уведомления**: `notify.smtp`, `notify.telegram`, `notify.webhook`

## Триггеры

### `trigger.manual` — Ручной запуск

Запуск сценария кнопкой «Запустить» в редакторе или через API.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `out` (Старт) | выход | `trigger` | — | — |

Параметров нет.

### `trigger.schedule` — По расписанию

Запуск по cron-выражению или ежедневно в заданное время (часовой пояс настраивается).

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `out` (Старт) | выход | `trigger` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `cron` | string |  | Cron-выражение. Например «0 14 * * *» — каждый день в 14:00 |
| `daily_at` | string |  | Каждый день в (ЧЧ:ММ) |
| `timezone` | string |  | Часовой пояс. Пусто — часовой пояс рабочего пространства |

### `trigger.webhook` — Webhook / CI

Запуск из GitHub/GitLab (push, pull/merge request) по подписанному вебхуку или из CI через API.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `out` (Событие) | выход | `trigger` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `provider` | github \| gitlab \| ci | "github" | Провайдер |
| `secret` | credential |  | Секрет вебхука. Для проверки подписи X-Hub-Signature-256 / X-Gitlab-Token (ссылка на секрет хранилища) |
| `events` | array<push / pull_request / merge_request> | ["push", "pull_request", "merge_request"] | События |
| `branches` | array<string> | [] | Ветки (пусто — все) |
| `repo_url` | string |  | Репозиторий (из allowlist). Событие принимается только для этого репозитория |

## Источник кода

### `source.repo` — Исходный код

Готовит проверяемый код: загруженный архив, git-репозиторий из allowlist или каталог внутри разрешённых корней. Код никогда не исполняется.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Старт) | вход | `trigger` | да | нет |
| `out` (Код) | выход | `repo` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `mode` | project \| upload \| git_url \| path | "project" | Источник. project — источник из настроек проекта запуска |
| `git_url` | string |  | Git URL (https, из allowlist) |
| `ref` | string |  | Ветка / тег / commit |
| `path` | string |  | Путь (внутри APP_SCAN_ROOTS) |
| `upload_id` | string |  | Загруженный архив |
| `subdir` | string |  | Подкаталог проекта. Корень проверки внутри репозитория, например training-project |
| `access_token` | credential |  | Токен доступа (приватный репозиторий) (ссылка на секрет хранилища) |

## Сканеры

### `scanner.sast` — SAST Kotlin / Spring

Собственный статический анализ Kotlin/Spring Boot на tree-sitter: taint, граф вызовов по DI, правила Spring Security (SQLi, TLS, CORS, маршруты, IDOR и др.).

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Код) | вход | `repo` | да | нет |
| `out` (Находки) | выход | `findings` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `disabled_rules` | array<sql-injection / tls-verification / credentialed-cors / route-authorization / object-authorization / hardcoded-credentials / unsafe-deserialization / path-traversal / weak-crypto / missing-input-validation / insecure-endpoint / csrf-disabled> | [] | Отключённые правила |
| `min_confidence` | number | 0.0 | Минимальная уверенность |
| `include` | array<string> | [] | Включить (glob) |
| `exclude` | array<string> | [] | Исключить (glob) |

### `scanner.sca` — Проверка зависимостей (SCA)

Собственный разбор Gradle (Kotlin DSL, Groovy, version catalog, gradle.properties, lockfile) и сверка с локальным справочником уязвимостей; CVSS считается собственным калькулятором.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Код) | вход | `repo` | да | нет |
| `out` (Находки) | выход | `findings` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `database_path` | string |  | Справочник уязвимостей (JSON). Пусто — встроенный справочник организаторов |
| `include_transitive` | boolean | false | Транзитивные зависимости. Записи lockfile без явного объявления |
| `include_test_scopes` | boolean | true | Тестовые конфигурации |

### `scanner.secrets` — Поиск секретов

Собственный детектор: сигнатуры токенов, контекст имён, разрешение констант Kotlin (AST), fallback-значения, энтропия. Значения маскируются.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Код) | вход | `repo` | да | нет |
| `out` (Находки) | выход | `findings` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `include` | array<string> | [] | Включить (glob) |
| `exclude` | array<string> | [] | Исключить (glob) |
| `entropy_threshold` | number | 4.0 | Порог энтропии |
| `heuristics` | boolean | true | Эвристика неизвестных секретов |

## Логика

### `logic.compare` — Сравнение

Сравнивает два значения (числа, строки, уровни критичности): путь к данным или литерал.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Данные) | вход | `any` | нет | нет |
| `result` (Результат) | выход | `bool` | — | — |
| `true` (Да) | выход | `any` | — | — |
| `false` (Нет) | выход | `any` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `left` | string |  | Слева. Путь (findings.count, data.x) или значение **обязательный** |
| `operator` | == \| != \| > \| >= \| < \| <= \| in \| contains | "==" | Оператор **обязательный** |
| `right` | string |  | Справа. Путь или значение **обязательный** |

### `logic.if_else` — Условие IF/ELSE

Ветвление по выражению: findings.count, severity.max, category, new_findings.count, verdict, score.value, score.delta; сравнения и and/or/not. Данные входа передаются в выбранную ветку.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Данные) | вход | `any` | да | нет |
| `true` (Да) (ветка) | выход | `any` | — | — |
| `false` (Нет) (ветка) | выход | `any` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `expression` | string |  | Условие. Например: severity.max >= HIGH and findings.count > 0 **обязательный** |

### `logic.merge` — Объединение находок

Объединяет несколько наборов находок и убирает дубликаты (одна проблема — одна находка).

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Находки) | вход | `findings` | да | да |
| `out` (Все находки) | выход | `findings` | — | — |

Параметров нет.

### `logic.regex` — Регулярное выражение

match — есть ли совпадение; extract — извлечь совпадения; filter — оставить находки/строки, поле которых совпадает. Таймаут и лимит длины защищают от катастрофического бэктрекинга.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Данные) | вход | `any` | да | нет |
| `out` (Результат) | выход | `any` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `pattern` | string |  | Шаблон **обязательный** |
| `flags` | string | "" | Флаги (i, m, s) |
| `field` | string | "path" | Поле. Для находок: path, class, title, description, snippet… |
| `mode` | match \| extract \| filter | "match" | Режим |
| `timeout_ms` | integer | 500 | Таймаут, мс |

### `logic.set_value` — Задать значения

Создаёт JSON со значениями (переменные для условий и шаблонов); объединяется с JSON-входом.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Данные) | вход | `any` | нет | нет |
| `out` (Значения) | выход | `json` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `values` | object | {} | Значения |

### `logic.severity_filter` — Фильтр по критичности

Оставляет находки не ниже заданной критичности и выбранных категорий/классов.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Находки) | вход | `findings` | да | нет |
| `out` (Отфильтровано) | выход | `findings` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `min_severity` | LOW \| MEDIUM \| HIGH \| CRITICAL | "LOW" | Минимальная критичность |
| `categories` | array<SECRET / SCA / SAST> | [] | Категории (пусто — все) |
| `classes` | array<string> | [] | Классы (пусто — все) |
| `min_confidence` | number | 0.0 | Минимальная уверенность |

## AI

### `ai.report` — AI-объяснение

LLM объясняет уже найденные анализаторами проблемы простым языком, оценивает последствия и предлагает исправления (diff). Ответ проходит валидатор достоверности; без AI — детерминированный отчёт с пометкой.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Находки) | вход | `findings` | да | нет |
| `out` (AI-отчёт) | выход | `report` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `provider` |  \| openai_compat \| ollama | "" | Провайдер (пусто — из настроек workspace) |
| `base_url` | string |  | Base URL провайдера |
| `model` | string |  | Модель |
| `api_key` | credential |  | API-ключ провайдера (ссылка на секрет хранилища) |
| `language` | auto \| ru \| en | "auto" | Язык отчёта. auto — язык интерфейса пользователя |
| `generate_fix_diff` | boolean | true | Предлагать исправления (diff) |
| `fallback_to_deterministic` | boolean | true | Отчёт без AI при недоступности LLM |
| `max_findings` | integer | 60 | Максимум находок для AI |

## Вывод

### `output.ci_gate` — CI gate

Итоговый статус для CI: fail при находках не ниже fail_on (по умолчанию CRITICAL). С входом verdict от diff-aware сканирования учитываются только новые находки.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Находки) | вход | `findings` | да | нет |
| `verdict` (Вердикт diff) | вход | `json` | нет | нет |
| `out` (Gate) | выход | `json` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `fail_on` | CRITICAL \| HIGH \| MEDIUM \| LOW \| none | "CRITICAL" | Падать при |

### `output.report_export` — Экспорт отчёта

Формирует submission.json (официальный формат, проверяется валидатором), report.md и report.html из одного набора находок и сохраняет их в артефакты запуска.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Находки) | вход | `findings` | да | нет |
| `ai` (AI-отчёт) | вход | `report` | нет | нет |
| `out` (Отчёт) | выход | `report` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `formats` | array<submission_json / markdown / html> | ["submission_json", "markdown", "html"] | Форматы |
| `min_confidence` | number | 0.6 | Порог уверенности |
| `include_transitive` | boolean | false | Включать транзитивные SCA |

## Уведомления

### `notify.smtp` — Письмо (SMTP)

HTML-письмо со сводкой и таблицей находок, вложения report.html и report.md. TLS / STARTTLS.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Данные) | вход | `any` | да | да |
| `out` (Статус) | выход | `json` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `host` | string |  | SMTP-сервер **обязательный** |
| `port` | integer | 587 | Порт |
| `security` | starttls \| tls \| none | "starttls" | Шифрование |
| `username` | string |  | Пользователь |
| `password` | credential |  | Пароль (ссылка на секрет хранилища) |
| `from_addr` | string |  | От кого **обязательный** |
| `to` | array<string> |  | Кому **обязательный** |
| `subject` | string | "AI Security Workflow: {{findings.count}} находок ({{workflow.name}})" | Тема |
| `template` | string |  | Шаблон текста |

### `notify.telegram` — Уведомление в Telegram

Сводка (критичность, главные находки, score, вывод AI) и файл report.md через Bot API. Длинные сообщения режутся по лимиту 4096 символов.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Данные) | вход | `any` | да | да |
| `out` (Статус) | выход | `json` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `bot_token` | credential |  | Токен бота (ссылка на секрет хранилища) **обязательный** |
| `chat_id` | string |  | Chat ID **обязательный** |
| `template` | string |  | Шаблон сообщения. Подстановки: {{findings.count}}, {{severity.critical}}, {{score.value}}, {{run.url}}… |
| `send_document` | boolean | true | Прикладывать report.md |

### `notify.webhook` — HTTP Webhook

JSON со сводкой, маскированными находками и ссылками на экспорт; подпись HMAC-SHA256; защита от SSRF.

| Порт | Направление | Тип | Обязательный | Несколько |
|---|---|---|---|---|
| `in` (Данные) | вход | `any` | да | да |
| `out` (Статус) | выход | `json` | — | — |

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `url` | string |  | URL **обязательный** |
| `method` | POST \| PUT | "POST" | Метод |
| `headers` | object | {} | Заголовки |
| `secret_headers` | object | {} | Секретные заголовки (из хранилища) |
| `hmac_secret` | credential |  | Секрет подписи HMAC (ссылка на секрет хранилища) |
| `body_template` | string |  | Шаблон тела (пусто — JSON по умолчанию) |
