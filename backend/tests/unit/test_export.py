"""Tests for the report export module: submission JSON, validator, Markdown and HTML reports."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.analyzers.common.finding import Finding
from app.export.html import render_html
from app.export.markdown import render_markdown
from app.export.submission_json import dumps_submission, to_submission
from app.export.validator import validate_submission

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURES = BACKEND_DIR.parent / "fixtures" / "organizer-training"
EXAMPLE_JSON = FIXTURES / "docs" / "training-result-example.json"
GROUND_TRUTH = FIXTURES / "ground-truth" / "training-findings.json"

RAW_SECRET = "Sup3rS3cr3tP@ssw0rd-RAW"


def _secret(**kw) -> Finding:
    data = dict(
        category="SECRET",
        cls="password",
        rule_id="secret.password",
        title="Встроенный пароль",
        description="Пароль служебной учётной записи хранится в коде",
        remediation="Вынести в переменную окружения",
        severity="HIGH",
        path="src/main/kotlin/App.kt",
        line=4,
        snippet='val password = "Su***23"',
        masked_value="Su***23",
    )
    data.update(kw)
    return Finding(**data)


def _sast(**kw) -> Finding:
    data = dict(
        category="SAST",
        cls="sql-injection",
        rule_id="sast.sqli",
        title="SQL-инъекция",
        description="Параметр запроса подставляется в SQL без параметризации",
        remediation="Использовать параметризованный запрос",
        severity="HIGH",
        path="src/main/kotlin/repair/RepairLookupController.kt",
        line=13,
        end_line=14,
    )
    data.update(kw)
    return Finding(**data)


def _sca(**kw) -> Finding:
    data = dict(
        category="SCA",
        cls="known-vulnerable-dependency",
        rule_id="sca.osv",
        title="Уязвимая зависимость commons-text",
        description="Опасные lookup-подстановки",
        remediation="Обновить до 1.10.0",
        severity="CRITICAL",
        path="build.gradle.kts",
        line=31,
        group="org.apache.commons",
        artifact="commons-text",
        version="1.9",
        advisory_id="CVE-2022-42889",
        aliases=["GHSA-599f-7c49-w659"],
        fixed_versions=["1.10.0"],
    )
    data.update(kw)
    return Finding(**data)


def _ground_truth_findings() -> list[Finding]:
    raw = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))["findings"]
    out: list[Finding] = []
    for item in raw:
        common = dict(
            category=item["category"],
            cls=item["class"],
            rule_id=f"gt.{item['id']}",
            title=item["class"],
            description=item.get("description", ""),
            remediation=item.get("remediation", ""),
            severity=item.get("severity", "MEDIUM"),
            path=item["path"],
            line=item.get("line", 1),
            end_line=item.get("endLine"),
        )
        if item["category"] == "SCA":
            common.update(
                group=item["group"],
                artifact=item["artifact"],
                version=item["version"],
                advisory_id=item["advisoryIds"][0],
                aliases=item["advisoryIds"][1:],
            )
        out.append(Finding(**common))
    return out


# --------------------------------------------------------------------------- submission JSON


class TestSubmissionJson:
    def test_empty(self):
        assert to_submission([]) == {"findings": []}
        assert json.loads(dumps_submission([])) == {"findings": []}

    def test_secret_fields(self):
        sub = to_submission([_secret()])
        assert sub == {
            "findings": [
                {
                    "category": "SECRET",
                    "path": "src/main/kotlin/App.kt",
                    "class": "password",
                    "line": 4,
                    "severity": "HIGH",
                    "description": "Пароль служебной учётной записи хранится в коде",
                    "remediation": "Вынести в переменную окружения",
                }
            ]
        }

    def test_sast_end_line_kept_when_different(self):
        item = to_submission([_sast()])["findings"][0]
        assert item["line"] == 13
        assert item["endLine"] == 14
        assert isinstance(item["line"], int) and isinstance(item["endLine"], int)

    def test_end_line_omitted_when_equal(self):
        item = to_submission([_sast(end_line=13)])["findings"][0]
        assert "endLine" not in item

    def test_sca_fields_and_no_line(self):
        item = to_submission([_sca()])["findings"][0]
        assert item == {
            "category": "SCA",
            "path": "build.gradle.kts",
            "group": "org.apache.commons",
            "artifact": "commons-text",
            "version": "1.9",
            "advisoryId": "CVE-2022-42889",
            "severity": "CRITICAL",
            "description": "Опасные lookup-подстановки",
            "remediation": "Обновить до 1.10.0",
        }

    def test_blank_optional_strings_omitted(self):
        item = to_submission([_secret(description="  ", remediation="")])["findings"][0]
        assert "description" not in item
        assert "remediation" not in item

    def test_no_internal_fields_leak(self):
        f = _secret(value_fingerprint="abc", context_key="k", confidence=0.3)
        item = to_submission([f])["findings"][0]
        for key in ("id", "rule_id", "snippet", "masked_value", "confidence", "value_fingerprint", "title"):
            assert key not in item

    def test_raw_secret_never_output(self):
        # the raw value is only present in a field that must never be exported
        f = _secret(context_key=RAW_SECRET)
        text = dumps_submission([f])
        assert RAW_SECRET not in text

    def test_stable_ordering(self):
        findings = [
            _sca(advisory_id="CVE-2-B", artifact="b"),
            _sast(path="b.kt", line=5, end_line=5),
            _secret(path="z.kt", line=1),
            _sast(path="a.kt", line=9, end_line=9),
            _secret(path="a.kt", line=7),
            _sast(path="a.kt", line=2, end_line=3),
            _sca(advisory_id="CVE-1-A", artifact="a"),
        ]
        out = to_submission(findings)["findings"]
        keys = [(i["category"], i["path"], i.get("line"), i.get("artifact")) for i in out]
        assert keys == [
            ("SECRET", "a.kt", 7, None),
            ("SECRET", "z.kt", 1, None),
            ("SAST", "a.kt", 2, None),
            ("SAST", "a.kt", 9, None),
            ("SAST", "b.kt", 5, None),
            ("SCA", "build.gradle.kts", None, "a"),
            ("SCA", "build.gradle.kts", None, "b"),
        ]
        # deterministic regardless of input order
        assert dumps_submission(findings) == dumps_submission(list(reversed(findings)))

    def test_dumps_is_utf8_not_ascii_escaped(self):
        text = dumps_submission([_secret()])
        assert "Пароль" in text
        assert "\\u" not in text
        text.encode("utf-8")

    def test_dot_slash_prefix_normalized(self):
        item = to_submission([_secret(path="./src/App.kt")])["findings"][0]
        assert item["path"] == "src/App.kt"

    def test_invalid_findings_are_skipped(self):
        bad = [
            _secret(path="/etc/passwd"),
            _secret(path="../outside.kt"),
            _secret(path="C:/x/App.kt"),
            _sca(advisory_id=None),
            _sca(version=" "),
            _secret(cls=" "),
        ]
        sub = to_submission(bad + [_secret()])
        assert len(sub["findings"]) == 1
        assert validate_submission(sub) == []

    def test_ground_truth_roundtrip_is_valid(self):
        findings = _ground_truth_findings()
        text = dumps_submission(findings)
        assert validate_submission(text) == []
        data = json.loads(text)
        assert len(data["findings"]) == len(findings)
        sql = next(i for i in data["findings"] if i.get("class") == "sql-injection")
        assert sql["line"] == 13 and sql["endLine"] == 14


# --------------------------------------------------------------------------- validator


def _valid_doc() -> dict:
    return json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))


def _with(index: int, **changes) -> dict:
    doc = _valid_doc()
    item = doc["findings"][index]
    for k, v in changes.items():
        if v is _DELETE:
            item.pop(k, None)
        else:
            item[k] = v
    return doc


_DELETE = object()
SECRET_IDX, SCA_IDX, SAST_IDX = 0, 1, 2


class TestValidatorAccepts:
    def test_example_file(self):
        assert validate_submission(_valid_doc()) == []

    def test_example_as_string(self):
        assert validate_submission(EXAMPLE_JSON.read_text(encoding="utf-8")) == []

    def test_empty_findings(self):
        assert validate_submission({"findings": []}) == []

    def test_spec_full_example(self):
        doc = {
            "findings": [
                {
                    "category": "SECRET",
                    "path": "src/main/kotlin/lab/repairdesk/integration/QuoteRequest.kt",
                    "class": "api-key",
                    "line": 7,
                    "severity": "MEDIUM",
                    "description": "Встроенный API-ключ используется в заголовке X-Api-Key",
                    "remediation": "Передавать ключ через настройки окружения",
                },
                {
                    "category": "SAST",
                    "path": "src/main/kotlin/lab/repairdesk/repair/RepairLookupController.kt",
                    "class": "sql-injection",
                    "line": 13,
                    "endLine": 14,
                },
            ]
        }
        assert validate_submission(doc) == []

    def test_windows_relative_separator_allowed(self):
        assert validate_submission(_with(SECRET_IDX, path="src\\main\\resources\\application.yml")) == []

    def test_end_line_boundaries(self):
        assert validate_submission(_with(SAST_IDX, endLine=13)) == []
        assert validate_submission(_with(SAST_IDX, endLine=27)) == []

    def test_custom_class_allowed(self):
        assert validate_submission(_with(SAST_IDX, **{"class": "xxe"})) == []

    def test_non_vocabulary_severity_allowed(self):
        assert validate_submission(_with(SECRET_IDX, severity="INFO")) == []

    def test_extra_fields_allowed(self):
        assert validate_submission(_with(SECRET_IDX, confidence=0.9)) == []

    def test_float_with_integral_value_in_text_is_rejected_but_int_ok(self):
        assert validate_submission('{"findings":[{"category":"SAST","path":"a.kt","class":"x","line":3}]}') == []
        assert validate_submission('{"findings":[{"category":"SAST","path":"a.kt","class":"x","line":3.0}]}')


def _assert_rejected(doc, fragment: str | None = None) -> list[str]:
    errors = validate_submission(doc)
    assert errors, "expected validation errors"
    assert all(isinstance(e, str) and e for e in errors)
    if fragment is not None:
        assert any(fragment in e for e in errors), errors
    return errors


class TestValidatorRejects:
    def test_missing_findings(self):
        _assert_rejected({}, "findings")

    def test_findings_not_array(self):
        _assert_rejected({"findings": {}}, "findings")

    def test_root_not_object(self):
        _assert_rejected("[]")

    def test_invalid_json_text(self):
        _assert_rejected('{"findings": [,]}', "JSON")

    def test_trailing_comma_json(self):
        _assert_rejected('{"findings": [],}')

    def test_finding_not_object(self):
        _assert_rejected({"findings": ["x"]}, "findings[0]")

    def test_wrong_category(self):
        _assert_rejected(_with(SECRET_IDX, category="SECRETS"), "category")

    def test_lowercase_category(self):
        _assert_rejected(_with(SECRET_IDX, category="secret"), "category")

    def test_missing_category(self):
        _assert_rejected(_with(SECRET_IDX, category=_DELETE), "category")

    def test_missing_path(self):
        _assert_rejected(_with(SECRET_IDX, path=_DELETE), "path")

    def test_blank_path(self):
        _assert_rejected(_with(SECRET_IDX, path="   "), "path")

    def test_absolute_path(self):
        _assert_rejected(_with(SECRET_IDX, path="/src/App.kt"), "path")

    def test_absolute_windows_path(self):
        _assert_rejected(_with(SECRET_IDX, path="\\src\\App.kt"), "path")

    def test_unc_path(self):
        _assert_rejected(_with(SECRET_IDX, path="\\\\server\\share\\App.kt"), "path")

    def test_dotdot(self):
        _assert_rejected(_with(SECRET_IDX, path="src/../App.kt"), "..")

    def test_dotdot_windows(self):
        _assert_rejected(_with(SECRET_IDX, path="src\\..\\App.kt"), "..")

    def test_drive_letter(self):
        _assert_rejected(_with(SECRET_IDX, path="C:\\proj\\App.kt"), "path")

    def test_drive_letter_forward_slash(self):
        _assert_rejected(_with(SECRET_IDX, path="C:/proj/App.kt"), "path")

    def test_colon_anywhere(self):
        _assert_rejected(_with(SECRET_IDX, path="src/a:b.kt"), "path")

    def test_string_line(self):
        _assert_rejected(_with(SAST_IDX, line="13"), "line")

    def test_float_line(self):
        _assert_rejected(_with(SAST_IDX, line=13.0), "line")

    def test_bool_line(self):
        _assert_rejected(_with(SAST_IDX, line=True), "line")

    def test_null_line(self):
        _assert_rejected(_with(SAST_IDX, line=None), "line")

    def test_missing_line(self):
        _assert_rejected(_with(SAST_IDX, line=_DELETE), "line")

    def test_zero_line(self):
        _assert_rejected(_with(SAST_IDX, line=0), "line")

    def test_end_line_less_than_line(self):
        _assert_rejected(_with(SAST_IDX, endLine=12), "endLine")

    def test_end_line_too_far(self):
        _assert_rejected(_with(SAST_IDX, endLine=28), "endLine")

    def test_end_line_string(self):
        _assert_rejected(_with(SAST_IDX, endLine="14"), "endLine")

    def test_end_line_null(self):
        _assert_rejected(_with(SAST_IDX, endLine=None), "endLine")

    def test_end_line_bool(self):
        _assert_rejected(_with(SAST_IDX, endLine=False), "endLine")

    def test_end_line_float(self):
        _assert_rejected(_with(SAST_IDX, endLine=14.5), "endLine")

    def test_secret_without_class(self):
        _assert_rejected(_with(SECRET_IDX, **{"class": _DELETE}), "class")

    def test_sast_blank_class(self):
        _assert_rejected(_with(SAST_IDX, **{"class": " "}), "class")

    def test_class_not_string(self):
        _assert_rejected(_with(SAST_IDX, **{"class": 5}), "class")

    def test_sca_missing_advisory(self):
        _assert_rejected(_with(SCA_IDX, advisoryId=_DELETE), "advisoryId")

    def test_sca_advisory_list(self):
        _assert_rejected(_with(SCA_IDX, advisoryId=["CVE-2022-42889"]), "advisoryId")

    def test_sca_advisory_ids_instead_of_advisory_id(self):
        _assert_rejected(
            _with(SCA_IDX, advisoryId=_DELETE, advisoryIds=["CVE-2022-42889", "GHSA-599f-7c49-w659"]),
            "advisoryId",
        )

    @pytest.mark.parametrize("key", ["group", "artifact", "version"])
    def test_sca_missing_coordinates(self, key):
        _assert_rejected(_with(SCA_IDX, **{key: _DELETE}), key)

    def test_sca_numeric_version(self):
        _assert_rejected(_with(SCA_IDX, version=1.9), "version")

    @pytest.mark.parametrize("key", ["severity", "description", "remediation"])
    def test_optional_string_wrong_type(self, key):
        _assert_rejected(_with(SECRET_IDX, **{key: 3}), key)

    def test_errors_mention_index(self):
        errors = _assert_rejected(_with(SAST_IDX, line="13"))
        assert any("findings[2]" in e for e in errors)

    def test_multiple_errors_collected(self):
        doc = _with(SAST_IDX, line="13", path="/abs.kt")
        assert len(validate_submission(doc)) >= 2


class TestValidatorCli:
    def _run(self, path: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "app.export.validator", str(path)],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_cli_valid(self):
        res = self._run(EXAMPLE_JSON)
        assert res.returncode == 0, res.stdout + res.stderr

    def test_cli_invalid(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(_with(SAST_IDX, line="13")), encoding="utf-8")
        res = self._run(bad)
        assert res.returncode == 1
        assert "line" in (res.stdout + res.stderr)

    def test_cli_missing_file(self, tmp_path):
        res = self._run(tmp_path / "nope.json")
        assert res.returncode == 1


# --------------------------------------------------------------------------- Markdown


def _mixed() -> list[Finding]:
    return [
        _secret(),
        _secret(cls="api-key", path="src/Q.kt", line=7, severity="MEDIUM", title="API-ключ", masked_value="ab***yz"),
        _sast(),
        _sca(),
    ]


class TestMarkdown:
    def test_header_and_project(self):
        md = render_markdown(_mixed(), "repairdesk")
        assert md.startswith("# ")
        assert "repairdesk" in md

    def test_summary_counts(self):
        md = render_markdown(_mixed(), "p")
        assert "Всего находок: 4" in md
        assert "| SECRET | 2 |" in md
        assert "| SAST | 1 |" in md
        assert "| SCA | 1 |" in md
        assert "| HIGH | 2 |" in md
        assert "| CRITICAL | 1 |" in md
        assert "| MEDIUM | 1 |" in md

    def test_locations(self):
        md = render_markdown(_mixed(), "p")
        assert "src/main/kotlin/repair/RepairLookupController.kt:13-14" in md
        assert "src/main/kotlin/App.kt:4" in md
        assert "src/main/kotlin/App.kt:4-" not in md
        assert "build.gradle.kts" in md
        assert "org.apache.commons:commons-text:1.9" in md
        assert "CVE-2022-42889" in md

    def test_sections_per_category(self):
        md = render_markdown(_mixed(), "p")
        assert "## Секреты (SECRET)" in md
        assert "## Уязвимости кода (SAST)" in md
        assert "## Уязвимые зависимости (SCA)" in md

    def test_titles_and_severity(self):
        md = render_markdown(_mixed(), "p")
        assert "SQL-инъекция" in md
        assert "Встроенный пароль" in md

    def test_pipe_escaped(self):
        f = _sast(title="a|b", description="x | y")
        md = render_markdown([f], "p")
        assert "a\\|b" in md
        assert "x \\| y" in md
        assert "a|b" not in md.replace("a\\|b", "")

    def test_newlines_in_cells_flattened(self):
        f = _sast(description="first line\nsecond line")
        md = render_markdown([f], "p")
        row = next(line for line in md.splitlines() if "first line" in line)
        assert "second line" in row

    def test_secret_masked_value_shown_raw_not(self):
        f = _secret(context_key=RAW_SECRET, value_fingerprint="fp")
        md = render_markdown([f], "p")
        assert RAW_SECRET not in md
        assert "Su***23" in md

    def test_empty_report(self):
        md = render_markdown([], "p")
        assert "Находок нет" in md

    def test_meta_rendered(self):
        md = render_markdown([], "p", meta={"commit": "abc123", "Дата": "2026-11-20"})
        assert "abc123" in md
        assert "2026-11-20" in md

    def test_meta_pipe_escaped(self):
        md = render_markdown([], "p", meta={"k": "a|b"})
        assert "a\\|b" in md

    def test_long_description_shortened(self):
        f = _sast(description="слово " * 200)
        md = render_markdown([f], "p")
        row = next(line for line in md.splitlines() if "слово" in line)
        assert len(row) < 600
        assert "…" in row

    def test_ground_truth_renders(self):
        md = render_markdown(_ground_truth_findings(), "repairdesk")
        assert "Всего находок: 15" in md


# --------------------------------------------------------------------------- HTML


class TestHtml:
    def test_self_contained(self):
        html = render_html(_mixed(), "repairdesk")
        low = html.lower()
        assert low.startswith("<!doctype html>")
        assert "<style>" in low
        assert 'charset="utf-8"' in low
        for bad in ("<link", "src=", "http://", "https://", "@import", "<script"):
            assert bad not in low

    def test_script_escaped(self):
        f = _sast(description='<script>alert("x")</script>', title="<b>t</b>")
        html = render_html([f], "<img onerror=1>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<b>t</b>" not in html
        assert "<img onerror=1>" not in html
        assert "&lt;img onerror=1&gt;" in html

    def test_meta_escaped(self):
        html = render_html([], "p", meta={"<k>": "<v>"})
        assert "&lt;k&gt;" in html and "&lt;v&gt;" in html
        assert "<v>" not in html

    def test_content(self):
        html = render_html(_mixed(), "p")
        assert "Всего находок: 4" in html
        assert "src/main/kotlin/repair/RepairLookupController.kt:13-14" in html
        assert "org.apache.commons:commons-text:1.9" in html
        assert "CVE-2022-42889" in html
        assert "Секреты (SECRET)" in html
        assert "Su***23" in html

    def test_no_raw_secret(self):
        f = _secret(context_key=RAW_SECRET)
        assert RAW_SECRET not in render_html([f], "p")

    def test_empty(self):
        assert "Находок нет" in render_html([], "p")

    def test_severity_classes(self):
        html = render_html(_mixed(), "p")
        assert 'class="sev sev-critical"' in html
        assert 'class="sev sev-high"' in html


def test_official_export_filters_low_confidence_and_transitive():
    low = _secret(confidence=0.3, path="src/Low.kt")
    trans = _sca(scope="transitive", direct=False)
    keep = _sast()
    data = to_submission([low, trans, keep], min_confidence=0.5)
    assert len(data["findings"]) == 1 and data["findings"][0]["category"] == "SAST"
    assert len(to_submission([low, keep], min_confidence=0.0)["findings"]) == 2
