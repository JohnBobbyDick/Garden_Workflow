import json
import os
import sys

BASE = str(__import__("pathlib").Path(__file__).resolve().parents[1])
DB = json.load(open("/Users/whoisniknek/PycharmProjects/Lampochki_CG/fixtures/organizer-training/vulnerability-database/vulnerabilities.json"))["vulnerabilities"]


def vkey(v):
    return [int(x) for x in v.split(".")]


def cmp(a, b):
    a, b = vkey(a), vkey(b)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return (a > b) - (a < b)


def in_range(v, r):
    if r["lower"] is not None:
        c = cmp(v, r["lower"])
        if c < 0 or (c == 0 and not r["lowerInclusive"]):
            return False
    if r["upper"] is not None:
        c = cmp(v, r["upper"])
        if c > 0 or (c == 0 and not r["upperInclusive"]):
            return False
    return True


def advisories(group, artifact, version):
    out = []
    for e in DB:
        if e["group"] == group and e["artifact"] == artifact and any(in_range(version, r) for r in e["ranges"]):
            cves = [a for a in e["aliases"] if a.startswith("CVE-")]
            out.append((cves[0] if cves else e["id"], e))
    return out


class Mutant:
    def __init__(self, name):
        self.name = name
        self.root = os.path.join(BASE, name, "project")
        self.findings = []
        self.controls = []

    def line(self, path, needle, nth=None):
        hits = [i + 1 for i, l in enumerate(open(os.path.join(self.root, path), encoding="utf-8").read().split("\n")) if needle in l]
        if len(hits) < (nth or 1):
            sys.exit(f"[{self.name}] needle not found in {path}: {needle!r}")
        if nth is None and len(hits) > 1:
            sys.exit(f"[{self.name}] needle not unique in {path}: {needle!r} -> {hits}")
        return hits[(nth or 1) - 1]

    def loc(self, path, start, end=None, end_nth=None):
        l1 = self.line(path, start)
        l2 = self.line(path, end, end_nth) if end else l1
        assert l1 <= l2 <= l1 + 14, (self.name, path, start, end, l1, l2)
        return {"path": path, "line": l1, "endLine": l2}

    def add(self, fid, category, cls, loc, desc, alts=(), severity=None):
        f = {"id": fid, "category": category, "class": cls}
        if severity:
            f["severity"] = severity
        f.update(loc)
        f["alternateLocations"] = list(alts)
        f["description"] = desc
        self.findings.append(f)

    def sca(self, prefix, group, artifact, version, loc, desc, alts=()):
        hits = advisories(group, artifact, version)
        assert hits, (group, artifact, version)
        for i, (adv, e) in enumerate(hits):
            fid = prefix if len(hits) == 1 else f"{prefix}{chr(ord('a') + i)}"
            f = {"id": fid, "category": "SCA", "class": "known-vulnerable-dependency", "severity": e["severity"]}
            f.update(loc)
            f["alternateLocations"] = list(alts)
            f.update({"group": group, "artifact": artifact, "version": version, "advisoryId": adv,
                      "advisoryIds": [adv, e["id"]] if adv != e["id"] else [adv], "description": desc})
            self.findings.append(f)

    def ctrl(self, cid, category, cls, loc, desc, **extra):
        c = {"id": cid, "category": category, "class": cls}
        c.update(loc)
        c.update(extra)
        c["description"] = desc
        self.controls.append(c)

    def ctrl_sca(self, cid, group, artifact, version, loc, desc):
        assert not advisories(group, artifact, version), (group, artifact, version)
        self.ctrl(cid, "SCA", "known-vulnerable-dependency", loc, desc, group=group, artifact=artifact, version=version)

    def write(self):
        out = {"dataset": self.name, "formatVersion": 1, "findings": self.findings, "controls": self.controls}
        with open(os.path.join(BASE, self.name, "expected.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(self.name, "findings:", len(self.findings), "controls:", len(self.controls))


def lockfile_versions(m):
    p = os.path.join(m.root, "gradle.lockfile")
    if not os.path.exists(p):
        return
    for raw in open(p):
        raw = raw.strip()
        if not raw or raw.startswith("#") or raw.startswith("empty="):
            continue
        coord = raw.split("=")[0]
        g, a, v = coord.split(":")
        hits = advisories(g, a, v)
        if hits:
            print("   lockfile vulnerable:", coord, [h[0] for h in hits])


# --------------------------------------------------------------------------- library-loans
m = Mutant("library-loans")
K = "src/main/kotlin/net/shelfline/loans/"
B = "build.gradle.kts"
m.add("LL-SEC-01", "SECRET", "password", m.loc(K + "partners/ArchiveDbSettings.kt", 'private val dbPass ='),
      "`partners/ArchiveDbSettings.kt`, свойство `dbPass` содержит встроенный пароль учётной записи `archive_reader`, который передаётся в `DriverManagerDataSource` архивной БД.", severity="HIGH")
m.add("LL-SEC-02", "SECRET", "api-key", m.loc(K + "partners/IsbnLookupClient.kt", 'private val lookupKey ='),
      "`partners/IsbnLookupClient.kt`, строковый `lookupKey` записывается в карту заголовков как `headers[\"X-Api-Key\"]` и уходит партнёрскому ISBN-сервису.",
      alts=[m.loc(K + "partners/IsbnLookupClient.kt", 'headers["X-Api-Key"] = lookupKey')], severity="MEDIUM")
m.add("LL-SEC-03", "SECRET", "configuration-token", m.loc("src/main/resources/application.yml", "authorization: Bearer"),
      "`application.yml`, `catalog-sync.partner.authorization` хранит готовую строку `Bearer …` без кавычек; `CatalogSyncHook` подставляет её в заголовок `Authorization`.",
      alts=[m.loc(K + "partners/CatalogSyncHook.kt", "catalog-sync.partner.authorization")], severity="HIGH")
m.add("LL-SEC-04", "SECRET", "secret-fallback", m.loc(K + "partners/ReminderGateway.kt", 'System.getProperty("shelfline.reminder.token"'),
      "`partners/ReminderGateway.kt`, `System.getProperty(\"shelfline.reminder.token\", \"…\")` задаёт встроенный токен по умолчанию для сервиса напоминаний; он уходит в `Authorization: Bearer`.", severity="LOW")
m.add("LL-SEC-05", "SECRET", "recoverable-token", m.loc(K + "partners/InterlibraryClient.kt", "val bearer = StringBuilder()", "headers.setBearerAuth(bearer)"),
      "`partners/InterlibraryClient.kt`, три литерала склеиваются цепочкой `StringBuilder().append(...)` и передаются в `setBearerAuth` для межбиблиотечного обмена.", severity="MEDIUM")

m.sca("LL-SCA-01", "org.apache.commons", "commons-text", "1.8", m.loc(B, "commons-text:$templatingRelease"),
      "Версия commons-text задана локальной переменной `templatingRelease = \"1.8\"` и подставлена в шаблон координат.",
      alts=[m.loc(B, 'val templatingRelease = "1.8"')])
m.sca("LL-SCA-02", "org.jsoup", "jsoup", "1.12.2", m.loc(B, "org.jsoup:jsoup:$jsoupVersion"),
      "Версия jsoup берётся из `gradle.properties` через делегат `val jsoupVersion: String by project`.",
      alts=[m.loc(B, "val jsoupVersion: String by project"), m.loc("gradle.properties", "jsoupVersion=")])
m.sca("LL-SCA-03", "commons-net", "commons-net", "3.6", m.loc(B, 'commons-net:commons-net:${extra["ftpClientLine"]}'),
      "Версия commons-net задана через `extra[\"ftpClientLine\"] = \"3.6\"` и подставлена шаблоном `${extra[...]}`.",
      alts=[m.loc(B, 'extra["ftpClientLine"] = "3.6"')])
m.sca("LL-SCA-04", "net.minidev", "json-smart", "2.4.7", m.loc(B, "implementation(libs.json.smart)"),
      "Зависимость объявлена через version catalog `libs.json.smart`; версия `jsonSmart = \"2.4.7\"` в `gradle/libs.versions.toml`.",
      alts=[m.loc("gradle/libs.versions.toml", 'jsonSmart = "2.4.7"'), m.loc("gradle/libs.versions.toml", "json-smart = {")])
m.sca("LL-SCA-05", "org.mybatis", "mybatis", "3.5.4", m.loc(B, "org.mybatis:mybatis:3.5.5"),
      "В `build.gradle.kts` объявлена 3.5.5, но `gradle.lockfile` фиксирует 3.5.4 — по правилам отчёта версия берётся из lockfile.",
      alts=[m.loc("gradle.lockfile", "org.mybatis:mybatis:3.5.4")])

m.add("LL-SAST-01", "SAST", "sql-injection", m.loc(K + "catalog/TitleRepository.kt", "fun searchByAuthor(", "return jdbc.queryForList(query)"),
      "`catalog/TitleRepository.kt`, `searchByAuthor`. `@RequestParam author` из `TitleSearchController.byAuthor` через `TitleSearchService.authorMatches` попадает в `String.format` с SQL-шаблоном и затем в `JdbcTemplate.queryForList`.",
      alts=[m.loc(K + "catalog/TitleSearchController.kt", "fun byAuthor("), m.loc(K + "catalog/TitleSearchService.kt", "fun authorMatches(", "return repository.searchByAuthor(normalized)")], severity="HIGH")
m.add("LL-SAST-02", "SAST", "tls-verification", m.loc(K + "partners/LegacyMirrorConnector.kt", "val trustEverything = object : X509TrustManager", "connection.sslSocketFactory = context.socketFactory"),
      "`partners/LegacyMirrorConnector.kt`, `open`. Анонимный `X509TrustManager` с пустым `checkServerTrusted` установлен в `SSLContext`, его фабрика сокетов назначена `HttpsURLConnection` — цепочка сертификатов не проверяется.",
      alts=[m.loc(K + "partners/LegacyMirrorConnector.kt", "override fun checkServerTrusted")], severity="MEDIUM")
m.add("LL-SAST-03", "SAST", "credentialed-cors", m.loc(K + "config/BrowserAccessConfig.kt", 'registry.addMapping("/api/members/**")', ".allowCredentials(true)"),
      "`config/BrowserAccessConfig.kt`, `addCorsMappings`. Для `/api/members/**` (данные читателя, выдачи) заданы `allowedOriginPatterns(\"*\")` и `allowCredentials(true)` — любой origin получает ответы с cookie сессии.", severity="MEDIUM")
m.add("LL-SAST-04", "SAST", "route-authorization", m.loc(K + "config/DeskSecurityConfig.kt", 'authorize(HttpMethod.GET, "/api/desk/overdue/export", permitAll)'),
      "`config/DeskSecurityConfig.kt`, Kotlin DSL `authorizeHttpRequests`. `permitAll` на `GET /api/desk/overdue/export` стоит перед правилом `/api/desk/**` с ролью `LIBRARIAN`; `OverdueReportController.exportOverdue` отдаёт логины и домашние адреса должников без аутентификации.",
      alts=[m.loc(K + "desk/OverdueReportController.kt", '@GetMapping("/overdue/export")', "fun exportOverdue()")], severity="HIGH")
m.add("LL-SAST-05", "SAST", "object-authorization", m.loc(K + "loans/LoanRepository.kt", "fun loadById(", 'WHERE loan_id = ?", mapper, loanId)'),
      "`loans/MemberLoanController.kt`, `loan`, → `LoanService.details` → `LoanRepository.loadById`. `GET /api/members/me/loans/{loanId}` выбирает выдачу только по ID; в таблице `loan` есть владелец `member_login`, но принципал не сверяется.",
      alts=[m.loc(K + "loans/MemberLoanController.kt", "fun loan(", "ResponseEntity.ofNullable(service.details(loanId))"), m.loc(K + "loans/LoanService.kt", "fun details(")], severity="HIGH")

m.ctrl("LL-CTRL-01", "SECRET", "api-key", m.loc("README.md", "YOUR_API_KEY"), "Плейсхолдер `YOUR_API_KEY` в документации, приложение его не читает.")
m.ctrl("LL-CTRL-02", "SECRET", "configuration-token", m.loc("src/main/resources/application.yml", "${CATALOG_MIRROR_TOKEN}"), "Ссылка на переменную окружения без значения по умолчанию.")
m.ctrl_sca("LL-CTRL-03", "org.apache.commons", "commons-lang3", "3.18.0", m.loc(B, "commons-lang3:3.18.0"), "Версия 3.18.0 — первая исправленная (верхняя граница диапазона исключена).")
m.ctrl("LL-CTRL-04", "SAST", "sql-injection", m.loc(K + "catalog/TitleRepository.kt", "fun searchByIsbn(", 'WHERE isbn = ?", isbn)'), "Параметризованный запрос с `?` рядом с уязвимым.")
m.ctrl("LL-CTRL-05", "SAST", "route-authorization", m.loc(K + "config/DeskSecurityConfig.kt", 'authorize("/assets/**", permitAll)'), "Публичная статика (`static/assets`), без персональных данных.")
m.ctrl("LL-CTRL-06", "SAST", "tls-verification", m.loc(K + "partners/OpenCatalogClient.kt", "private val http: HttpClient", "HttpResponse.BodyHandlers.ofByteArray()"), "Обычный HTTPS-клиент со штатной проверкой сертификатов.")
m.ctrl("LL-CTRL-07", "SAST", "object-authorization", m.loc(K + "loans/LoanRepository.kt", "fun loadOwned(", "AND member_login = ?"), "Выборка по `loan_id` и `member_login` из `principal.name` (`MemberLoanController.receipt`).")
lockfile_versions(m)
m.write()

# --------------------------------------------------------------------------- clinic-appointments
m = Mutant("clinic-appointments")
K = "src/main/kotlin/com/medibook/clinic/"
P = "src/main/resources/application.properties"
m.add("CA-SEC-01", "SECRET", "password", m.loc(K + "integrations/ClinicAdminConsole.kt", "const val adminSecretPassword ="),
      "`integrations/ClinicAdminConsole.kt`, `const val adminSecretPassword` в `companion object` — пароль администратора консоли аудита, уходит в Basic-авторизацию.",
      alts=[m.loc(K + "integrations/ClinicAdminConsole.kt", "Credentials.basic(ADMIN_LOGIN, adminSecretPassword)")], severity="HIGH")
m.add("CA-SEC-02", "SECRET", "api-key", m.loc(K + "integrations/LabOrderClient.kt", 'private val labKey ='),
      "`integrations/LabOrderClient.kt`, строковый `labKey` попадает в заголовок через пару `\"X-Api-Key\" to labKey` и `headers(map.toHeaders())`.",
      alts=[m.loc(K + "integrations/LabOrderClient.kt", '"X-Api-Key" to labKey')], severity="MEDIUM")
m.add("CA-SEC-03", "SECRET", "configuration-token", m.loc(P, "insurance.gateway.authorization="),
      "`application.properties`, `insurance.gateway.authorization` хранит литерал `Bearer …` для шлюза страховых заявок; `InsuranceClaims` ставит его в `Authorization`.", severity="HIGH")
m.add("CA-SEC-04", "SECRET", "secret-fallback", m.loc(K + "integrations/SmsReminderSender.kt", "sms.gateway.token:"),
      "`integrations/SmsReminderSender.kt`, `@Value(\"${sms.gateway.token:…}\")` содержит встроенный токен SMS-шлюза как значение по умолчанию (в properties ключа нет — используется именно он).", severity="LOW")
m.add("CA-SEC-05", "SECRET", "recoverable-token", m.loc(K + "integrations/RadiologyArchiveClient.kt", "val accessToken = listOf(", '.header("Authorization", "Bearer $accessToken")'),
      "`integrations/RadiologyArchiveClient.kt`, токен архива снимков собирается `listOf(...).joinToString(\"\")` из трёх литералов и ставится в `Authorization: Bearer`.", severity="MEDIUM")

B = "build.gradle.kts"
m.sca("CA-SCA-01", "org.apache.commons", "commons-compress", "1.21", m.loc(B, "commons-compress:$compressRev"),
      "Версия commons-compress из локальной переменной `compressRev = \"1.21\"`.", alts=[m.loc(B, 'val compressRev = "1.21"')])
m.sca("CA-SCA-02", "commons-io", "commons-io", "2.11.0", m.loc(B, 'commons-io:commons-io:" + extra["ioLine"]'),
      "Версия commons-io задана `extra[\"ioLine\"] = \"2.11.0\"` и приклеена к координатам конкатенацией `+`.", alts=[m.loc(B, 'extra["ioLine"] = "2.11.0"')])
m.sca("CA-SCA-03", "org.apache.poi", "poi-ooxml", "5.2.3", m.loc(B, "poi-ooxml:$poiVersion"),
      "Версия poi-ooxml берётся из `gradle.properties` (`poiVersion=5.2.3`) через `by project`.",
      alts=[m.loc(B, "val poiVersion: String by project"), m.loc("gradle.properties", "poiVersion=")])
m.sca("CA-SCA-04", "org.apache.commons", "commons-configuration2", "2.7", m.loc(B, "implementation(libs.commons.configuration2)"),
      "Зависимость из version catalog `libs.commons.configuration2`, версия `configuration = \"2.7\"`.",
      alts=[m.loc("gradle/libs.versions.toml", 'configuration = "2.7"'), m.loc("gradle/libs.versions.toml", "commons-configuration2 = {")])

m.add("CA-SAST-01", "SAST", "sql-injection", m.loc(K + "schedule/ScheduleDao.kt", "fun slotsForDoctor(", "return jdbc.query(sql.toString(), slotMapper)"),
      "`schedule/ScheduleDao.kt`, `slotsForDoctor`. `@RequestParam doctor` из `ScheduleController.freeSlots` через `ScheduleService` дописывается `StringBuilder.append` в SQL и выполняется `JdbcTemplate.query`.",
      alts=[m.loc(K + "schedule/ScheduleController.kt", "fun freeSlots("), m.loc(K + "schedule/ScheduleService.kt", "fun openSlotsFor(")], severity="HIGH")
m.add("CA-SAST-02", "SAST", "tls-verification", m.loc(K + "integrations/LabResultsFeed.kt", ".hostnameVerifier { _, _ -> true }"),
      "`integrations/LabResultsFeed.kt`, OkHttp-клиент лабораторных результатов собран с `.hostnameVerifier { _, _ -> true }` — проверка имени хоста отключена.", severity="MEDIUM")
m.add("CA-SAST-03", "SAST", "credentialed-cors", m.loc(K + "security/PatientPortalCors.kt", 'portal.addAllowedOriginPattern("*")', "portal.allowCredentials = true"),
      "`security/PatientPortalCors.kt`, `corsConfigurationSource`. `addAllowedOriginPattern(\"*\")` вместе с `allowCredentials = true` для `/api/patients/**` (визиты, диагнозы).", severity="MEDIUM")
m.add("CA-SAST-04", "SAST", "route-authorization", m.loc(K + "security/FrontDeskSecurity.kt", '.antMatchers(HttpMethod.GET, "/api/front-desk/day-sheet").permitAll()'),
      "`security/FrontDeskSecurity.kt`, `authorizeRequests().antMatchers(...)`. `permitAll` на `GET /api/front-desk/day-sheet` предшествует `/api/front-desk/**` с ролью `RECEPTION`; `DaySheetController.daySheet` отдаёт имена и телефоны пациентов анонимно.",
      alts=[m.loc(K + "frontdesk/DaySheetController.kt", '@GetMapping("/day-sheet")', "fun daySheet()")], severity="HIGH")
m.add("CA-SAST-05", "SAST", "object-authorization", m.loc(K + "visits/VisitDao.kt", "fun byId(", ").firstOrNull()", end_nth=2),
      "`visits/PatientVisitController.kt`, `visit`, → `VisitService.open` → `VisitDao.byId`. `GET /api/patients/self/visits/{visitId}` принимает `Principal`, но использует его только в логе; запрос фильтрует лишь `visit_id`, владелец `patient_login` не проверяется.",
      alts=[m.loc(K + "visits/PatientVisitController.kt", "fun visit(", "return visits.open(visitId)"), m.loc(K + "visits/VisitService.kt", "fun open(")], severity="HIGH")
m.add("CA-SAST-06", "SAST", "csrf-disabled", m.loc(K + "security/FrontDeskSecurity.kt", "http.csrf().disable()"),
      "CSRF-защита отключена (`http.csrf().disable()`) при аутентификации httpBasic: браузер автоматически отправляет сохранённые учётные данные, поэтому межсайтовые запросы проходят.",
      severity="MEDIUM")

m.ctrl("CA-CTRL-01", "SECRET", "api-key", m.loc("README.md", "YOUR_API_KEY"), "Плейсхолдер в README, не читается приложением.")
m.ctrl("CA-CTRL-02", "SECRET", "configuration-token", m.loc(P, "pharmacy.api.token="), "`${PHARMACY_API_TOKEN}` без значения по умолчанию.")
m.ctrl_sca("CA-CTRL-03", "org.jsoup", "jsoup", "1.15.3", m.loc(B, "org.jsoup:jsoup:1.15.3"), "jsoup 1.15.3 выше границы 1.14.2.")
m.ctrl_sca("CA-CTRL-04", "org.apache.httpcomponents", "httpclient", "4.5.13", m.loc(B, "httpclient:4.5.13"), "Ровно исправленная версия 4.5.13 (граница исключена).")
m.ctrl_sca("CA-CTRL-05", "org.json", "json", "20231013", m.loc(B, "org.json:json:20231013"), "Исправленная версия org.json.")
m.ctrl("CA-CTRL-06", "SAST", "sql-injection", m.loc(K + "schedule/ScheduleDao.kt", "fun slotsForRoom(", "WHERE room_code = ?"), "Параметризованный запрос рядом с уязвимым.")
m.ctrl("CA-CTRL-07", "SAST", "route-authorization", m.loc(K + "security/FrontDeskSecurity.kt", '.antMatchers("/favicon.ico", "/public/**").permitAll()'), "Публичная статика (часы работы).")
m.ctrl("CA-CTRL-08", "SAST", "tls-verification", m.loc(K + "integrations/PharmacyClient.kt", "private val client = OkHttpClient.Builder()", ".build()", end_nth=1), "OkHttp-клиент со штатной проверкой TLS.")
m.ctrl("CA-CTRL-09", "SAST", "object-authorization", m.loc(K + "visits/VisitDao.kt", "fun byIdForPatient(", ").firstOrNull()", end_nth=1), "Выборка по `visit_id` и `patient_login = principal.name`.")
m.write()

# --------------------------------------------------------------------------- parcel-lockers
m = Mutant("parcel-lockers")
K = "src/main/kotlin/io/lockerhub/parcels/"
Y = "src/main/resources/application.yml"
B = "build.gradle.kts"
m.add("PL-SEC-01", "SECRET", "password", m.loc(K + "outbound/LockerFirmwareSettings.kt", "var maintenancePasswd"),
      "`outbound/LockerFirmwareSettings.kt`, `maintenancePasswd` — встроенный пароль сервисной консоли прошивки шкафчиков.", severity="HIGH")
m.add("PL-SEC-02", "SECRET", "api-key", m.loc(K + "outbound/RoutingPartnerClient.kt", 'headers["X-Api-Key"] ='),
      "`outbound/RoutingPartnerClient.kt`, литерал ключа присваивается прямо `headers[\"X-Api-Key\"]` и уходит партнёру маршрутизации.", severity="MEDIUM")
m.add("PL-SEC-03", "SECRET", "configuration-token", m.loc(Y, "authorization: Bearer"),
      "`application.yml`, `courier-webhooks.outbound.authorization` содержит литерал `Bearer …`; `CourierWebhookPublisher` кладёт его в `Authorization`.", severity="HIGH")
m.add("PL-SEC-04", "SECRET", "secret-fallback", m.loc(K + "outbound/TelemetryUplink.kt", 'env["LOCKERHUB_TELEMETRY_TOKEN"] ?:'),
      "`outbound/TelemetryUplink.kt`, `System.getenv()` сохраняется в `env`, затем `env[\"LOCKERHUB_TELEMETRY_TOKEN\"] ?: \"…\"` подставляет встроенный токен телеметрии.", severity="LOW")
m.add("PL-SEC-05", "SECRET", "recoverable-token", m.loc(K + "outbound/CarrierLabelClient.kt", 'val prefix = "', "setBearerAuth(credential)"),
      "`outbound/CarrierLabelClient.kt`, два локальных литерала собираются `\"%s%s\".format(prefix, body)` и передаются в `setBearerAuth`.", severity="MEDIUM")

m.sca("PL-SCA-01", "com.thoughtworks.xstream", "xstream", "1.4.17", m.loc(B, "xstream:$xmlBridgeVersion"),
      "Версия xstream из локальной переменной `xmlBridgeVersion = \"1.4.17\"`; этой версии соответствуют две записи справочника.",
      alts=[m.loc(B, 'val xmlBridgeVersion = "1.4.17"')])
m.sca("PL-SCA-02", "org.apache.pdfbox", "pdfbox", "2.0.23", m.loc(B, 'pdfbox:${extra["pdfLine"]}'),
      "Версия pdfbox задана `extra[\"pdfLine\"] = \"2.0.23\"`; 2.0.23 вне диапазонов `<2.0.23`, но внутри `[2.0.0, 2.0.24)`.",
      alts=[m.loc(B, 'extra["pdfLine"] = "2.0.23"')])
m.sca("PL-SCA-03", "org.apache.httpcomponents", "httpclient", "4.5.12", m.loc(B, "httpclient:$httpClientVersion"),
      "Версия httpclient из `gradle.properties` (`httpClientVersion=4.5.12`) через `by project`.",
      alts=[m.loc(B, "val httpClientVersion: String by project"), m.loc("gradle.properties", "httpClientVersion=")])
m.sca("PL-SCA-04", "commons-fileupload", "commons-fileupload", "1.4", m.loc(B, "implementation(libs.commons.fileupload)"),
      "Зависимость из version catalog `libs.commons.fileupload` (`fileupload = \"1.4\"`, запись с `group`/`name`).",
      alts=[m.loc("gradle/libs.versions.toml", 'fileupload = "1.4"'), m.loc("gradle/libs.versions.toml", "commons-fileupload = {")])
m.sca("PL-SCA-05", "com.google.code.gson", "gson", "2.8.8", m.loc(B, "com.google.code.gson:gson:2.10.1"),
      "Объявлена безопасная 2.10.1, но `gradle.lockfile` фиксирует 2.8.8 — версия берётся из lockfile.",
      alts=[m.loc("gradle.lockfile", "com.google.code.gson:gson:2.8.8")])

m.add("PL-SAST-01", "SAST", "sql-injection", m.loc(K + "stations/StationRepository.kt", "fun lockersAtStation(", "return jdbc.queryForList(sql)"),
      "`stations/StationRepository.kt`, `lockersAtStation`. `@RequestParam station` из `CourierRouteController.stationLockers` через `RoutePlanner.lockersAt` склеивается `+` в SQL и выполняется `queryForList`.",
      alts=[m.loc(K + "stations/CourierRouteController.kt", "fun stationLockers("), m.loc(K + "stations/RoutePlanner.kt", "fun lockersAt(", "return stations.lockersAtStation(code)")], severity="HIGH")
m.add("PL-SAST-02", "SAST", "tls-verification", m.loc(K + "outbound/PermissiveTrust.kt", "internal class PermissiveTrust : X509TrustManager", "override fun checkServerTrusted"),
      "`outbound/PermissiveTrust.kt`, `checkServerTrusted(...) = Unit` принимает любую цепочку; `CourierTrackingClient` ставит этот менеджер в `SSLContext` своего `HttpClient`.",
      alts=[m.loc(K + "outbound/CourierTrackingClient.kt", ".sslContext(SSLContext.getInstance")], severity="MEDIUM")
m.add("PL-SAST-03", "SAST", "credentialed-cors", m.loc(K + "web/RecipientAppCors.kt", 'recipientApp.setAllowedOriginPatterns(listOf("*"))', "recipientApp.setAllowCredentials(true)"),
      "`web/RecipientAppCors.kt`, `setAllowedOriginPatterns(listOf(\"*\"))` + `setAllowCredentials(true)`; лямбда-`CorsConfigurationSource` применяет их к `/api/my/**` (посылки и коды получения).", severity="MEDIUM")
m.add("PL-SAST-04", "SAST", "route-authorization", m.loc(K + "web/AccessRules.kt", '.requestMatchers("/api/ops/stations/*/door-codes").permitAll()'),
      "`web/AccessRules.kt`, `permitAll` на `/api/ops/stations/*/door-codes` стоит раньше `/api/ops/**` с ролями `OPERATOR`/`ADMIN`; `StationServiceController.doorCodes` анонимно отдаёт коды дверей ячеек.",
      alts=[m.loc(K + "ops/StationServiceController.kt", '@GetMapping("/{stationCode}/door-codes")', "fun doorCodes(")], severity="HIGH")
m.add("PL-SAST-05", "SAST", "object-authorization", m.loc(K + "parcels/ParcelRepository.kt", "fun findOne(", "WHERE parcel_id = :parcelId\", params"),
      "`parcels/MyParcelsController.kt`, `parcel`, → `ParcelService.lookup` → `ParcelRepository.findOne`. `GET /api/my/parcels/{parcelId}` читает посылку по одному именованному параметру `:parcelId`; колонка `owner_id` не сверяется с принципалом.",
      alts=[m.loc(K + "parcels/MyParcelsController.kt", "fun parcel(", "ResponseEntity.notFound().build()"), m.loc(K + "parcels/ParcelService.kt", "fun lookup(")], severity="HIGH")

m.ctrl("PL-CTRL-01", "SECRET", "api-key", m.loc("README.md", "YOUR_API_KEY"), "Плейсхолдер в README.")
m.ctrl("PL-CTRL-02", "SECRET", "configuration-token", m.loc(Y, "${ROUTING_SIGNING_TOKEN}"), "Ссылка на переменную окружения без встроенного значения.")
m.ctrl("PL-CTRL-03", "SCA", "known-vulnerable-dependency", m.loc(B, "commons-lang3:3.12.0"),
       "Объявлена уязвимая 3.12.0, но `gradle.lockfile` фиксирует 3.18.0 (исправленную) — находки нет.",
       group="org.apache.commons", artifact="commons-lang3", version="3.18.0")
assert not advisories("org.apache.commons", "commons-lang3", "3.18.0")
m.ctrl("PL-CTRL-04", "SAST", "sql-injection", m.loc(K + "stations/StationRepository.kt", "fun lockersBySize(", "sizeClass,"), "Параметризованный запрос рядом с уязвимым.")
m.ctrl("PL-CTRL-05", "SAST", "route-authorization", m.loc(K + "web/AccessRules.kt", '"/index.html", "/favicon.ico").permitAll()'), "Публичная статическая главная страница.")
m.ctrl("PL-CTRL-06", "SAST", "tls-verification", m.loc(K + "outbound/StationMapClient.kt", "private val http: HttpClient", ".build()", end_nth=1), "Штатный HTTPS-клиент.")
m.ctrl("PL-CTRL-07", "SAST", "object-authorization", m.loc(K + "parcels/ParcelRepository.kt", "fun findOwned(", "AND owner_id = :ownerId"), "Выборка с фильтром `owner_id = principal.name`.")
lockfile_versions(m)
m.write()
