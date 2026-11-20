from app.analyzers.common.finding import Finding, Location, dedupe_findings
from app.analyzers.common.masking import fingerprint, mask_in_text, mask_value


def _secret(**kw):
    base = dict(category="SECRET", cls="password", rule_id="SEC-NAME-PASSWORD", title="t", path="a/B.kt", line=4,
                severity="HIGH", confidence=0.9)
    base.update(kw)
    return Finding(**base)


def test_mask_value_keeps_two_chars_and_length():
    assert mask_value("cg26_parts_H9r4Vm2Kb6Qp") == "cg…(len=23)"


def test_mask_short_value_hides_everything():
    assert mask_value("abc") == "…(len=3)"


def test_fingerprint_is_sha256_prefix_and_length():
    fp = fingerprint("secret-value")
    assert fp.startswith("sha256:") and fp.endswith(":12")
    assert len(fp.split(":")[1]) == 8


def test_mask_in_text_replaces_all_occurrences():
    text = 'val k = "topsecretvalue1"  // topsecretvalue1'
    out = mask_in_text(text, ["topsecretvalue1"])
    assert "topsecretvalue1" not in out
    assert out.count("to…(len=15)") == 2


def test_finding_id_is_stable_and_ignores_line_shift():
    a = _secret(line=4, context_key="legacyImportPassword")
    b = _secret(line=40, context_key="legacyImportPassword")
    assert a.id == b.id
    c = _secret(line=4, context_key="otherPassword")
    assert a.id != c.id


def test_end_line_defaults_to_line_and_range_capped_at_15_lines():
    f = _secret(line=10)
    assert f.end_line == 10
    g = _secret(line=10, end_line=40)
    assert g.end_line == 24


def test_dedupe_keeps_most_specific_class_for_same_location():
    generic = _secret(cls="generic-secret", rule_id="SEC-ENTROPY", confidence=0.5, value_fingerprint="sha256:aa:5")
    specific = _secret(cls="api-key", rule_id="SEC-NAME-APIKEY", confidence=0.9, value_fingerprint="sha256:aa:5")
    out = dedupe_findings([generic, specific])
    assert [f.cls for f in out] == ["api-key"]


def test_dedupe_same_secret_value_reported_once_per_file():
    a = _secret(line=4, value_fingerprint="sha256:bb:9")
    b = _secret(line=7, cls="api-key", value_fingerprint="sha256:bb:9")
    assert len(dedupe_findings([a, b])) == 1


def test_alternate_locations_serialize():
    f = _secret(alternate_locations=[Location(path="x.kt", line=1, end_line=2)])
    d = f.model_dump(by_alias=True)
    assert d["class"] == "password"
    assert d["alternate_locations"][0] == {"path": "x.kt", "line": 1, "end_line": 2}
