"""Deterministic SCA AutoFix for every version-declaration form (8.2) + lockfile; validated by the self-check."""

from pathlib import Path

import pytest

from app.analyzers.runner import analyze_project
from app.autofix.sca_bump import LOCK_NOTE, BumpError, plan_bump
from app.autofix.validator import Validation, apply_and_check

LIB = "org.apache.commons:commons-text"
FORMS = {
    "literal": ({"build.gradle.kts": f'dependencies {{\n    implementation("{LIB}:1.9")\n}}\n'}, ["build.gradle.kts"]),
    "val": ({"build.gradle.kts": f'val textV = "1.9"\ndependencies {{\n    implementation("{LIB}:$textV")\n}}\n'},
            ["build.gradle.kts"]),
    "gradle.properties": ({"build.gradle.kts": 'val textV: String by project\ndependencies {\n'
                                               f'    implementation("{LIB}:$textV")\n}}\n',
                           "gradle.properties": "# versions\ntextV=1.9\n"}, ["gradle.properties"]),
    "catalog": ({"build.gradle.kts": "dependencies {\n    implementation(libs.commons.text)\n}\n",
                 "gradle/libs.versions.toml": '[versions]\ntext = "1.9"\n\n[libraries]\n'
                                              'commons-text = { module = "org.apache.commons:commons-text", '
                                              'version.ref = "text" }\n'}, ["gradle/libs.versions.toml"]),
    "extra": ({"build.gradle.kts": 'extra["textV"] = "1.9"\ndependencies {\n'
                                   f'    implementation("{LIB}:${{extra["textV"]}}")\n}}\n'}, ["build.gradle.kts"]),
}


def make(tmp_path: Path, files: dict[str, str], lock: bool) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    if lock:
        (tmp_path / "gradle.lockfile").write_text(f"# lock\n{LIB}:1.9=compileClasspath,runtimeClasspath\nempty=\n")
    return tmp_path


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("lock", [False, True])
def test_bump_every_declaration_form(tmp_path, form, lock):
    files, expected = FORMS[form]
    root = make(tmp_path, files, lock)
    baseline = analyze_project(root).findings
    f = next(x for x in baseline if x.artifact == "commons-text")
    fix, edits, proposal = plan_bump(root, f)
    assert fix == "1.10.0"
    assert [e.path for e in edits] == sorted(expected + (["gradle.lockfile"] if lock else []))
    for e in edits:
        assert "1.10.0" in e.after and e.before.count("\n") == e.after.count("\n")
    assert (LOCK_NOTE in proposal["explanation"]) is lock
    v = apply_and_check(Validation(), root, edits, f, baseline)
    assert v.status == "validated", v.steps
    assert v.self_check["finding_gone"] and v.self_check["new_findings"] == []
    assert (root / expected[0]).read_text() == files[expected[0]]  # the original project is untouched


def test_bump_without_fixed_version_is_refused(tmp_path):
    root = make(tmp_path, FORMS["literal"][0], False)
    f = next(x for x in analyze_project(root).findings if x.artifact == "commons-text")
    with pytest.raises(BumpError):
        plan_bump(root, f.model_copy(update={"fixed_versions": []}))
