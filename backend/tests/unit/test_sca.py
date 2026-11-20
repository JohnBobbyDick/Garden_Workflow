import json
from pathlib import Path

import pytest

from app.analyzers.sca.detector import scan_sca
from app.analyzers.sca.gradle_parser import parse_build_file
from app.analyzers.sca.vulndb import VulnDB, VulnDBError

DEFAULT_DB = Path(__file__).resolve().parents[2] / "vulndb" / "vulnerabilities.json"


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def deps_of(tmp_path, build: str, props: str | None = None, catalog: str | None = None):
    write(tmp_path, "build.gradle.kts", build)
    if props is not None:
        write(tmp_path, "gradle.properties", props)
    if catalog is not None:
        write(tmp_path, "gradle/libs.versions.toml", catalog)
    return {(d.group, d.artifact): d for d in parse_build_file(tmp_path, "build.gradle.kts")}


class TestGradleParser:
    def test_literal_coordinates_and_line(self, tmp_path):
        d = deps_of(tmp_path, 'dependencies {\n    implementation("org.jsoup:jsoup:1.14.1")\n}\n')
        dep = d[("org.jsoup", "jsoup")]
        assert dep.declared_version == "1.14.1" and dep.line == 2 and dep.configuration == "implementation"

    def test_version_from_file_val_template(self, tmp_path):
        d = deps_of(tmp_path, 'val v = "1.25.0"\ndependencies {\n    api("org.apache.commons:commons-compress:$v")\n}\n')
        dep = d[("org.apache.commons", "commons-compress")]
        assert dep.declared_version == "1.25.0"
        assert dep.version_source == "variable:v"
        assert [(a.path, a.line) for a in dep.alternate_locations] == [("build.gradle.kts", 1)]

    def test_multiline_add_with_trailing_comma(self, tmp_path):
        d = deps_of(tmp_path, 'dependencies {\n    add(\n        "implementation",\n        "commons-net:commons-net:3.8.0",\n    )\n}\n')
        dep = d[("commons-net", "commons-net")]
        assert dep.line == 4 and dep.configuration == "implementation"

    def test_gradle_property_provider(self, tmp_path):
        d = deps_of(
            tmp_path,
            'val jsonV = providers.gradleProperty("jsonVersion").get()\ndependencies {\n    implementation("org.json:json:$jsonV")\n}\n',
            props="# c\njsonVersion=20230227\n",
        )
        dep = d[("org.json", "json")]
        assert dep.declared_version == "20230227"
        assert ("gradle.properties", 2) in [(a.path, a.line) for a in dep.alternate_locations]

    def test_inline_property_forms(self, tmp_path):
        d = deps_of(
            tmp_path,
            'val a: String by project\nextra["bVer"] = "2.0"\ndependencies {\n'
            '    implementation("g1:a1:$a")\n'
            '    implementation("g2:a2:${extra["bVer"]}")\n'
            '    implementation("g3:a3:${project.property("cVer")}")\n'
            '    implementation("g4:a4:${providers.gradleProperty("dVer").orNull}")\n'
            "}\n",
            props="a=1.0\ncVer=3.0\ndVer=4.0\n",
        )
        assert [d[(f"g{i}", f"a{i}")].declared_version for i in range(1, 5)] == ["1.0", "2.0", "3.0", "4.0"]

    def test_named_arguments_form(self, tmp_path):
        d = deps_of(tmp_path, 'dependencies {\n    implementation(group = "org.yaml", name = "snakeyaml", version = "1.33")\n}\n')
        assert d[("org.yaml", "snakeyaml")].declared_version == "1.33"

    def test_platform_bom_and_versionless(self, tmp_path):
        d = deps_of(
            tmp_path,
            'dependencies {\n    implementation(platform("org.springframework.boot:spring-boot-dependencies:3.0.0"))\n'
            '    implementation("org.springframework.boot:spring-boot-starter-web")\n}\n',
        )
        assert d[("org.springframework.boot", "spring-boot-dependencies")].declared_version == "3.0.0"
        assert d[("org.springframework.boot", "spring-boot-starter-web")].declared_version is None

    def test_version_catalog_alias(self, tmp_path):
        d = deps_of(
            tmp_path,
            "dependencies {\n    implementation(libs.commons.text)\n    implementation(libs.jsoup)\n}\n",
            catalog='[versions]\ntext = "1.9"\n\n[libraries]\ncommons-text = { module = "org.apache.commons:commons-text", version.ref = "text" }\n'
            'jsoup = { group = "org.jsoup", name = "jsoup", version = "1.14.1" }\n',
        )
        assert d[("org.apache.commons", "commons-text")].declared_version == "1.9"
        assert d[("org.jsoup", "jsoup")].declared_version == "1.14.1"
        assert d[("org.apache.commons", "commons-text")].version_source == "catalog:text"

    def test_strings_outside_dependencies_block_ignored(self, tmp_path):
        d = deps_of(tmp_path, 'val note = "commons-net:commons-net:3.8.0"\ndependencies {\n}\n')
        assert d == {}

    def test_kotlin_shorthand(self, tmp_path):
        d = deps_of(tmp_path, 'dependencies {\n    implementation(kotlin("stdlib"))\n}\n')
        assert ("org.jetbrains.kotlin", "kotlin-stdlib") in d

    def test_groovy_build_basic(self, tmp_path):
        write(tmp_path, "build.gradle", "def v = '1.9'\ndependencies {\n    implementation 'org.apache.commons:commons-text:' + v\n"
              "    implementation \"org.jsoup:jsoup:${v}\"\n    implementation group: 'commons-net', name: 'commons-net', version: '3.8.0'\n}\n")
        d = {(x.group, x.artifact): x for x in parse_build_file(tmp_path, "build.gradle")}
        assert d[("org.jsoup", "jsoup")].declared_version == "1.9"
        assert d[("commons-net", "commons-net")].declared_version == "3.8.0"


class TestVulnDB:
    def test_loads_default_snapshot(self):
        db = VulnDB.load(DEFAULT_DB)
        assert len(db.entries_for("org.apache.commons", "commons-text")) == 1

    def test_invalid_db_fails_loudly(self, tmp_path):
        bad = tmp_path / "db.json"
        bad.write_text(json.dumps({"formatVersion": 1, "vulnerabilities": []}))
        with pytest.raises(VulnDBError):
            VulnDB.load(bad)


class TestDetector:
    def test_lockfile_version_wins_and_advisory_prefers_cve(self, tmp_path):
        write(tmp_path, "build.gradle.kts", 'dependencies {\n    implementation("org.apache.commons:commons-text:1.10.0")\n}\n')
        write(tmp_path, "gradle.lockfile", "org.apache.commons:commons-text:1.9=runtimeClasspath\nempty=\n")
        res = scan_sca(tmp_path, VulnDB.load(DEFAULT_DB))
        assert len(res.findings) == 1
        f = res.findings[0]
        assert (f.group, f.artifact, f.version, f.declared_version) == ("org.apache.commons", "commons-text", "1.9", "1.10.0")
        assert f.advisory_id == "CVE-2022-42889"
        assert f.cvss.score == 9.8 and f.severity == "CRITICAL"
        assert "1.10.0" in f.remediation
        assert f.path == "build.gradle.kts" and f.line == 2

    def test_control_version_above_bound_has_no_finding(self, tmp_path):
        write(tmp_path, "build.gradle.kts", 'dependencies {\n    implementation("org.apache.commons:commons-lang3:3.20.0")\n}\n')
        assert scan_sca(tmp_path, VulnDB.load(DEFAULT_DB)).findings == []

    def test_transitive_only_when_enabled(self, tmp_path):
        write(tmp_path, "build.gradle.kts", "dependencies {\n}\n")
        write(tmp_path, "gradle.lockfile", "org.yaml:snakeyaml:1.30=runtimeClasspath\n")
        db = VulnDB.load(DEFAULT_DB)
        assert scan_sca(tmp_path, db).findings == []
        trans = scan_sca(tmp_path, db, include_transitive=True).findings
        assert trans and all(f.scope == "transitive" and f.direct is False for f in trans)

    def test_qualified_version_produces_note_not_finding(self, tmp_path):
        write(tmp_path, "build.gradle.kts", 'dependencies {\n    implementation("org.jsoup:jsoup:1.14.1-SNAPSHOT")\n}\n')
        res = scan_sca(tmp_path, VulnDB.load(DEFAULT_DB))
        assert res.findings == [] and any("jsoup" in n["message"] for n in res.notes)

    def test_multiple_advisories_produce_separate_findings(self, tmp_path):
        write(tmp_path, "build.gradle.kts", 'dependencies {\n    implementation("org.yaml:snakeyaml:1.20")\n}\n')
        fs = scan_sca(tmp_path, VulnDB.load(DEFAULT_DB)).findings
        assert len({f.advisory_id for f in fs}) == len(fs) >= 2

    def test_submodules_from_settings(self, tmp_path):
        write(tmp_path, "settings.gradle.kts", 'rootProject.name = "x"\ninclude(":app", ":lib:core")\n')
        write(tmp_path, "build.gradle.kts", "")
        write(tmp_path, "lib/core/build.gradle.kts", 'dependencies {\n    implementation("org.jsoup:jsoup:1.14.1")\n}\n')
        fs = scan_sca(tmp_path, VulnDB.load(DEFAULT_DB)).findings
        assert [f.path for f in fs] == ["lib/core/build.gradle.kts"]
