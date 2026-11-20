# Безопасность платформы

Платформа работает с чужим кодом и чужими секретами. Ниже — модель угроз, механизмы защиты и тесты, которые их
проверяют.

## Модель угроз

| Угроза | Защита | Где | Тест |
| --- | --- | --- | --- |
| Утечка найденного секрета в БД, API, события, логи, отчёты, уведомления, промпты | Маскирование `ab…(len=N)` + отпечаток `sha256:<8hex>:<len>` на всех выходах; лог-фильтр на корневых и uvicorn-логгерах | `core/masking.py`, `main.py::_install_log_masking` | `tests/security/test_platform_security.py::test_injected_secret_never_appears_in_db_api_events_logs` (тест-канарейка) |
| Утечка сохранённых credential | AES-256-GCM, версия ключа в шифртексте, ротация `APP_MASTER_KEY="1:old,2:new"`; API возвращает только `••••` + хвост; значения загружаются в маскировщик при старте | `core/crypto.py`, `engine/services.py::preload_credentials` | `test_masker_knows_stored_credentials_after_restart`, `tests/unit/test_core_crypto_masking.py` |
| SSRF через вебхуки, LLM, SCM-API | Только http/https; все адреса из DNS должны быть публичными (loopback, private, link-local, metadata, CGNAT блокируются); соединение с проверенным IP (защита от DNS rebinding); каждый редирект проверяется; явный `APP_SSRF_ALLOW_HOSTS` | `core/ssrf.py` | `tests/unit/test_ssrf.py` |
| Сканирование чужого / произвольного кода | Allowlist репозиториев (точное совпадение URL, только https), `path` только внутри `APP_SCAN_ROOTS`, архивы только от пользователя | `core/repo_guard.py` | `test_allowlist_rules`, `test_path_source_outside_scan_roots_rejected` |
| Запись в чужой репозиторий | Запись (статусы, комментарии, PR) только при `allow_write` + токене; для репозитория организаторов и фикстур запрет зашит в коде (`is_readonly_repo`, `is_readonly_path`) | `core/repo_guard.py`, `ci/status.py`, `autofix/pull_request.py` | `test_allowlist_rules`, `tests/api/test_autofix_api.py` (403-кейсы) |
| Опасный git | Список аргументов (без shell), `GIT_ALLOW_PROTOCOL=https`, без prompt и hooks, shallow, тайм-аут, проверка ref/sha; токен через заголовок, не в URL | `core/repo_guard.py::git_env`, `clone_repo` | `tests/unit/test_repo_guard.py` |
| Zip-бомба и path traversal в архивах | Без абсолютных путей, `..`, ссылок и устройств; лимиты числа файлов и распакованного размера проверяются по ходу потока, а не по заголовкам | `core/repo_guard.py::safe_extract` | `tests/unit/test_repo_guard.py` |
| Выполнение кода проекта | Анализаторы только читают файлы (tree-sitter, свои парсеры Gradle). Gradle, скрипты и тесты проекта не запускаются | `app/analyzers/**` | `test_analyzers_never_execute_project_code` |
| IDOR между workspace | Каждый объект загружается через `load_scoped` (workspace + роль); чужой объект → `404` | `app/deps.py` | `test_idor_matrix` |
| Повышение привилегий | Роли `viewer` < `developer` < `admin`; последнего admin нельзя понизить или удалить; изменения allowlist, `allow_write`, секретов и score — только admin и с записью в аудит | `api/workspaces.py`, `core/audit.py` | `test_invitation_flow_and_roles`, `test_last_admin_cannot_be_demoted_or_removed` |
| Подбор пароля, кража сессии | argon2; access JWT 15 мин; refresh 14 дней с ротацией, повторное использование отзывает всю цепочку; rate limit 10 входов/мин на (IP, e-mail) | `core/security.py`, `api/auth.py` | `test_login_rate_limit`, `tests/api/test_api_core.py` |
| Поддельный вебхук | HMAC `X-Hub-Signature-256` (GitHub) / `X-Gitlab-Token`, сравнение за постоянное время; идемпотентность по delivery id | `api/webhooks.py` | `tests/ci/test_ci.py` |
| Инъекции в выражениях и шаблонах | Собственный парсер выражений без `eval`; шаблоны — только подстановка `{{path}}` из подготовленного контекста без секретов | `engine/expressions.py`, `engine/templating.py` | `tests/engine/test_expressions_templates.py` |
| Галлюцинации LLM | Валидатор: id, файлы и строки, CVE, версии; AutoFix — самопроверка анализаторами | `ai/validator.py`, `autofix/validator.py` | см. [AI.md](AI.md) |
| Prompt injection из кода проекта | LLM ничего не решает: её ответ не меняет находки, вердикт и score; AutoFix-патч применяется только после 7 проверок, PR без auto-merge | `ai/`, `autofix/` | `tests/api/test_autofix_api.py` |
| CORS, размер запроса | CORS только для `APP_CORS_ORIGINS`; лимит тела 60 МБ; nginx: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` | `main.py`, `docker/nginx.conf` | `test_cors_only_for_configured_origins`, `test_body_size_limit` |

## Хранение

- **Архивы** хранятся зашифрованными и удаляются после `APP_UPLOAD_RETENTION_HOURS`; воркер чистит их каждые 30 с.
- **Рабочие копии** — временные каталоги, удаляются после запуска.
- **Содержимое файлов в БД не хранится.** AutoFix сохраняет только маскированное предложение и для PR повторно
  применяет его к заново восстановленным исходникам.
- **Ключи.** В `APP_ENV=prod` обязательны `APP_MASTER_KEY` и `APP_JWT_SECRET`. В `dev` они генерируются один раз в
  том данных (только для демо).
- **Репозиторий.** `.env` и ключи в него не попадают, есть только `.env.example`. Docker-образ собирается без `.env`
  (`.dockerignore`).

## Проверка

```bash
cd backend && .venv/bin/pytest -q tests/security tests/unit/test_ssrf.py tests/unit/test_repo_guard.py
```

## Честные ограничения

- Rate limit входа хранится в памяти процесса. При нескольких экземплярах API он считается для каждого отдельно.
- `X-Forwarded-For` не доверяется (uvicorn принимает его только от `FORWARDED_ALLOW_IPS`, по умолчанию localhost), nginx
  перезаписывает его, а не дописывает. Порт backend опубликован только на `127.0.0.1`. За nginx все клиенты видны
  backend с одного адреса, поэтому лимит фактически действует на e-mail. Чтобы считать его по реальному IP клиента,
  задайте `FORWARDED_ALLOW_IPS` = адрес nginx в сети Compose.
- В `dev` ключи лежат в томе рядом с данными. Для продакшна задайте их через секреты оркестратора.
- TLS терминируется вне Compose (обратный прокси или балансировщик). В Compose — HTTP на localhost.
