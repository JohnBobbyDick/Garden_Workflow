# Анализаторы

Все три анализатора написаны с нуля: готовые сканеры и их наборы правил не используются. Kotlin-код разбирается tree-sitter (`tree-sitter-kotlin`) в собственное промежуточное представление (`app/analyzers/common/kotlin_ast.py`). LLM в обнаружении не участвует, она только объясняет найденное.

Общий вход — корень проекта. Общий выход — список `Finding` (`app/analyzers/common/finding.py`). Объединяет анализаторы `app/analyzers/runner.py::analyze_project`.

## Общие механизмы

| Механизм | Где | Что делает |
| --- | --- | --- |
| Обход файлов | `common/files.py` | Пропускает `.git`, `build`, `node_modules` и подобные каталоги, а также шаблоны корневого `.gitignore`, символические ссылки, бинарные и слишком большие файлы. `safe_file` открывает только обычные файлы внутри корня, без symlink и `..`. |
| Константный резолвер | `common/kotlin_ast.py::ConstantResolver` | Вычисляет строку из локальных переменных, полей, `const`/`object`, других файлов (`ProjectIndex`), шаблонов, `+`, `StringBuilder`/`buildString`, `format`/`String.format`, `joinToString`, Base64 и `reversed/trim/lowercase`. Бюджет общий на вложенные вызовы: глубина 48, 2000 вычислений, значение до 64 КБ, проверка по ходу построения. |
| Маскирование | `common/masking.py` | Форма `ab…(len=N)` (для значений короче 8 символов — `…(len=N)`) и отпечаток `sha256:<8hex>:<len>`. В сниппетах маскируются значение и каждый литерал-фрагмент, из которого оно собрано; у PEM — каждая строка тела. |
| Дедупликация | `common/finding.py::dedupe_findings` | SECRET: тот же файл и (тот же отпечаток или пересечение строк) → остаётся самый конкретный класс, затем самый уверенный. SAST: тот же класс с пересечением строк. SCA: те же координаты и advisory. |
| Критичность | `common/severity.py` | SCA: CVSS v3 (свой калькулятор), иначе уровень из справочника. SECRET: базовая таблица по классу; путь продакшн-кода +1, тесты и документация −1. SAST: матрица класс × достижимость без аутентификации. |

**Шкала уверенности (`confidence`).** 0.9–0.95 — сигнатура или точный AST-шаблон. 0.8–0.88 — межпроцедурный вывод (taint, IDOR, маршруты). 0.45 — энтропийная эвристика. В документации уверенность умножается на ×0.55–0.6, в тестах — на ×0.6. Порог отбора задаётся `min_confidence` в настройках узла.

## SECRET (`app/analyzers/secrets/`)

Слои по порядку:

1. **Сигнатуры** (`rules.py::SIGNATURES`): ключи AWS, токены GitHub, Telegram, Slack, Stripe, ключи Google API, JWT (заголовок проверяется декодированием), PEM-ключи, учётные данные в URL и JDBC, Basic. Срабатывают в файлах любого типа.
2. **Kotlin AST** (`kotlin_consts.py`):
   - **имена**: семантика имени, разбитого на слова (`password`/`api-key`/`token`; суффиксы вроде `Name`, `Header`, `Env` исключаются);
   - **стоки**: заголовки с секретным именем, `setBearerAuth`/`basicAuth`, `.password(x)`, `"X-Api-Key" to v`, `headers["…"] = v`;
   - **fallback**: `getenv(..) ?: "…"`, `getProperty(k, "…")`, `getOrDefault`, `orElse`, `@Value("${k:default}")`;
   - **восстановление** (`recoverable-token`): значение из ≥2 литералов или с преобразованием, использованное как секрет. Диапазон — от первого литерала до места использования, не больше 15 строк.
3. **Конфигурация** (`config_files.py`): YAML (пути ключей и строки через `yaml.compose`), `.properties`/`.env`, JSON, XML и общий `key=value`. `${ENV}` без значения по умолчанию не считается секретом; `${ENV:literal}` — это `secret-fallback`.
4. **Энтропия** — только как слабая эвристика (`generic-secret`, 0.45). Порог Шеннона зависит от алфавита.

**Как снижаются FP.** Отсеиваются:
- плейсхолдеры (`YOUR_…`, `changeme`, `xxx`, `<…>`, `example`);
- имена переменных окружения, точечные ключи, имена заголовков, URL без учётных данных, пути, форматные строки, обычные слова, строки с пробелами;
- значения, которые резолвер вычислил из окружения.

## SCA (`app/analyzers/sca/`)

- **Разбор Gradle Kotlin DSL** (`gradle_parser.py`) — по AST и только внутри `dependencies {}`. Версия берётся:
  - из литерала;
  - из `val`;
  - из `extra[...]`;
  - из `by project` и `gradle.properties`;
  - из `providers.gradleProperty`;
  - из каталога `libs.versions.toml`;
  - из `platform()`.

  Groovy DSL разбирается регулярными выражениями. Модули берутся из `include` в `settings.gradle(.kts)`, без `..`.
- Версия из `gradle.lockfile` важнее объявленной. Место объявления остаётся основной локацией, место определения версии — альтернативной.
- **Справочник** (`vulndb.py`) проверяется по JSON-схеме. Диапазоны `introduced/fixed/lastAffected` сравниваются собственным сравнением версий (`versions.py`); нечисловые версии дают заметку, а не находку.
- **advisoryId** — CVE, если есть, иначе GHSA. **Remediation** — ближайшая исправленная версия. Autofix детерминированный: замена версии.
- Транзитивные зависимости показываются только по флагу, с `scope=transitive`.

## SAST (`app/analyzers/sast/`)

**Модель:**
- `spring_security.py` — маршруты контроллеров (префикс класса + метод) и правила `SecurityFilterChain`:
  - `requestMatchers`/`antMatchers`/`mvcMatchers`;
  - `anyRequest`;
  - DSL `authorize(...)`.

  Правила упорядочены по позиции в исходнике, срабатывает первое совпавшее. Ant-шаблоны (`*`, `**`, `{var}`) переводятся в регулярные выражения.
- `callgraph.py` — вызовы через поля конструктора (Spring DI), реализации интерфейсов, Spring Data репозитории.
- `taint.py`:
  - **источники**: параметры обработчиков (`@RequestParam`, `@PathVariable`, `@RequestBody`, …) и `request.getParameter/getHeader/...`;
  - **распространение**: шаблоны, `+`, `format`, `StringBuilder`, преобразования, аргументы вызовов (фиксированная точка по графу);
  - **санитайзеры**: числовые и UUID-типы, enum, `toLong`/`toInt`, проверки `matches`/`contains`.

Если стоком является всё тело функции-выражения, диапазон находки идёт от строки объявления функции до стока — как в эталоне организаторов.

| Класс | Что ищет | Как снижаются FP |
| --- | --- | --- |
| `sql-injection` | Taint из запроса в первый аргумент `query*/update/execute/createQuery/createNativeQuery/executeQuery/prepareStatement` на получателе типа JdbcTemplate/EntityManager/Statement/... Диапазон — от построения строки (`val sql = …`, `StringBuilder`) до стока. | Параметризованные запросы (литерал с `?`/`:name`) не помечены. Числовые и UUID-параметры не помечены. Константы в шаблоне не считаются taint. |
| `tls-verification` | `hostnameVerifier = { _, _ -> true }`, `setHostnameVerifier`, `setDefaultHostnameVerifier`, `.hostnameVerifier{…true}` у OkHttp, `NoopHostnameVerifier`, `TrustAllStrategy`, `InsecureTrustManagerFactory`, `X509TrustManager` с пустым `checkServerTrusted` (класс или анонимный объект). | Лямбда должна возвращать константу `true`. Верификатор с условием и стандартный HTTPS-клиент не помечаются. |
| `credentialed-cors` | В одной области (лямбда `apply {}`, цепочка `CorsRegistry` или функция): `allowedOrigins`/`allowedOriginPatterns`/`addAllowedOrigin*` со значением `*` (в том числе через константы) и `allowCredentials = true` / `allowCredentials(true)`; `@CrossOrigin(origins=["*"], allowCredentials="true")`. | Без учётных данных или с конкретным origin — не помечается. |
| `route-authorization` | `permitAll()` для конкретного шаблона, который перекрыт более общим и более строгим шаблоном ниже (`hasRole`/`authenticated`/`denyAll`), при этом обработчик маршрута обращается к данным (JDBC/JPA/репозиторий, транзитивно). Альтернативная локация — обработчик. | Публичные маршруты без доступа к данным (статический каталог) и обработчики с `@PreAuthorize`/`@Secured` не помечаются. `anyRequest()` не считается «более строгим шаблоном». |
| `object-authorization` | Обработчик с `@PathVariable` идентификатора, который не использует Principal/Authentication/SecurityContext. Идентификатор передаётся через сервисы в доступ к данным по id: SQL, где в `WHERE` нет колонки владельца, `findById` и подобные, `em.find`. Нужен признак «данные пользователя»: сегмент пути (`customer`, `user`, `me`, `account`, …) или колонка/поле владельца в выборке/сущности. Основная локация — доступ к данным, альтернативная — обработчик. | Фильтр по владельцу в SQL, имя метода с владельцем (`findByIdAndOwner`), сравнение с Principal после загрузки, вызовы `check*Owner/*Access`, `@PostAuthorize` — не помечаются. |
| `hardcoded-credentials` | `.password("литерал")` в `User.withUsername`/`withUser`/`inMemoryAuthentication`/`DataSourceBuilder`; `DriverManager.getConnection(url, user, "литерал")`. Значение в сниппете маскируется. | Пароль из окружения/кодировщика, плейсхолдеры, bcrypt-хеши (`$2…`) не помечаются. |
| `unsafe-deserialization` | `ObjectInputStream(...).readObject()`, `XMLDecoder`, `Yaml().load*`, `XStream.fromXML` без `allowTypes`, Jackson `enableDefaultTyping`/`activateDefaultTyping` с `LaissezFaire`. | `ObjectInputFilter`, `Yaml(SafeConstructor(...))`, `ObjectMapper.readValue` в DTO не помечаются. |
| `path-traversal` | Taint из запроса в `File(...)`, `FileInputStream`, `Paths.get`/`Path.of`, `Files.*`, `base.resolve(x)`. | Функция с `normalize()` + `startsWith(base)`, `FilenameUtils.getName` или `.fileName` считается проверенной. |
| `weak-crypto` | `MessageDigest` MD5/SHA-1, `Cipher` DES/3DES/RC4/ECB/`"AES"` без режима, `KeyGenerator` DES, `NoOpPasswordEncoder` и подобные; `Random()`/`Math.random` для переменных с семантикой секрета (`token`, `password`, `nonce`, `salt`, `otp`, …). | `Random` для несекретных значений (jitter) не помечается. |
| `missing-input-validation` | Параметр `@RequestBody`, чей DTO содержит ограничения Bean Validation, без `@Valid`/`@Validated`. | DTO без ограничений и контроллеры с `@Validated` не помечаются. |
| `insecure-endpoint` | Конфигурация: `management.endpoints.web.exposure.include=*`, `spring.h2.console.enabled=true`, `web-allow-others`, `include-stacktrace=always`, `env.show-values=always`, `management.security.enabled=false`. Код: GET-обработчик, который меняет состояние (`delete*`/`update*`/`save*` на репозитории/сервисе). | Ограниченный список эндпоинтов, файлы `test/` и GET-обработчики только для чтения не помечаются. |
| `csrf-disabled` | `csrf().disable()` / `csrf { it.disable() }` при `formLogin`/`httpBasic`/`sessionManagement`. | Конфигурации с `SessionCreationPolicy.STATELESS` не помечаются. |

Правило можно отключить (`disabled_rules`) и задать порог `min_confidence` — это настраивается в узле workflow.

## Проверка качества

- `make test` — модульные тесты; у каждого правила есть положительные и «опасно похожие» отрицательные случаи (`tests/unit/test_sast.py`, `test_secrets.py`, `test_sca.py`, `test_analyzer_hardening.py`).
- `make test-eval` — сверка с эталоном организаторов и с мутантами (`fixtures/mutants/*/expected.json`) по правилам из README эталона: категория, путь, класс и строка (с учётом `alternateLocations`), для SCA — координаты, версия и advisory. Тест падает на пропуске, на срабатывании контроля и на необъяснённой лишней находке.
- Анализаторы не содержат имён файлов, классов и переменных из учебного набора (это проверяется grep на гейте фазы).

**Текущие результаты** (`make test-eval`, фаза 7): учебный набор — recall 100 % (15/15), precision 100 %, контролей 0,
лишних 0; мутанты `clinic-appointments` 15/15, `library-loans` 15/15, `parcel-lockers` 16/16, контролей 0, лишних 0.

## Метаданные AutoFix

У каждой находки есть поле `autofix: llm | deterministic | none`. Оно говорит, можно ли автоматически подготовить
патч ([TEAM_FEATURES.md](TEAM_FEATURES.md#3-ai-autofix-патч-самопроверка-сканером-и-pull-request)):

| Категория | Значение |
| --- | --- |
| SCA `known-vulnerable-dependency` | `deterministic`: обновление версии до ближайшей исправленной в месте определения + lockfile. |
| SECRET (все классы, кроме `private-key`) | `llm`: вынос значения в переменную окружения без значения по умолчанию. |
| SECRET `private-key` | `none`: файл ключа удаляют и перевыпускают ключ, точечный патч невозможен. |
| SAST `unsafe-deserialization`, `csrf-disabled` | `none`: архитектурное решение (формат сериализации, модель CSRF приложения). |
| Остальные SAST-правила | `llm`. |

Покрытие («AutoFix доступен для N из M правил») считается из этих таблиц (`app/autofix/coverage.py`).

## Diff-aware и Security Score

- Классификация находок на `new`/`existing` относительно base-ветки (hunks, переименования, whitespace, SCA по
  координатам и advisory, межфайловые находки) описана в [TEAM_FEATURES.md, раздел 1](TEAM_FEATURES.md).
- Security Score использует `severity`, `confidence` (порог 0.6, как у официальной выгрузки) и `diff_status`
  (новизна ×1.5) — [раздел 2](TEAM_FEATURES.md).
