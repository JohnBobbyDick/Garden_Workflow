"""Project root detection: finding paths must be relative to the checked project, not to the repository root
(mentor's remark: ``src/main/kotlin/…``, not ``training-project/src/main/kotlin/…``)."""

from pathlib import Path

from app.analyzers.common.project_root import detect_project_root


def touch(root: Path, *rels: str) -> None:
    for rel in rels:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// x\n")


def test_gradle_project_at_root_is_kept(tmp_path):
    touch(tmp_path, "build.gradle.kts", "src/main/kotlin/A.kt", "app/build.gradle.kts")
    assert detect_project_root(tmp_path) == (None, [])


def test_organizer_layout_points_to_the_project_folder(tmp_path):
    touch(tmp_path, "README.md", "docs/submission-format.md", "ground-truth/training-findings.json",
          "vulnerability-database/vulnerabilities.json",
          "training-project/settings.gradle.kts", "training-project/build.gradle.kts",
          "training-project/src/main/kotlin/A.kt")
    assert detect_project_root(tmp_path) == ("training-project", ["training-project"])


def test_deeper_single_project_is_found(tmp_path):
    touch(tmp_path, "README.md", "services/payments/build.gradle.kts", "services/payments/src/main/kotlin/A.kt")
    assert detect_project_root(tmp_path)[0] == "services/payments"


def test_multi_project_build_uses_its_settings_root(tmp_path):
    touch(tmp_path, "README.md", "app/settings.gradle.kts", "app/build.gradle.kts", "app/core/build.gradle.kts",
          "app/api/build.gradle.kts")
    assert detect_project_root(tmp_path)[0] == "app"


def test_several_unrelated_projects_are_ambiguous(tmp_path):
    touch(tmp_path, "svc-a/build.gradle.kts", "svc-b/build.gradle.kts")
    sub, candidates = detect_project_root(tmp_path)
    assert sub is None and candidates == ["svc-a", "svc-b"]


def test_settings_file_wins_over_sibling_build_file(tmp_path):
    touch(tmp_path, "project/settings.gradle", "project/build.gradle", "tools/build.gradle.kts")
    assert detect_project_root(tmp_path)[0] == "project"


def test_ignored_and_hidden_directories_are_skipped(tmp_path):
    touch(tmp_path, "node_modules/x/build.gradle.kts", ".gradle/y/build.gradle.kts", "build/z/build.gradle.kts",
          "real/build.gradle.kts")
    assert detect_project_root(tmp_path)[0] == "real"


def test_no_gradle_anywhere_keeps_root(tmp_path):
    touch(tmp_path, "src/main/kotlin/A.kt", "README.md")
    assert detect_project_root(tmp_path) == (None, [])


def test_depth_is_bounded(tmp_path):
    touch(tmp_path, "a/b/c/d/e/build.gradle.kts")
    assert detect_project_root(tmp_path) == (None, [])


def test_code_outside_the_gradle_folder_keeps_the_whole_root(tmp_path):
    """A sample/tool Gradle build must not hide the main code: narrow only when nothing to scan is left outside."""
    touch(tmp_path, "src/main/kotlin/Main.kt", "samples/demo/build.gradle.kts", "samples/demo/src/main/kotlin/D.kt")
    assert detect_project_root(tmp_path) == (None, ["samples/demo"])


def test_non_code_files_outside_do_not_block_narrowing(tmp_path):
    touch(tmp_path, "README.md", "docs/a.md", "ground-truth/x.json", "scripts/run.sh",
          "training-project/build.gradle.kts", "training-project/src/main/kotlin/A.kt")
    assert detect_project_root(tmp_path)[0] == "training-project"
