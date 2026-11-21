# Рабочее пространство «конструктор в центре» + внешние LLM через прокси — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переделать интерфейс в одно рабочее пространство вокруг холста: путь «ссылка на репозиторий → запуск» за ≤ 3 действия, неоновые анимации выполнения. Плюс подключение внешних LLM API (Gemini и любых OpenAI-совместимых) через пул ключей, прокси и ретраи.

**Architecture:** Backend: пул ключей/прокси/моделей встраивается в базовый класс провайдера (`app/ai/providers/base.py`) поверх существующего `_request`; новый провайдер `gemini`; SSRF-обёртка получает режим прокси; два новых эндпоинта (`/repos/attest`, `/checks`). Frontend: новый каркас `Workspace` (левая колонка, холст, правый инспектор, выдвижные панели) переиспользует существующие компоненты редактора, страниц и API-хуки; старые маршруты перенаправляются.

**Tech Stack:** FastAPI, SQLAlchemy, httpx (+`socksio` через `httpx[socks]`), pydantic-settings; React 18, TypeScript, `@xyflow/react` v13, TanStack Query, Zustand, Tailwind, i18next; pytest, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-21-workspace-redesign-design.md` (разделы 1–13). Исходная схема ретраев — `LLM_PROXY.md`.

## Global Constraints

- Не коммитить: шаги «Commit» заменены проверкой `git status`; коммитит пользователь.
- Никаких заглушек, моков в продуктовом коде и имитаций результатов; LLM только объясняет.
- Секреты (ключи, пароли прокси, токены) маскируются везде: логи, API, ошибки, БД, UI. Ключ LLM — только в заголовке, не в URL.
- Фикстуры организаторов и `github.com/TBagirov/training` — только чтение (`is_readonly_repo`).
- `@xyflow/react` v13: `changes.applyTo(nodes)`, нет `applyNodeChanges`, нет `colorMode`.
- UI: RU по умолчанию + EN, паритет ключей (тест `src/i18n/i18n.test.ts`).
- Окружение LLM — имена как в `LLM_PROXY.md`: `LLM_ENABLED`, `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_KEYS_COUNT`, `GEMINI_MODEL` (по умолчанию `gemini-2.5-flash`), `GEMINI_FALLBACK_MODELS` (`gemini-2.5-flash,gemini-2.5-flash-lite`), `GEMINI_MAX_RETRIES`, `GEMINI_PROXIES`, `GEMINI_PROXY_SCHEME` (`auto`), `GEMINI_PROXY_PORT`, `GEMINI_BASE_URL` (`https://generativelanguage.googleapis.com/v1beta`), `OLLAMA_URL` (`http://localhost:11434`), `OLLAMA_MODEL`.
- Ретраи: авто-число `min(max(ключей, кандидатов, 3), 6)` (auto-прокси = 2 кандидата); паузы 2, 4, 6, 8, 10 с; connect-таймаут `min(timeout, 10)`; жёсткий дедлайн `timeout + 5`; кэш протокола прокси 600 с; сниффинг по 3 с.
- Анимации: только CSS (`@property`, `conic-gradient`, `@keyframes`, `transform`/`opacity`); `prefers-reduced-motion: reduce` → статика.
- Маршрут `/runs/:id` обязан работать (ссылки из уведомлений, CI, `report.html`).

## Review Focus

1. Пароль прокси с `:`, `@`, `#` → разбирается (всё после 3-го двоеточия — пароль), percent-кодируется, нигде не всплывает в ошибках/логах — тест в Task A1 и A4.
2. Жюри вставляет `https://github.com/org/repo.git`, `…/tree/main`, `http://…` или URL с пробелами → нормализация или понятная ошибка, а не 500 — тест в Task B1.
3. «Запустить» нажато, пока автосохранение ещё не отправлено → запускается актуальный граф (сохранение сбрасывается перед запуском) — тест в Task B4 (vitest на `useAutosave.flush`) и e2e B9.
4. Старые ссылки `/runs/{id}`, `/workflows/{id}`, `/pr`, `/templates` → открывают эквивалент в рабочем пространстве — vitest в Task B3 и e2e B9.
5. Все попытки LLM провалились (нет сети/прокси мёртв) → отчёт строится детерминированно, UI показывает причину без секретов — тест в Task A4.

---

## Часть A. Внешние LLM через прокси

### Task A1: Разбор окружения и прокси

**Files:**
- Create: `backend/app/ai/pool.py`
- Modify: `backend/pyproject.toml` (зависимость `httpx[socks]>=0.27`), `backend/.env.example` (переменные из Global Constraints с комментариями)
- Test: `backend/tests/ai/test_pool.py`

**Interfaces:**
- Produces:
  - `split_list(raw: str | None) -> list[str]` — разделители `,`, `;`, пробел; без пустых и дублей, порядок сохраняется.
  - `parse_proxy(entry: str, scheme: str = "auto", default_port: str | None = None) -> str | None` — `host:port:login:password` и `host:login:password` → `<scheme>://quote(login):quote(password)@host[:port]`; полный URL (`socks5://…`, `http://…`) — как есть; иначе `None`. При `scheme="auto"` результат `auto://…`.
  - `auto_retries(n_keys: int, proxies: list[str]) -> int`.
  - `mask_proxy(url: str) -> str` → `scheme://host:port`.
  - `class LLMEnv(BaseSettings)` (без префикса, `env_file="backend/.env"` относительно `BACKEND_DIR`, `extra="ignore"`): поля из Global Constraints; свойства `keys: list[str]` (с учётом `GEMINI_KEYS_COUNT`), `models: list[str]` (основная + фолбэки без дублей), `proxies: list[str]` (через `parse_proxy`), `retries: int`.
  - `get_llm_env() -> LLMEnv` (`lru_cache`).

- [ ] **Step 1: Тесты**

```python
def test_split_list_separators_and_dupes():
    assert split_list("a, b;c  a ,") == ["a", "b", "c"]

def test_parse_proxy_formats():
    assert parse_proxy("1.2.3.4:1080:user:p:a@ss#1", "socks5") == "socks5://user:p%3Aa%40ss%231@1.2.3.4:1080"
    assert parse_proxy("1.2.3.4:user:pw", "http", default_port="3128") == "http://user:pw@1.2.3.4:3128"
    assert parse_proxy("1.2.3.4:user:pw", "http") == "http://user:pw@1.2.3.4"
    assert parse_proxy("socks5://u:p@h:1", "http") == "socks5://u:p@h:1"
    assert parse_proxy("1.2.3.4:1080:u:p") == "auto://u:p@1.2.3.4:1080"
    assert parse_proxy("garbage") is None

def test_auto_retries_formula():
    assert auto_retries(1, []) == 3
    assert auto_retries(2, ["auto://a", "auto://b"]) == 4
    assert auto_retries(9, []) == 6

def test_env_models_and_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k1,k2,k3"); monkeypatch.setenv("GEMINI_KEYS_COUNT", "2")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    env = LLMEnv(_env_file=None)
    assert env.keys == ["k1", "k2"]
    assert env.models == ["gemini-2.5-flash-lite", "gemini-2.5-flash"]

def test_mask_proxy_hides_credentials():
    assert mask_proxy("socks5://u:secret@h:1080") == "socks5://h:1080"
```

- [ ] **Step 2:** `cd backend && .venv/Scripts/pytest tests/ai/test_pool.py -q` → FAIL (модуля нет).
- [ ] **Step 3:** Реализовать `pool.py`; `uv pip install -e ".[dev]"` после правки зависимостей.
- [ ] **Step 4:** Тот же запуск → PASS; `ruff check app tests`.
- [ ] **Step 5:** `git status` — изменения на месте, без коммита.

### Task A2: Автоопределение протокола прокси

**Files:**
- Create: `backend/app/ai/proxy_scheme.py`
- Test: `backend/tests/ai/test_proxy_scheme.py` (локальные asyncio-серверы: «SOCKS5» отвечает `05 00`, «HTTP» отвечает `HTTP/1.1 407`, «немой» молчит)

**Interfaces:**
- Consumes: формат `auto://…` из A1.
- Produces:
  - `CACHE_TTL = 600`, `ORDER = ("http", "socks5", "https")`.
  - `async sniff(host: str, port: int, timeout: float = 3.0) -> str | None` — шлёт `05 01 00`: первый байт `0x05` → `"socks5"`, ответ `HTTP/` → `"http"`; иначе новое соединение с `CONNECT generativelanguage.googleapis.com:443 HTTP/1.1\r\n\r\n` → `HTTP/` → `"http"`; иначе `None`. Логин/пароль не отправляются.
  - `async resolve(url: str, tried: set[str]) -> str` — для `auto://` возвращает URL с конкретной схемой; правила: кэш (если не в `tried`) → sniff (если не в `tried`) → первый из `ORDER` не в `tried` → если всё опробовано, `tried.clear()` и заново. Добавляет выбранную схему в `tried`. Для не-`auto` — URL без изменений.
  - `remember(concrete_url: str) -> None`, `forget(concrete_url: str) -> None`, `clear_cache() -> None` (для тестов).

- [ ] **Step 1: Тесты:** `test_sniff_detects_socks5`, `test_sniff_detects_http`, `test_sniff_silent_returns_none` (таймаут 0.3), `test_resolve_uses_cache_then_falls_through_order` (после `remember("socks5://u:p@h:1")` первый `resolve` даёт socks5 без сети; при `tried={"socks5"}` и немом порте → `http`, затем `https`), `test_forget_drops_cache`, `test_sniff_never_sends_credentials` (сервер записывает все полученные байты; в них нет `u`/`p`).
- [ ] **Step 2:** pytest → FAIL.
- [ ] **Step 3:** Реализовать на `asyncio.open_connection`; кэш `dict[str, tuple[str, float]]` по ключу `host:port`.
- [ ] **Step 4:** pytest → PASS; ruff.
- [ ] **Step 5:** `git status`.

### Task A3: SSRF-обёртка с прокси

**Files:**
- Modify: `backend/app/core/ssrf.py` (`safe_request`)
- Test: `backend/tests/security/test_ssrf_proxy.py`

**Interfaces:**
- Produces: `safe_request(..., proxy: str | None = None, connect_timeout: float | None = None)`. Если `proxy` задан:
  - `check_url(url, allow)` — политика для цели;
  - `check_url(proxy_as_http_url, allow)` — прокси тоже публичный или разрешённый; для `socks5://` и `socks5h://` проверка хоста по тем же правилам;
  - запрос через `httpx.AsyncClient(proxy=proxy, trust_env=False, timeout=httpx.Timeout(timeout, connect=connect_timeout or timeout))` на исходный URL без закрепления IP;
  - редиректы не следуют (`max_redirects` = 0 в этом режиме), лимит размера ответа сохраняется.

  Без прокси поведение не меняется.

- [ ] **Step 1: Тесты:** `test_proxy_to_private_host_blocked` (`proxy="http://127.0.0.1:9"` без allow → `SSRFError`); `test_target_private_blocked_even_via_proxy`; `test_proxy_allowed_host_forwards_request` (локальный HTTP-прокси-сервер в тесте, `127.0.0.1:<port>` в `allow_hosts`, цель `http://example.test/` резолвится заглушкой-резолвером в публичный IP, прокси отвечает 200 → ответ получен, прокси видел абсолютный URL); `test_no_proxy_path_unchanged` (существующие тесты `tests/security` зелёные).
- [ ] **Step 2:** pytest → FAIL.
- [ ] **Step 3:** Реализовать ветку `proxy`.
- [ ] **Step 4:** `pytest tests/security -q` → PASS.
- [ ] **Step 5:** `git status`.

### Task A4: Ротация ключей, прокси и моделей в базовом провайдере

**Files:**
- Modify: `backend/app/ai/providers/base.py`
- Test: `backend/tests/ai/test_llm_rotation.py`

**Interfaces:**
- Consumes: A1 (`auto_retries`, `mask_proxy`), A2 (`resolve`, `remember`, `forget`), A3 (`safe_request(proxy=…)`).
- Produces (в `ProviderConfig`):
  - новые поля `api_keys: list[str] = []`, `fallback_models: list[str] = []`, `proxies: list[str] = []`;
  - `rotation_retries: int | None = None` (None → `auto_retries`);
  - `pause_first: float = 2.0`, `pause_step: float = 2.0`;
  - свойство `pooled: bool` = `len(keys) > 1 or proxies or fallback_models` (где `keys` = `api_keys or [api_key]`).
- Produces (в `LLMProvider`):
  - `async _rotate(attempt: Callable[[str, str | None, str | None], Awaitable[ChatResult]], validate: Callable[[str], bool] | None = None) -> ChatResult`. Аргументы `attempt` — `(model, key, concrete_proxy)`. Правила выбора модели, ключа и прокси, паузы — из Global Constraints.
  - Неудача — любое исключение `LLMError`/`httpx.HTTPError`, `asyncio.TimeoutError` (обёртка `asyncio.wait_for(…, timeout + 5)`) или `validate(text) is False`.
  - Успех → `remember(proxy)`; неудача → `forget(proxy)`.
  - В конце `LLMError(f"Все {n} попытки исчерпаны. Последняя ошибка: {reason}")`; при `n == 1` — просто причина.
  - Причины проходят через `Masker`, в который зарегистрированы все ключи и логин/пароль прокси.
  - Лог `logger.info("LLM attempt %d/%d: model=%s key=...%s proxy=%s", …)` — последние 4 символа ключа и `mask_proxy`.
  - `_request(..., proxy: str | None = None)` пробрасывает прокси в `safe_request` с `connect_timeout=min(timeout, 10)`.
  - `chat(...)` получает необязательный `validate: Callable[[str], bool] | None = None`; у провайдеров, где `cfg.pooled` ложно, поведение прежнее.

- [ ] **Step 1: Тесты** (фейковый провайдер-подкласс, `pause_first=0`):

```python
async def test_rotates_keys_and_models_until_success():
    calls = []
    async def attempt(model, key, proxy):
        calls.append((model, key))
        if len(calls) < 3: raise LLMError("HTTP 429")
        return ChatResult("ok", model)
    p = Fake(cfg(api_keys=["k1", "k2"], fallback_models=["m2"], model="m1"))
    res = await p._rotate(attempt)
    assert res.content == "ok" and calls[0][0] == "m1" and calls[1][0] == "m2" and calls[2][0] == "m2"
    assert {calls[0][1], calls[1][1]} == {"k1", "k2"}

async def test_validate_failure_counts_as_failed_attempt(): ...   # validate=lambda t: '"ok"' in t; 1-я попытка "{}"
async def test_exhausted_message_masks_secrets():               # ключ "sk-SECRETKEY1234", прокси с паролем "pw:x"
    with pytest.raises(LLMError) as e: await p._rotate(always_fail_with_text_containing_secrets)
    assert "SECRETKEY" not in str(e.value) and "pw:x" not in str(e.value) and "исчерпаны" in str(e.value)
async def test_hard_deadline_cancels_hung_attempt():            # attempt спит 10 с, timeout=0.2 → неудача ≤ 1 с
async def test_unpooled_provider_keeps_old_path():               # существующие tests/ai/* зелёные
```

- [ ] **Step 2:** pytest → FAIL.
- [ ] **Step 3:** Реализовать `_rotate` и проброс `proxy`; паузы `pause_first + pause_step * (i - 1)` перед попыткой `i ≥ 1`, максимум 10 с.
- [ ] **Step 4:** `pytest tests/ai -q` → PASS.
- [ ] **Step 5:** `git status`.

### Task A5: Провайдер `gemini` и пул для `openai_compat`

**Files:**
- Create: `backend/app/ai/providers/gemini.py`
- Modify: `backend/app/ai/providers/openai_compat.py`, `backend/app/ai/providers/ollama.py` (только проброс `validate`)
- Test: `backend/tests/ai/test_gemini_provider.py` (локальный HTTP-сервер в формате Gemini, как `tests/ai/fake_llm.py`)

**Interfaces:**
- Produces: `GeminiProvider(name="gemini")`. `chat` всегда через `_rotate`; одна попытка — `POST {base}/models/{model}:generateContent`, заголовок `x-goog-api-key: <key>`, тело `{"contents":[{"role": "user"|"model", "parts":[{"text":…}]}], "systemInstruction": {...} (если есть system), "generationConfig":{"temperature":t, "maxOutputTokens":n, "responseMimeType":"application/json" при response_schema}}`; при `response_schema` в system добавляется `JSON_INSTRUCTION`. Ответ: склейка `candidates[0].content.parts[*].text`; пустой текст — неудача; `json_mode="object"`. `list_models` — `GET {base}/models` (ключ в заголовке) → имена без префикса `models/`.
- `OpenAICompatProvider.chat`: если `cfg.pooled` — каждая попытка `_rotate` выполняет текущую логику с `model`, `Authorization: Bearer <key>`, `proxy`.

- [ ] **Step 1: Тесты:** `test_gemini_generate_content_request_shape` (сервер проверяет путь, заголовок, `responseMimeType`, отсутствие ключа в URL); `test_gemini_falls_back_to_second_model_on_429`; `test_gemini_empty_candidate_is_failure`; `test_gemini_list_models_strips_prefix`; `test_openai_compat_pooled_rotates_keys` (первый ключ → 401, второй → 200).
- [ ] **Step 2:** pytest → FAIL.
- [ ] **Step 3:** Реализовать.
- [ ] **Step 4:** `pytest tests/ai -q` → PASS.
- [ ] **Step 5:** `git status`.

### Task A6: Настройки, окружение, диагностика

**Files:**
- Modify: `backend/app/ai/settings_service.py`, `backend/app/api/ai.py`, `backend/app/api/credentials.py` (`KINDS += ["proxy"]`)
- Create: `backend/app/ai/diagnose.py`, `backend/app/ai/check_llm.py` (CLI `python -m app.ai.check_llm`)
- Modify: `scripts/gen_api_doc.py` (RU-строка для `POST /api/settings/ai/diagnose`), `docs/AI.md` (раздел «Внешние API через прокси»)
- Test: `backend/tests/api/test_ai_proxy_settings.py`

**Interfaces:**
- `AISettingsIn` новые поля:
  - `credential_ids: list[str] = []` (доп. ключи, порядок важен);
  - `proxy_credential_ids: list[str] = []` (секреты вида `proxy`, значение — строка прокси в формате A1);
  - `fallback_models: list[str] = []`;
  - `proxy_scheme: Literal["auto","http","https","socks5","socks5h"] = "auto"`;
  - `proxy_port: str | None`;
  - `max_retries: int | None (1..6)`.

  Хранятся в `AISettings.extra`; `settings_out` их возвращает (без значений секретов).
- `provider_config_for(...)`:
  - расшифровывает все ключи и прокси (регистрирует в `masker`), заполняет поля A4;
  - если у пространства нет `AISettings` (или не включено) **и** `get_llm_env().enabled` — строит конфиг из окружения: `gemini` или `ollama` (`base_url=OLLAMA_URL`, `model=OLLAMA_MODEL`, хост Ollama в `allow_hosts`);
  - секреты окружения в `masker`, в БД не пишутся.
- `POST /api/settings/ai/diagnose {workspace_id}` (роль developer) → `{"results": [{"proxy": "socks5://h:1080" | "direct", "scheme": "http"|…|None, "ok": bool, "ms": int, "error": str|None}]}`:
  - по одному запросу первым ключом через каждый прокси (для `auto` — по `http`, `socks5`, `https`, `socks5h`) и напрямую;
  - ошибки замаскированы.
- `GET /api/settings/ai` дополнительно возвращает `env_default: {"enabled": bool, "provider": str, "model": str}` (без секретов).

- [ ] **Step 1: Тесты:**
  - `test_put_and_get_pool_settings_roundtrip`: ключи и прокси сохраняются ссылками; в ответе нет значений.
  - `test_proxy_credential_kind_accepted`.
  - `test_env_default_used_when_workspace_unconfigured`: monkeypatch `get_llm_env`, `LLM_PROVIDER=gemini`, `base_url` указывает на фейковый Gemini; AI-отчёт генерируется с `ai_generated=True`.
  - `test_diagnose_reports_per_proxy_without_secrets`: два локальных прокси, один мёртвый.
  - `test_secret_canary_not_in_diagnose_or_logs`: секрет-канарейка в ключе и пароле прокси не попадает в ответ и `caplog`.
- [ ] **Step 2:** pytest → FAIL.
- [ ] **Step 3:** Реализовать; `make api-doc` (`cd backend && .venv/Scripts/python ../scripts/gen_api_doc.py`).
- [ ] **Step 4:** `pytest -q` (весь backend) → PASS; `tests/security/test_platform_security.py` зелёный.
- [ ] **Step 5:** `git status`.

### Task A7: UI настроек AI

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx` (секция AI), `frontend/src/i18n/{ru,en}.ts`
- Test: проверка в B9 (e2e: открыть «Настройки → AI», добавить прокси-секрет, «Проверить соединение» показывает таблицу)

**Interfaces:**
- Consumes: A6 (`GET/PUT /api/settings/ai`, `POST /api/settings/ai/diagnose`, `POST /api/credentials` с `kind: "proxy"`).
- Produces: в форме AI:
  - провайдер (`gemini` с подсказкой base URL);
  - мульти-выбор ключей из хранилища;
  - модели-фолбэки (через запятую);
  - список прокси (секреты `proxy`, кнопка «Добавить прокси» создаёт секрет);
  - протокол, порт по умолчанию, число попыток;
  - баннер «Используется провайдер из окружения: gemini · gemini-2.5-flash», если `env_default.enabled` и своего нет;
  - кнопка «Проверить соединение» вызывает `diagnose` и показывает таблицу OK/FAIL, мс, причину.

- [ ] **Step 1:** Реализовать; `npx tsc -b --noEmit`; `npx vitest run src/i18n`.
- [ ] **Step 2:** Проверить вживую на dev-стеке: фейковый Gemini — `backend/tests/ai/fake_llm.py` в режиме сервера или `scripts/mock_services.py` (если в нём нет Gemini-формата — проверить на `openai_compat` mock). Скриншот.
- [ ] **Step 3:** `git status`.

---

## Часть B. Рабочее пространство

### Task B1: Подтверждение собственного репозитория (вариант А)

**Files:**
- Create: `backend/app/api/repos.py` (регистрация в `app/main.py`)
- Modify: `backend/app/core/repo_guard.py` — `normalize_user_repo_url(raw: str) -> str` (обрезает пробелы, `.git`, хвост `/tree/<ref>…` и `/blob/…`, `http://` → ошибка «нужен https»)
- Test: `backend/tests/api/test_repo_attest.py`

**Interfaces:**
- Produces: `POST /api/repos/attest {workspace_id?, url: str, confirm: bool}` (роль developer):
  - `confirm` ≠ true → 422 `confirmation_required`;
  - URL нормализуется и проверяется `check_git_url(norm, [norm])`;
  - хост должен резолвиться только в публичные адреса (`check_url` из `ssrf.py` без allow) → иначе 422 `private_host`;
  - добавляет `RepoAllowlist(url=norm, allow_write=False)`, если записи нет;
  - пишет `audit(s, "repo.attest", …, details={"confirmation": "учебный/собственный проект"})`;
  - ответ `{"url": norm, "ref": <ref из /tree/<ref>> | None, "readonly": is_readonly_repo(norm)}`.

- [ ] **Step 1: Тесты:**
  - без `confirm` → 422;
  - `https://github.com/Org/Repo.git` и `…/tree/dev/src` → `url=https://github.com/Org/Repo`, у второго `ref="dev"`;
  - `http://…` → 422 с текстом про https;
  - `https://10.0.0.5/x/y` и хост, резолвящийся в `127.0.0.1` (резолвер подменён) → 422 `private_host`;
  - повторный вызов не дублирует запись;
  - аудит записан;
  - viewer → 403;
  - после attest `check_git_url(url, allowlist)` проходит.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS + `make api-doc`. **Step 5:** `git status`.

### Task B2: Создание проверки одним запросом

**Files:**
- Create: `backend/app/api/checks.py` (регистрация в `app/main.py`)
- Modify: `backend/app/templates/…` или место, где живёт `apply_parameters` (найти: `grep -rn "def apply_parameters" backend/app`) — режим `partial=True`, оставляющий незаполненные параметры пустыми
- Test: `backend/tests/api/test_checks.py`

**Interfaces:**
- Produces: `POST /api/checks` (201) — тело:
  - `workspace_id?`, `name?`;
  - `source: {mode: "git_url"|"upload"|"training", url?, ref?, upload_id?}`;
  - `start: {"template_id": str} | {"blank": true} | {"prompt": str}`.

  Возвращает `{"workflow_id": str, "needs_input": [{"node_id", "field"}]}`. Логика:
  - `training` → путь из `GET /api/demo/training`-логики (`TRAINING` + `check_scan_path`);
  - `git_url` требует, чтобы URL был в allowlist (иначе 422 `not_attested`, UI сначала вызывает B1);
  - шаблон применяется с `partial=True`; источник записывается во **все** ноды `source.repo` (`mode`, `git_url`/`ref` или `upload_id` или `path`);
  - `blank` → граф `trigger.manual → source.repo`;
  - `prompt` → `ai.workflow_gen`, без LLM → 422 `ai_not_configured`;
  - `name` по умолчанию: последний сегмент URL / имя архива / «Учебный проект».
- Системные шаблоны для карточек «С чего начать?»:
  - `GET /api/checks/starters` → `[{id, title, description, template_id}]`;
  - порядок: «Полная проверка», «Только секреты», «Проверка PR (diff)»;
  - взять из существующих системных шаблонов (`grep -rn "system" backend/app/templates`); если «Проверка PR (diff)» нет — добавить системный шаблон на основе `demo_graph()` из `app/api/demo.py`.

- [ ] **Step 1: Тесты:**
  - training + «Полная проверка» → граф валиден (`/api/workflows/validate`), запуск даёт 15 находок;
  - git_url без attest → 422 `not_attested`;
  - шаблон с параметром Telegram без значения создаётся, в `needs_input` есть нода telegram;
  - `blank` → 2 ноды и 1 ребро;
  - `upload` → `source.repo.config.upload_id` выставлен;
  - `starters` возвращает 3 элемента в заданном порядке.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS + весь backend `pytest -q` + `make api-doc`. **Step 5:** `git status`.

### Task B3: Каркас рабочего пространства и маршруты

**Files:**
- Create: `frontend/src/workspace/WorkspaceLayout.tsx` (левая колонка + `<Outlet/>` + хост выдвижных панелей), `frontend/src/workspace/Drawer.tsx`, `frontend/src/workspace/routes.ts`, `frontend/src/store/workspace.ts` (Zustand: `railCollapsed`, `inspectorCollapsed`, `lastWorkflowId` — в `localStorage`)
- Modify: `frontend/src/App.tsx` (новые маршруты), `frontend/src/components/layout/AppShell.tsx` (используется только для страниц входа, если нужно; верхняя навигация удаляется)
- Test: `frontend/src/workspace/routes.test.ts`

**Interfaces:**
- Produces:
  - `legacyRedirect(pathname: string, search: string): string | null`:
    - `/workflows/:id` → `/c/:id`;
    - `/workflows` и `/` → `null` (обрабатывает индекс);
    - `/pr?run=X` → `/runs/X`;
    - `/templates` → `?panel=templates`, `/integration` → `?panel=ci`, `/settings` → `?panel=settings`, `/projects` → `?panel=settings&tab=projects`, `/runs` → `?panel=history`, `/runs/compare?...` → `?panel=history&compare=...`.
  - `panelFromSearch(search: string): PanelId | null`, где `type PanelId = "history" | "templates" | "ci" | "overview" | "settings"`.
  - Маршруты:
    - `/` → `lastWorkflowId` или первая проверка, иначе открыть `NewCheckDialog` (B6);
    - `/c/:id` → `CanvasPage` (B4);
    - `/runs/:id` → загрузить запуск: есть `workflow_id` → `navigate('/c/<wf>?run=<id>', {replace:true})`, иначе полноэкранный `RunDetailsPage`.
  - Левая колонка: список проверок (`useWorkflows`) с точкой статуса последнего запуска, «+ Новая проверка», пункты панелей, переключатели темы и языка, аккаунт и пространство (перенос из `AppShell`). Ширина 240 / 64 px.
  - `Drawer`: справа налево поверх холста, ширина `min(920px, 70vw)`, `Esc` и клик по подложке закрывают, фокус-ловушка, анимация `transform` 220 мс.

- [ ] **Step 1: Тест** `routes.test.ts`: таблица из 8 случаев `legacyRedirect` + `panelFromSearch`.
- [ ] **Step 2:** `npx vitest run src/workspace` → FAIL. **Step 3:** Реализовать. **Step 4:** PASS, `npx tsc -b --noEmit`. **Step 5:** `git status`.

### Task B4: Холст на весь экран, плавающая палитра, инспектор, автосохранение

**Files:**
- Create: `frontend/src/editor/CanvasPage.tsx` (вместо разметки `EditorPage`; логика `EditorInner` переносится сюда без потерь: undo/redo, копировать/вставить, контекстное меню, горячие клавиши, импорт/экспорт, AI-ассистент, публикация, связи), `frontend/src/editor/QuickAdd.tsx` (плавающая палитра), `frontend/src/editor/Inspector.tsx`, `frontend/src/editor/useAutosave.ts`
- Delete после переноса: разметка-карточки из `frontend/src/editor/WorkflowPanels.tsx`, которые больше не используются (`SourceCard`, `LinksCard`, `RunHistoryCard`, `RunDataCard`); `findConnection` остаётся в `graphModel.ts` и используется QuickAdd
- Modify: `frontend/src/editor/EditorPage.tsx` → реэкспорт `CanvasPage` или удалить и поправить `App.tsx`
- Test: `frontend/src/editor/useAutosave.test.ts`, `frontend/src/editor/graphModel.test.ts` (+ `placeAfter`)

**Interfaces:**
- Produces:
  - `useAutosave(save: () => Promise<boolean>, dirty: boolean, delayMs = 800): { flush(): Promise<boolean>, pending: boolean }` — дебаунс; `flush` отменяет таймер и сохраняет немедленно, если `dirty`.
  - `placeAfter(source: FlowNode, existing: FlowNode[]): {x, y}` в `graphModel.ts` — позиция под нодой-источником (+140 по y), со сдвигом по x на 280, пока место занято.
  - Шапка:
    - имя (inline-редактирование → `PUT /api/workflows/:id {name}`);
    - строка источника (из ноды `source.repo`: URL / имя архива / «Учебный проект» / «проект»), клик открывает `NewCheckDialog` в режиме «сменить источник» (B6);
    - переключатель «Запуск: вручную / по расписанию ЧЧ:ММ / вебхук» — заменяет тип ноды-триггера, сохраняя id и связи (логика `replaceTrigger` из текущего `EditorPage`);
    - «Запустить» сначала вызывает `flush()`, затем запуск;
    - отмена и повтор, «Раскладка», «AI», меню «⋯»: импорт, экспорт, опубликовать как шаблон, проверить граф, удалить;
    - индикатор «Сохранено / Сохраняется…».
  - `QuickAdd`:
    - открывается кнопкой «+» в шапке, клавишей `Tab` (если фокус не в поле) и кнопкой «+» на выходе выбранной ноды;
    - поиск, группы по категориям, перетаскивание (`DRAG_MIME`);
    - клик добавляет ноду: при открытии с выхода — в `placeAfter` и с автосвязью через `findConnection`, иначе в центр видимой области.
  - `Inspector` (правая колонка 380 px):
    - выбрана нода и нет запуска → `ConfigPanel`;
    - выбрана нода и есть запуск → `RunNodePanel`;
    - ничего не выбрано и есть показываемый запуск → `RunResults` (B5);
    - иначе — подсказка «Добавьте ноду (+ или Tab) или запустите проверку».
  - Показываемый запуск: `?run=` или живой запуск; выбор в «Истории» ставит `?run=`.

- [ ] **Step 1: Тесты:**
  - `useAutosave`: fake timers; изменение → через 800 мс один вызов `save`; `flush()` до таймера → один вызов, таймер отменён;
  - `placeAfter`: свободное место прямо под источником; занятое → смещение на 280.
- [ ] **Step 2:** vitest → FAIL. **Step 3:** Реализовать. **Step 4:** vitest PASS, `tsc`.
- [ ] **Step 5:** Ручная проверка на стеке: перетаскивание, связи, контекстное меню, `Ctrl+Z/Y/C/V/D/S`, `Tab`, импорт/экспорт, AI-ассистент открывается. `git status`.

### Task B5: Итоги запуска в инспекторе

**Files:**
- Create: `frontend/src/results/RunResults.tsx` (вкладки), `frontend/src/results/FindingsTab.tsx`, `frontend/src/results/FindingDetail.tsx` (AutoFix-поток из `PrReviewPage.AutofixCard`), `frontend/src/results/ReportTab.tsx`, `frontend/src/results/ScoreTab.tsx`, `frontend/src/results/DataTab.tsx`, `frontend/src/results/JournalTab.tsx`
- Delete: `frontend/src/pages/PrReviewPage.tsx` (логика перенесена; маршрут `/pr` редиректит по B3)
- Reuse: `components/autofix.tsx` (`Autofix`, `PatchView`), `components/score.tsx`, `TrustIndicator` из `pages/RunDetailsPage.tsx`, хуки `useRun`, `useRunFindings`, `useAiReport`
- Test: `frontend/src/results/findings.test.ts`

**Interfaces:**
- Produces:
  - `RunResults({ run }: { run: Run })` — вкладки «Находки · AI-отчёт · Score · Данные · Журнал».
  - Шапка итогов: статус, вердикт (FAIL/PASS или «без вердикта» — правило из текущего `runFailed` + проверка наличия verdict/gate), время, количество находок со «счётчиком» (анимация 600 мс), кнопки экспорта (`submission.json`, `report.md`, `report.html` через `downloadFile`), «Сравнить с предыдущим» (`/runs/compare`, панель «История»), «Открыть полный отчёт» (Drawer с `RunDetailsPage`).
  - `filterFindings(list: Finding[], f: {diff: "new"|"existing"|"all", severity?: Severity, category?: string}): Finding[]` и `sortFindings` (новые → критичность → путь) в `findings.ts`.
  - `FindingDetail`: где, почему такая критичность, рекомендация, замаскированный фрагмент, AI AutoFix → чеклист + diff → «Скачать .patch» / «Создать PR» (если `can_create_pr`) → «Применить патч и перепроверить» → результат перепроверки и «Открыть новый запуск».

- [ ] **Step 1: Тест** `findings.test.ts`: фильтры по diff, severity, category; порядок сортировки.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS, `tsc`.
- [ ] **Step 5:** Ручная проверка на стеке: SCA-находка → AutoFix → перепроверка → PASS. `git status`.

### Task B6: «Новая проверка» и первый экран

**Files:**
- Create: `frontend/src/workspace/NewCheckDialog.tsx`
- Modify: `frontend/src/workspace/WorkspaceLayout.tsx` (кнопка «+ Новая проверка», автопоказ при пустом списке), `frontend/src/i18n/{ru,en}.ts`
- Test: `frontend/src/workspace/newCheck.test.ts`

**Interfaces:**
- Consumes: B1 (`/repos/attest`), B2 (`/checks`, `/checks/starters`), `POST /api/uploads` (как `UploadField`), `GET /api/demo/training`.
- Produces:
  - `validateRepoInput(raw: string): { ok: true, url: string } | { ok: false, reason: "empty" | "not_https" | "not_url" }` — клиентская предпроверка (финальная нормализация на сервере).
  - Диалог: шаг 1 «Что проверяем?» (URL + ветка + обязательная галочка; или архив; или «Учебный проект», если `available`); шаг 2 «С чего начать?» (карточки `starters` + «Пустой граф» + «Описать словами (AI)» с полем текста; без провайдера карточка AI показывает «Подключите AI в настройках»).
  - Кнопки «Создать и открыть» / «Создать и запустить»: attest (для URL) → `/checks` → переход на `/c/:id` (и при «запустить» — `POST /api/workflows/:id/run`, `?run=`).
  - Режим `mode="change-source"`: только шаг 1, обновляет ноды `source.repo` открытой проверки.
  - Первый экран: если проверок нет — диалог открыт поверх пустого холста, закрыть нельзя, пока не создана первая проверка (есть ссылка «Открыть пустой конструктор» → `start: blank` с источником «Учебный проект»).

- [ ] **Step 1: Тест** `validateRepoInput`: пусто → empty; `http://x/y` → not_https; `github.com/x` → not_url; `https://github.com/a/b.git ` → ok с обрезанным пробелом.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS, `tsc`.
- [ ] **Step 5:** Ручная проверка: от входа до запуска по ссылке ≤ 3 действия (вставить → галочка → «Создать и запустить»; галочку считаем частью шага ввода). `git status`.

### Task B7: Неоновые анимации выполнения

**Files:**
- Create: `frontend/src/editor/neon.css` (импорт в `CanvasPage`), `frontend/src/editor/runAnimation.ts`
- Modify: `frontend/src/editor/NodeCard.tsx` (классы состояний), `frontend/src/editor/CanvasPage.tsx` (оверлей запуска, финальная волна, кастомный тип ребра), create `frontend/src/editor/FlowEdge.tsx` (ребро с «пакетом» и значком количества)
- Test: `frontend/src/editor/runAnimation.test.ts`

**Interfaces:**
- Produces:
  - `nodeVisualState(status: NodeStatus | undefined, runActive: boolean): "idle" | "waiting" | "running" | "success" | "failed" | "skipped"`.
  - `finaleOrder(nodes: {id: string, startedAt?: string | null}[]): string[]` — успешные ноды по времени старта (для волны, шаг 60 мс).
  - CSS-классы `.node-waiting`, `.node-running`, `.node-success`, `.node-failed`, `.node-skipped`, `.node-finale` по таблице спеки, раздел 7:
    - `@property --neon-angle { syntax: '<angle>'; inherits: false; initial-value: 0deg }`;
    - рамка — псевдоэлемент `::before` с `conic-gradient(from var(--neon-angle), …)` и маской `padding-box`/`border-box`;
    - вращение 1.8 с linear infinite; свечение `box-shadow` пульс 1.6 с;
    - `success`: вспышка 300 мс, затем ровная обводка; `failed`: покачивание 2×80 мс;
    - `skipped`: `opacity .45` + пунктир.
  - `FlowEdge`: путь `smoothstep`; при `data.active` — бегущий светящийся сегмент (`stroke-dasharray` + анимация `stroke-dashoffset` 900 мс) и значок `data.count` с pop-in.
  - Оверлей холста при запуске: затемнение 8 % за 200 мс.
  - Финальная волна по `finaleOrder`, после неё инспектор открывает «Итоги».
  - `@media (prefers-reduced-motion: reduce)`: все `animation: none`, статичные цветные рамки.
  - Цвета — из CSS-переменных темы (`--primary`, `--edge`, `--danger`, новые `--neon-1/2/3` в `index.css` для обеих тем).

- [ ] **Step 1: Тест:** `nodeVisualState` — таблица (pending+active → waiting, running → running, skipped → skipped, undefined+inactive → idle); `finaleOrder` — сортировка и исключение неуспешных.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS.
- [ ] **Step 5:** Ручная проверка на стеке в обеих темах: запуск демо-сценария; Performance-профиль (30 нод) ≥ 50 FPS; эмуляция `prefers-reduced-motion` в DevTools. Скриншоты/запись для отчёта. `git status`.

### Task B8: Выдвижные панели второго уровня

**Files:**
- Create: `frontend/src/workspace/panels/HistoryPanel.tsx`, `TemplatesPanel.tsx`, `CiPanel.tsx`, `OverviewPanel.tsx`, `SettingsPanel.tsx`
- Modify (переиспользование содержимого как компонентов без `Page`-обёртки): `pages/RunsPage.tsx`, `pages/ComparePage.tsx`, `pages/TemplatesPage.tsx`, `pages/IntegrationPage.tsx`, `pages/DashboardPage.tsx`, `pages/SettingsPage.tsx`, `pages/ProjectsPage.tsx` — вынести тело в экспортируемые компоненты (`RunsView`, `CompareView`, `TemplatesView`, `IntegrationView`, `OverviewView`, `SettingsView`, `ProjectsView`)
- Test: e2e в B9

**Interfaces:**
- Consumes: B3 (`Drawer`, `PanelId`, `?panel=`), B6 (`NewCheckDialog` с предвыбранным шаблоном).
- Produces:
  - История: по умолчанию запуски открытой проверки, переключатель «все»; клик по запуску → `/c/<wf>?run=<id>` и закрытие панели; сравнение двух.
  - Шаблоны: «Использовать» → `NewCheckDialog` с шаблоном на шаге 2 (параметр-путь больше не спрашивается); публикация текущей проверки — из меню «⋯» холста (существующий `PublishDialog`).
  - CI/CD: `IntegrationView` с предвыбранной открытой проверкой.
  - Обзор: дашборд.
  - Настройки: вкладки AI (A7), секреты, allowlist, участники, расписания, проекты, интерфейс.

- [ ] **Step 1:** Реализовать; `tsc`; `npx vitest run`.
- [ ] **Step 2:** Ручная проверка каждой панели на стеке. `git status`.

### Task B9: E2E, документация, отчёт

**Files:**
- Modify: `frontend/e2e/flow.spec.ts` (переписать под новый поток), `README.md` (демо-сценарий), `docs/REPORT.md` («Фаза 10»), `docs/AI.md`, `CLAUDE.md` + `AGENTS.md` (синхронно: новые подводные камни), `.superpowers/sdd/design/progress.md` (rulings), скриншоты `docs/screens`
- Test: `npx playwright test`

**Interfaces:**
- Consumes: всё выше.
- e2e-сценарий 1 (основной):
  - регистрация → автоматически открыт «Новая проверка» → «Учебный проект» + «Полная проверка» → «Создать и запустить»;
  - на холсте появляются `.node-running`, затем `.node-success`;
  - в «Итогах» 15 находок → SCA-находка → «Проверить патч» → «Применить патч и перепроверить» → PASS;
  - `/runs/<id>` открывает `/c/<wf>?run=<id>`;
  - `/workflows/<id>` → `/c/<id>`.
- e2e-сценарий 2 (конструктор):
  - «+ Новая проверка» → «Пустой граф»;
  - перетаскивание сканеров из QuickAdd, связи, IF;
  - `Tab` открывает палитру;
  - запуск → статусы и значки количества на рёбрах.
- e2e-сценарий 3 (шаблоны и CI):
  - панель «Шаблоны» → опубликовать текущую → найти → «Использовать» → диалог с шаблоном;
  - панель «CI/CD» показывает YAML.
- e2e-сценарий 4 (своя ссылка):
  - ввод `http://…` → ошибка https;
  - ввод `https://github.com/TBagirov/training` без галочки → кнопка неактивна;
  - с галочкой → attest проходит (сеть не нужна — проверяем только ответ attest и что проверка создана, без запуска).
- e2e-сценарий 5: «Настройки → AI» — добавить прокси-секрет, «Проверить соединение» показывает таблицу.
- Скриншоты: рабочее пространство (светлое/тёмное, RU/EN), запуск с неоном (`.node-running` в кадре), итоги, новая проверка.

- [ ] **Step 1:** Переписать e2e. **Step 2:** `npx playwright test` → 5 passed.
- [ ] **Step 3:** Полная регрессия: `cd backend && .venv/Scripts/pytest -q`; `ruff check app tests ../scripts`; `cd frontend && npx tsc -b --noEmit && npx vitest run`; `grep -R "repairdesk\|RepairTicketReader\|WarrantyHeaders" backend/app` пусто; поиск заглушек пуст.
- [ ] **Step 4:** Документация и отчёт: таблица «требование ТЗ → где в интерфейсе» (из спеки раздел 4) с отметкой проверки.
- [ ] **Step 5:** `git status` — список изменений для пользователя; не коммитить.

---

## Порядок выполнения

A1 → A2 → A3 → A4 → A5 → A6 → A7 (часть A независима от B, даёт рабочий результат сама по себе) → B1 → B2 → B3 → B4 → B5 → B6 → B7 → B8 → B9.
