from pathlib import Path

import pytest

from app.analyzers.sast.detector import SastConfig, scan_sast


def scan(tmp_path: Path, files: dict[str, str], **cfg):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return scan_sast(tmp_path, SastConfig(**cfg))


def of(findings, cls):
    return [f for f in findings if f.cls == cls]


CTL_HEAD = """package demo
import org.springframework.web.bind.annotation.*
import org.springframework.jdbc.core.JdbcTemplate
"""

# ---------------------------------------------------------------- sql-injection


def test_sqli_template_in_handler_and_parameterized_neighbour_is_safe(tmp_path):
    src = CTL_HEAD + """
@RestController
@RequestMapping("/api/items")
class ItemCtl(private val jdbc: JdbcTemplate) {
    @GetMapping("/by-tag")
    fun byTag(@RequestParam tag: String): List<String> =
        jdbc.queryForList("SELECT code FROM item WHERE tag = '$tag'", String::class.java)

    @GetMapping("/by-code")
    fun byCode(@RequestParam code: String): List<String> =
        jdbc.queryForList("SELECT code FROM item WHERE code = ?", String::class.java, code)
}
"""
    fs = of(scan(tmp_path, {"src/ItemCtl.kt": src}), "sql-injection")
    assert [(f.line, f.end_line) for f in fs] == [(9, 10)]


def test_sqli_string_format_through_service_and_repository(tmp_path):
    files = {
        "src/A.kt": CTL_HEAD + """
@RestController
class SearchCtl(private val svc: SearchService) {
    @GetMapping("/api/search")
    fun search(@RequestParam("q") query: String) = svc.find(query)
}
""",
        "src/B.kt": """package demo
import org.springframework.stereotype.Service
@Service
class SearchService(private val repo: SearchRepo) {
    fun find(term: String): List<String> = repo.lookup(term.trim())
}
""",
        "src/C.kt": """package demo
import org.springframework.jdbc.core.JdbcTemplate
class SearchRepo(private val jdbc: JdbcTemplate) {
    fun lookup(value: String): List<String> {
        val sql = String.format("SELECT name FROM t WHERE name LIKE '%%%s%%'", value)
        return jdbc.queryForList(sql, String::class.java)
    }
}
""",
    }
    fs = of(scan(tmp_path, files), "sql-injection")
    assert [(f.path, f.line, f.end_line) for f in fs] == [("src/C.kt", 5, 6)]


def test_sqli_numeric_param_and_constant_interpolation_safe(tmp_path):
    src = CTL_HEAD + """
const val TABLE = "item"
@RestController
class C(private val jdbc: JdbcTemplate) {
    @GetMapping("/a/{id}")
    fun a(@PathVariable id: Long) = jdbc.queryForList("SELECT * FROM $TABLE WHERE id = $id")
    @GetMapping("/b")
    fun b(@RequestParam name: String) = jdbc.query("SELECT * FROM item WHERE name = :n", mapOf("n" to name)) { r, _ -> r.getString(1) }
}
"""
    assert of(scan(tmp_path, {"src/C.kt": src}), "sql-injection") == []


def test_sqli_entity_manager_concat_and_string_builder(tmp_path):
    src = CTL_HEAD + """
@RestController
class C(private val em: EntityManager) {
    @PostMapping("/x")
    fun x(@RequestBody body: Filter): List<Any?> {
        val sb = StringBuilder("SELECT u FROM User u WHERE u.name = '")
        sb.append(body.name).append("'")
        return em.createQuery(sb.toString()).resultList
    }
    @GetMapping("/y")
    fun y(req: HttpServletRequest) = em.createNativeQuery("DELETE FROM t WHERE k = " + req.getParameter("k")).executeUpdate()
}
"""
    fs = of(scan(tmp_path, {"src/C.kt": src}), "sql-injection")
    assert sorted((f.line, f.end_line) for f in fs) == [(9, 11), (14, 14)]


# ---------------------------------------------------------------- tls-verification


@pytest.mark.parametrize("snippet,line", [
    ("conn.hostnameVerifier = HostnameVerifier { _, _ -> true }", 6),
    ("conn.setHostnameVerifier { _, _ -> true }", 6),
    ("HttpsURLConnection.setDefaultHostnameVerifier(NoopHostnameVerifier.INSTANCE)", 6),
    ("val b = OkHttpClient.Builder().hostnameVerifier { _, _ -> true }", 6),
])
def test_tls_hostname_verifier_variants(tmp_path, snippet, line):
    src = f"package d\nimport javax.net.ssl.*\nclass S {{\n    fun c(conn: HttpsURLConnection) {{\n        val x = 1\n        {snippet}\n    }}\n}}\n"
    fs = of(scan(tmp_path, {"src/S.kt": src}), "tls-verification")
    assert [f.line for f in fs] == [line]


def test_tls_trust_all_manager(tmp_path):
    src = """package d
import javax.net.ssl.*
import java.security.cert.X509Certificate
class TrustAll : X509TrustManager {
    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
    override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
}
"""
    fs = of(scan(tmp_path, {"src/T.kt": src}), "tls-verification")
    assert [f.line for f in fs] == [6]


def test_tls_safe_clients_and_real_verifier(tmp_path):
    src = """package d
import javax.net.ssl.*
class S {
    fun a() = URI("https://x.invalid").toURL().openConnection() as HttpsURLConnection
    fun b(c: HttpsURLConnection) { c.hostnameVerifier = HostnameVerifier { host, _ -> host == "api.example.org" } }
}
class Strict : X509TrustManager {
    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) { delegate.checkServerTrusted(chain, authType) }
    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) { throw CertificateException("no") }
    override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
}
"""
    assert of(scan(tmp_path, {"src/S.kt": src}), "tls-verification") == []


# ---------------------------------------------------------------- credentialed-cors


def test_cors_configuration_source_wildcard_with_credentials(tmp_path):
    src = """package d
class Cors {
    @Bean
    fun src(): UrlBasedCorsConfigurationSource {
        val c = CorsConfiguration().apply {
            allowedOriginPatterns = listOf("*")
            allowCredentials = true
        }
        return UrlBasedCorsConfigurationSource().apply { registerCorsConfiguration("/api/me", c) }
    }
}
"""
    fs = of(scan(tmp_path, {"src/Cors.kt": src}), "credentialed-cors")
    assert [(f.line, f.end_line) for f in fs] == [(6, 7)]


def test_cors_webmvc_configurer_registry_chain(tmp_path):
    src = """package d
class Web : WebMvcConfigurer {
    override fun addCorsMappings(registry: CorsRegistry) {
        registry.addMapping("/**")
            .allowedOrigins("*")
            .allowedMethods("GET", "POST")
            .allowCredentials(true)
    }
}
"""
    fs = of(scan(tmp_path, {"src/Web.kt": src}), "credentialed-cors")
    assert [(f.line, f.end_line) for f in fs] == [(5, 7)]


def test_cors_annotation(tmp_path):
    src = 'package d\n@RestController\n@CrossOrigin(origins = ["*"], allowCredentials = "true")\nclass C\n'
    assert [f.line for f in of(scan(tmp_path, {"src/C.kt": src}), "credentialed-cors")] == [3]


def test_cors_wildcard_without_credentials_or_specific_origin_is_safe(tmp_path):
    src = """package d
class Cors {
    fun a() = CorsConfiguration().apply { allowedOrigins = listOf("*"); allowCredentials = false }
    fun b() = CorsConfiguration().apply { allowedOrigins = listOf("https://app.example.org"); allowCredentials = true }
}
"""
    assert of(scan(tmp_path, {"src/Cors.kt": src}), "credentialed-cors") == []


# ---------------------------------------------------------------- route-authorization

SEC_FILES = {
    "src/Sec.kt": """package d
class Sec {
    @Bean
    fun chain(http: HttpSecurity): SecurityFilterChain = http
        .authorizeHttpRequests { r ->
            r.requestMatchers(GET, "/api/catalog/items").permitAll()
            r.requestMatchers(GET, "/api/orders/report").permitAll()
            r.requestMatchers("/api/orders/**").hasRole("STAFF")
            r.anyRequest().authenticated()
        }
        .build()
}
""",
    "src/Catalog.kt": """package d
@RestController
class Catalog {
    @GetMapping("/api/catalog/items")
    fun items() = listOf("a", "b")
}
""",
    "src/Report.kt": """package d
@RestController
@RequestMapping("/api/orders")
class Report(private val jdbc: JdbcTemplate) {
    @GetMapping("/report")
    fun report() = jdbc.queryForList("SELECT o.id, o.customer_email, o.total FROM orders o")
}
""",
}


def test_route_permit_all_on_sensitive_shadowed_route(tmp_path):
    fs = of(scan(tmp_path, SEC_FILES), "route-authorization")
    assert [(f.path, f.line) for f in fs] == [("src/Sec.kt", 7)]
    assert fs[0].alternate_locations[0].path == "src/Report.kt"


def test_route_rules_with_ant_matchers_in_other_order(tmp_path):
    files = dict(SEC_FILES)
    files["src/Sec.kt"] = """package d
class Sec : WebSecurityConfigurerAdapter() {
    override fun configure(http: HttpSecurity) {
        http.authorizeRequests()
            .antMatchers("/api/orders/**").hasRole("STAFF")
            .antMatchers("/api/catalog/**").permitAll()
            .anyRequest().authenticated()
    }
}
"""
    assert of(scan(tmp_path, files), "route-authorization") == []
    files["src/Sec.kt"] = files["src/Sec.kt"].replace(
        '.antMatchers("/api/orders/**").hasRole("STAFF")', '.antMatchers("/api/orders/report").permitAll()\n            .antMatchers("/api/orders/**").hasRole("STAFF")')
    fs = of(scan(tmp_path, files), "route-authorization")
    assert [f.line for f in fs] == [5]


def test_route_method_level_preauthorize_is_safe(tmp_path):
    files = dict(SEC_FILES)
    files["src/Report.kt"] = files["src/Report.kt"].replace('@GetMapping("/report")', '@PreAuthorize("hasRole(\'STAFF\')")\n    @GetMapping("/report")')
    assert of(scan(tmp_path, files), "route-authorization") == []


# ---------------------------------------------------------------- object-authorization

IDOR_FILES = {
    "src/OrderCtl.kt": """package d
@RestController
@RequestMapping("/api/customer")
class OrderCtl(private val svc: OrderService) {
    @GetMapping("/orders/{orderId}")
    fun get(@PathVariable orderId: Long): Order? =
        svc.load(orderId)

    @GetMapping("/orders")
    fun mine(principal: Principal) = svc.forOwner(principal.name)
}
""",
    "src/OrderService.kt": """package d
@Service
class OrderService(private val store: OrderStore) {
    fun load(id: Long): Order? = store.byId(id)
    fun forOwner(owner: String) = store.byOwner(owner)
}
""",
    "src/OrderStore.kt": """package d
data class Order(val id: Long, val ownerId: String, val total: Int)
@Repository
class OrderStore(private val jdbc: JdbcTemplate) {
    fun byId(id: Long): Order? = jdbc.query(
        "SELECT id, owner_id, total FROM orders WHERE id = ?",
        { r, _ -> Order(r.getLong(1), r.getString(2), r.getInt(3)) },
        id,
    ).firstOrNull()

    fun byOwner(owner: String): List<Order> = jdbc.query(
        "SELECT id, owner_id, total FROM orders WHERE owner_id = ?",
        { r, _ -> Order(r.getLong(1), r.getString(2), r.getInt(3)) },
        owner,
    )
}
""",
}


def test_idor_through_service_layer_reported_at_data_access(tmp_path):
    fs = of(scan(tmp_path, IDOR_FILES), "object-authorization")
    assert [(f.path, f.line) for f in fs] == [("src/OrderStore.kt", 5)]
    assert ("src/OrderCtl.kt", 6) in [(a.path, a.line) for a in fs[0].alternate_locations]


def test_idor_owner_filter_in_query_is_safe(tmp_path):
    files = dict(IDOR_FILES)
    files["src/OrderCtl.kt"] = files["src/OrderCtl.kt"].replace(
        "fun get(@PathVariable orderId: Long): Order? =\n        svc.load(orderId)",
        "fun get(@PathVariable orderId: Long, principal: Principal): Order? =\n        svc.loadOwned(orderId, principal.name)")
    files["src/OrderService.kt"] = files["src/OrderService.kt"].replace(
        "fun load(id: Long): Order? = store.byId(id)", "fun loadOwned(id: Long, who: String): Order? = store.byIdAndOwner(id, who)")
    files["src/OrderStore.kt"] = files["src/OrderStore.kt"].replace(
        'fun byId(id: Long): Order? = jdbc.query(\n        "SELECT id, owner_id, total FROM orders WHERE id = ?",',
        'fun byIdAndOwner(id: Long, owner: String): Order? = jdbc.query(\n        "SELECT id, owner_id, total FROM orders WHERE id = ? AND owner_id = ?",'
    ).replace("        id,\n    ).firstOrNull()", "        id, owner,\n    ).firstOrNull()")
    assert of(scan(tmp_path, files), "object-authorization") == []


def test_idor_ownership_check_after_load_is_safe(tmp_path):
    files = dict(IDOR_FILES)
    files["src/OrderCtl.kt"] = files["src/OrderCtl.kt"].replace(
        "fun get(@PathVariable orderId: Long): Order? =\n        svc.load(orderId)",
        "fun get(@PathVariable orderId: Long, auth: Authentication): Order? {\n        val o = svc.load(orderId) ?: return null\n"
        "        if (o.ownerId != auth.name) throw AccessDeniedException(\"no\")\n        return o\n    }")
    assert of(scan(tmp_path, files), "object-authorization") == []


def test_idor_spring_data_find_by_id(tmp_path):
    src = """package d
@RestController
class DocCtl(private val docs: DocRepository) {
    @GetMapping("/api/user/docs/{id}")
    fun doc(@PathVariable id: UUID) = docs.findById(id).orElseThrow()
}
interface DocRepository : JpaRepository<Doc, UUID>
@Entity
class Doc(@Id val id: UUID, val userId: String, val body: String)
"""
    fs = of(scan(tmp_path, {"src/D.kt": src}), "object-authorization")
    assert [f.line for f in fs] == [5]


# ---------------------------------------------------------------- rules 6-11


def test_extra_rules_positive(tmp_path):
    src = """package d
class X {
    fun users() = InMemoryUserDetailsManager(User.withUsername("admin").password("{noop}S3cret!pw").roles("ADMIN").build())
    fun de(input: InputStream) = ObjectInputStream(input).readObject()
    fun y(s: String) = Yaml().load<Any>(s)
    fun h(p: String) = MessageDigest.getInstance("MD5").digest(p.toByteArray())
    fun c() = Cipher.getInstance("DES/ECB/PKCS5Padding")
    fun t(): String { val token = java.util.Random().nextLong().toString(); return token }
}
@RestController
class F {
    @GetMapping("/files")
    fun read(@RequestParam name: String) = File("/data/" + name).readText()
    @GetMapping("/users/delete/{id}")
    fun del(@PathVariable id: Long) = repo.deleteById(id)
}
"""
    cls = {f.cls for f in scan(tmp_path, {"src/X.kt": src, "src/main/resources/application.properties":
                                           "management.endpoints.web.exposure.include=*\nspring.h2.console.enabled=true\n"})}
    assert {"hardcoded-credentials", "unsafe-deserialization", "weak-crypto", "path-traversal", "insecure-endpoint"} <= cls


def test_extra_rules_negative(tmp_path):
    src = """package d
class X {
    fun de(input: InputStream) = ObjectMapper().readValue(input, Dto::class.java)
    fun y(s: String) = Yaml(SafeConstructor(LoaderOptions())).load<Any>(s)
    fun h(p: String) = MessageDigest.getInstance("SHA-256").digest(p.toByteArray())
    fun c() = Cipher.getInstance("AES/GCM/NoPadding")
    fun t() = SecureRandom().nextLong()
    fun jitter() = java.util.Random().nextInt(100)
}
@RestController
class F {
    @GetMapping("/files")
    fun read(@RequestParam name: String): String {
        val p = base.resolve(name).normalize()
        require(p.startsWith(base))
        return Files.readString(p)
    }
}
"""
    assert scan(tmp_path, {"src/X.kt": src, "application.yml": "management:\n  endpoints:\n    web:\n      exposure:\n        include: health,info\n"}) == []


def test_rule_toggle_and_min_confidence(tmp_path):
    src = "package d\nclass S { fun c(conn: HttpsURLConnection) { conn.hostnameVerifier = HostnameVerifier { _, _ -> true } } }\n"
    assert scan(tmp_path, {"src/S.kt": src}, disabled_rules=["tls-verification"]) == []
    assert scan(tmp_path, {"src/S.kt": src}, min_confidence=0.99) == []


def test_idor_principal_only_logged_is_still_idor(tmp_path):
    files = dict(IDOR_FILES)
    files["src/OrderCtl.kt"] = files["src/OrderCtl.kt"].replace(
        "fun get(@PathVariable orderId: Long): Order? =\n        svc.load(orderId)",
        "fun get(@PathVariable orderId: Long, principal: Principal): Order? {\n"
        "        log.info(\"order {} by {}\", orderId, principal.name)\n        return svc.load(orderId)\n    }")
    assert [f.path for f in of(scan(tmp_path, files), "object-authorization")] == ["src/OrderStore.kt"]


def test_idor_named_parameter_template_with_param_source(tmp_path):
    files = dict(IDOR_FILES)
    files["src/OrderStore.kt"] = """package d
data class Order(val id: Long, val ownerId: String, val total: Int)
@Repository
class OrderStore(private val named: NamedParameterJdbcTemplate) {
    fun byId(id: Long): Order? {
        val params = MapSqlParameterSource("id", id)
        return named.query("SELECT id, owner_id, total FROM orders WHERE id = :id", params, rows).firstOrNull()
    }
    fun byOwner(owner: String): List<Order> = named.query("SELECT * FROM orders WHERE owner_id = :o", mapOf("o" to owner), rows)
}
"""
    fs = of(scan(tmp_path, files), "object-authorization")
    assert [(f.path, f.line) for f in fs] == [("src/OrderStore.kt", 7)]


def test_cors_reflected_origin_with_credentials(tmp_path):
    src = """package d
class CorsFilter : OncePerRequestFilter() {
    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        response.setHeader("Access-Control-Allow-Origin", request.getHeader("Origin"))
        response.setHeader("Access-Control-Allow-Credentials", "true")
        chain.doFilter(request, response)
    }
}
class Safe : OncePerRequestFilter() {
    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        response.setHeader("Access-Control-Allow-Origin", "https://app.example.org")
        response.setHeader("Access-Control-Allow-Credentials", "true")
    }
}
"""
    fs = of(scan(tmp_path, {"src/F.kt": src}), "credentialed-cors")
    assert [(f.line, f.end_line) for f in fs] == [(4, 5)]
