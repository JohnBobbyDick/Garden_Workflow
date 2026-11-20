from pathlib import Path

import pytest

from app.analyzers.secrets.detector import SecretsConfig, scan_secrets
from app.analyzers.secrets.entropy import shannon_entropy
from app.analyzers.secrets.rules import is_placeholder, looks_like_secret


def scan(tmp_path: Path, files: dict[str, str], **cfg):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return scan_secrets(tmp_path, SecretsConfig(**cfg))


def one(findings):
    assert len(findings) == 1, [(f.cls, f.path, f.line) for f in findings]
    return findings[0]


# ---- value rules ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("v", ["${API_TOKEN}", "#{vault.x}", "{{token}}", "<token>", "%TOKEN%", "YOUR_API_KEY", "xxxxxxxx",
                               "changeme", "example", "dummy-value", "***", "", "null", "your-token-here", "REPLACE_ME"])
def test_placeholders(v):
    assert is_placeholder(v)


@pytest.mark.parametrize("v", ["cg26_parts_H9r4Vm2Kb6Qp", "Zx81!qpL0", "ghp_aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z"])
def test_secret_like_values(v):
    assert looks_like_secret(v)


@pytest.mark.parametrize("v", ["REPAIR_COPPER_PASSWORD", "pickup.callback.authorization", "X-Api-Key", "https://example.org/a",
                               "/var/lib/app", "Enter your password", "%s:%s", "Authorization"])
def test_not_secret_like_values(v):
    assert not looks_like_secret(v)


def test_entropy():
    assert shannon_entropy("aaaa") == 0
    assert shannon_entropy("aB3dE5fG7hJ9kL1m") > 3.5


# ---- kotlin ---------------------------------------------------------------------------------------------------

def test_password_literal_in_named_field(tmp_path):
    f = one(scan(tmp_path, {"src/A.kt": 'class A {\n    private val importPassword = "Sx91_qWe82_Lk"\n}\n'}))
    assert (f.cls, f.line, f.category) == ("password", 2, "SECRET")
    assert "Sx91_qWe82_Lk" not in f.snippet and f.masked_value == "Sx…(len=13)"


def test_api_key_flowing_into_header(tmp_path):
    src = ('class Q {\n    private val pricing = "k_live_qA7mN4kV9rT2sJ6c"\n'
           '    fun b() = Req.newBuilder().header("X-Api-Key", pricing).build()\n}\n')
    f = one(scan(tmp_path, {"src/Q.kt": src}))
    assert (f.cls, f.line) == ("api-key", 2)


def test_secret_fallback_elvis(tmp_path):
    src = 'class D {\n    fun r() {\n        val access = System.getenv("STATUS_TOKEN") ?: "dep_mK7xR4bP9wD2qT"\n        call("Bearer $access")\n    }\n}\n'
    f = one(scan(tmp_path, {"src/D.kt": src}))
    assert (f.cls, f.line) == ("secret-fallback", 3)


@pytest.mark.parametrize("expr", [
    'env.getProperty("svc.token", "dep_mK7xR4bP9wD2qT")',
    'System.getProperty("svc.token", "dep_mK7xR4bP9wD2qT")',
    'System.getenv().getOrDefault("SVC_TOKEN", "dep_mK7xR4bP9wD2qT")',
    'settings.token ?: "dep_mK7xR4bP9wD2qT"',
    'Optional.ofNullable(System.getenv("SVC_TOKEN")).orElse("dep_mK7xR4bP9wD2qT")',
])
def test_secret_fallback_variants(tmp_path, expr):
    f = one(scan(tmp_path, {"src/D.kt": f"class D {{\n    fun r() {{\n        val t = {expr}\n    }}\n}}\n"}))
    assert (f.cls, f.line) == ("secret-fallback", 3)


def test_value_annotation_default_is_fallback(tmp_path):
    src = 'class C(@Value("\\${svc.api-token:dep_mK7xR4bP9wD2qT}") private val token: String)\n'
    f = one(scan(tmp_path, {"src/C.kt": src}))
    assert (f.cls, f.line) == ("secret-fallback", 1)


def test_env_without_default_is_not_secret(tmp_path):
    src = 'class D {\n    val t = System.getenv("SVC_TOKEN") ?: error("missing")\n    val u = System.getenv("SVC_PASSWORD") ?: UUID.randomUUID().toString()\n}\n'
    assert scan(tmp_path, {"src/D.kt": src}) == []


def test_recoverable_token_concatenation_range(tmp_path):
    src = ("class W {\n    fun build(): Headers {\n        val series = \"cg26_warranty_\"\n        val grant = \"D7v4sB2wJ8kP6mQ9\"\n"
           "        val access = series + grant\n        return Headers().apply { setBearerAuth(access) }\n    }\n}\n")
    f = one(scan(tmp_path, {"src/W.kt": src}))
    assert (f.cls, f.line, f.end_line) == ("recoverable-token", 3, 6)


@pytest.mark.parametrize("build", [
    'val access = StringBuilder().append("cg26_w_").append("D7v4sB2wJ8kP6mQ9").toString()',
    'val access = listOf("cg26_w_", "D7v4sB2wJ8kP6mQ9").joinToString("")',
    'val access = "%s%s".format("cg26_w_", "D7v4sB2wJ8kP6mQ9")',
    'val access = String(Base64.getDecoder().decode("Y2cyNl93X0Q3djRzQjJ3SjhrUDZtUTk="))',
    'val access = "9Qm6Pk8Jw2Bs4v7D_w_62gc".reversed()',
])
def test_recoverable_token_variants(tmp_path, build):
    src = f"class W {{\n    fun h(): Headers {{\n        {build}\n        return Headers().apply {{ set(\"Authorization\", \"Bearer \" + access) }}\n    }}\n}}\n"
    f = one(scan(tmp_path, {"src/W.kt": src}))
    assert f.cls == "recoverable-token" and f.line == 3 and f.end_line == 4


def test_fragments_without_secret_sink_or_name_not_reported(tmp_path):
    src = 'class G {\n    fun g(): String {\n        val a = "Hello, "\n        val b = "world"\n        return a + b\n    }\n}\n'
    assert scan(tmp_path, {"src/G.kt": src}) == []


def test_env_var_name_constants_not_secrets(tmp_path):
    src = ('class Acc {\n    fun u() = listOf(account("rider", "CUSTOMER", "APP_RIDER_PASSWORD"))\n'
           '    private val passwordVariable = "APP_ADMIN_PASSWORD"\n    const val TOKEN_HEADER = "X-Auth-Token"\n}\n')
    assert scan(tmp_path, {"src/Acc.kt": src}) == []


def test_signature_aws_key_in_code(tmp_path):
    key = "AKIA" + "Q3EGRTXN5VJ7LMZP"
    f = one(scan(tmp_path, {"src/Cfg.kt": f'object Cfg {{\n    val k = "{key}"\n}}\n'}))
    assert f.cls == "aws-access-key" and f.severity == "CRITICAL"


def test_private_key_block(tmp_path):
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA1x2y3z\n-----END RSA PRIVATE KEY-----\n"
    f = one(scan(tmp_path, {"keys/id.pem": pem}))
    assert f.cls == "private-key" and f.line == 1


def test_jdbc_url_with_password(tmp_path):
    f = one(scan(tmp_path, {"src/main/resources/application.properties": "spring.datasource.url=jdbc:postgresql://db:5432/app?user=app&password=Pg_s3cr3t_92\n"}))
    assert f.cls == "db-credentials"


# ---- config files -------------------------------------------------------------------------------------------

def test_yaml_bearer_token_nested(tmp_path):
    yml = "server:\n  port: 8080\n\npickup:\n  callback:\n    authorization: \"Bearer cg26_pickup_Gq7mP8vJdW3sY6zN\"\n\ninventory:\n  token: ${INVENTORY_TOKEN}\n"
    f = one(scan(tmp_path, {"src/main/resources/application.yml": yml}))
    assert (f.cls, f.line) == ("configuration-token", 6)
    assert f.context_key == "pickup.callback.authorization"


def test_yaml_env_with_default_is_fallback(tmp_path):
    yml = "svc:\n  token: ${SVC_TOKEN:dep_mK7xR4bP9wD2qT}\n  other: ${SVC_OTHER:localhost}\n"
    f = one(scan(tmp_path, {"application.yml": yml}))
    assert (f.cls, f.line) == ("secret-fallback", 2)


def test_properties_token(tmp_path):
    f = one(scan(tmp_path, {"application.properties": "# c\nintegration.api-token=cg26_tok_A8sKd02mZx\nserver.port=8080\n"}))
    assert (f.cls, f.line) == ("configuration-token", 2)


def test_readme_placeholder_ignored_but_real_key_in_docs_low_confidence(tmp_path):
    md = 'Пример: `apiKey = "YOUR_API_KEY"`.\n\nold: apiKey = "k_live_qA7mN4kV9rT2sJ6c"\n'
    fs = scan(tmp_path, {"README.md": md})
    f = one(fs)
    assert f.line == 3 and f.confidence < 0.6


def test_include_exclude_respected(tmp_path):
    files = {"src/A.kt": 'class A { val password = "Sx91_qWe82_Lk" }\n', "other/B.kt": 'class B { val password = "Sx91_qWe82_Lk" }\n'}
    fs = scan(tmp_path, files, include=["src/**"])
    assert [f.path for f in fs] == ["src/A.kt"]


def test_recoverable_token_snippet_masks_every_fragment(tmp_path):
    src = ("class W {\n    fun build(): Headers {\n        val series = \"cg26_warranty_\"\n        val grant = \"D7v4sB2wJ8kP6mQ9\"\n"
           "        val access = series + grant\n        return Headers().apply { setBearerAuth(access) }\n    }\n}\n")
    f = one(scan(tmp_path, {"src/W.kt": src}))
    assert "cg26_warranty_" not in f.snippet and "D7v4sB2wJ8kP6mQ9" not in f.snippet


def test_private_key_body_never_in_snippet(tmp_path):
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA1x2y3zABCDEF\nQWERTYUIOPasdfghjkl0987654\n-----END RSA PRIVATE KEY-----\n"
    f = one(scan(tmp_path, {"keys/id.pem": pem}))
    assert "MIIEowIBAAKCAQEA1x2y3zABCDEF" not in f.snippet and "QWERTYUIOPasdfghjkl0987654" not in f.snippet


def test_template_literal_segments_masked_separately(tmp_path):
    src = ("class W {\n    fun build(): Headers {\n        val mid = \"Zq81\"\n"
           "        val access = \"kT9vR2mXa7_${mid}_pL4wQ8nB3y\"\n"
           "        return Headers().apply { setBearerAuth(access) }\n    }\n}\n")
    f = one(scan(tmp_path, {"src/W.kt": src}))
    assert "kT9vR2mXa7_" not in f.snippet and "_pL4wQ8nB3y" not in f.snippet


def test_dependency_coordinates_are_not_generic_secrets(tmp_path):
    src = ('dependencies {\n    implementation("com.squareup.okhttp3:okhttp:4.12.0")\n'
           '    implementation("org.apache.httpcomponents:httpclient:4.5.13")\n'
           '    implementation("org.apache.commons:commons-lang3:3.12.0")\n}\n')
    assert scan(tmp_path, {"build.gradle.kts": src}) == []


def test_coordinate_shaped_password_still_reported(tmp_path):
    src = 'class C {\n    private val password = "svc.app:Xk9mZ2pQ7vR4tW"\n}\n'
    f = one(scan(tmp_path, {"src/C.kt": src}))
    assert f.cls == "password"
