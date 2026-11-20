from app.analyzers.common.severity import max_severity, sast_severity, sca_severity, secret_severity


def test_sca_uses_computed_cvss_bands():
    assert sca_severity(9.8, "HIGH")[0] == "CRITICAL"
    assert sca_severity(5.9, "HIGH")[0] == "MEDIUM"


def test_sca_without_vector_falls_back_to_snapshot_severity():
    sev, reason = sca_severity(None, "HIGH")
    assert sev == "HIGH" and "справочник" in reason


def test_secret_matrix_context_modifiers():
    assert secret_severity("private-key", "src/main/x.kt")[0] == "CRITICAL"
    assert secret_severity("password", "src/main/x.kt")[0] == "HIGH"
    assert secret_severity("password", "src/test/x.kt")[0] == "MEDIUM"
    assert secret_severity("api-key", "config/application-prod.yml")[0] == "HIGH"
    assert secret_severity("generic-secret", "src/main/x.kt")[0] == "LOW"


def test_sast_matrix_reachability():
    assert sast_severity("sql-injection", unauthenticated=True)[0] == "CRITICAL"
    assert sast_severity("sql-injection", unauthenticated=False)[0] == "HIGH"
    assert sast_severity("object-authorization")[0] == "HIGH"
    assert sast_severity("weak-crypto")[0] == "MEDIUM"
    sev, reason = sast_severity("credentialed-cors", unauthenticated=False)
    assert sev == "MEDIUM" and reason


def test_max_severity():
    assert max_severity(["LOW", "HIGH", "MEDIUM"]) == "HIGH"
    assert max_severity([]) is None
