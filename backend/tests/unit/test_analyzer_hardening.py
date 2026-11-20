from app.analyzers.common.kotlin_ast import KotlinFile
from app.analyzers.sca.detector import scan_sca
from app.analyzers.sca.gradle_parser import module_build_files, parse_build_file
from app.analyzers.sca.vulndb import VulnDB
from tests.conftest import symlink_or_skip


def test_symlinked_gradle_properties_outside_root_is_ignored(tmp_path):
    outside = tmp_path / "outside.properties"
    outside.write_text("v=1.14.1\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "build.gradle.kts").write_text('dependencies {\n    implementation("org.jsoup:jsoup:${providers.gradleProperty("v").get()}")\n}\n')
    symlink_or_skip(outside, proj / "gradle.properties")
    deps = parse_build_file(proj, "build.gradle.kts")
    assert deps[0].declared_version is None


def test_symlinked_lockfile_ignored(tmp_path):
    outside = tmp_path / "lock"
    outside.write_text("org.jsoup:jsoup:1.14.1=runtimeClasspath\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "build.gradle.kts").write_text('dependencies {\n    implementation("org.jsoup:jsoup")\n}\n')
    symlink_or_skip(outside, proj / "gradle.lockfile")
    assert scan_sca(proj, VulnDB.load()).findings == []


def test_module_include_with_parent_traversal_rejected(tmp_path):
    proj = tmp_path / "proj"
    (tmp_path / "evil").mkdir()
    (tmp_path / "evil" / "build.gradle.kts").write_text("")
    proj.mkdir()
    (proj / "settings.gradle.kts").write_text('include("../evil", ":..:evil")\n')
    assert module_build_files(proj) == []


def test_resolver_budget_bounds_wide_expression():
    import time

    lines = ['val a0 = "x"'] + [f"val a{i} = (a{i - 1} + a{i - 1}) + (a{i - 1} + a{i - 1})" for i in range(1, 9)]
    src = "fun f() {\n" + "\n".join(lines) + "\n}\n"
    kf = KotlinFile.parse("T.kt", src)
    started = time.monotonic()
    r = kf.resolver_for(kf.functions()[0])
    assert r.resolve_name("a8") is None
    assert r.resolve_name("a3") is not None and len(r.resolve_name("a3").value) == 64
    assert time.monotonic() - started < 2.0


def test_value_cap_enforced_during_format_and_join():
    big = "A" * 40000
    src = f'fun f() {{\n    val a = "{big}"\n    val b = "%s%s".format(a, a)\n    val c = listOf(a, a).joinToString("")\n}}\n'
    kf = KotlinFile.parse("T.kt", src)
    r = kf.resolver_for(kf.functions()[0])
    assert r.resolve_name("b") is None and r.resolve_name("c") is None
