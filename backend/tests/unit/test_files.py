from app.analyzers.common.files import walk_project


def test_walk_skips_build_git_binary_and_gitignored(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "A.kt").write_text("class A")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "B.kt").write_text("class B")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "lib.jar").write_bytes(b"PK\x03\x04\x00\x00binary")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "G.kt").write_text("class G")
    (tmp_path / ".gitignore").write_text("/generated/\n*.log\n")
    (tmp_path / "x.log").write_text("log")
    (tmp_path / "big.txt").write_text("a" * 3000)
    files = walk_project(tmp_path, max_file_size=2000)
    assert sorted(f.rel for f in files) == [".gitignore", "src/A.kt"]


def test_include_exclude_globs(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.kt").write_text("1")
    (tmp_path / "a" / "y.yml").write_text("1")
    (tmp_path / "a" / "z.kt").write_text("1")
    files = walk_project(tmp_path, include=["**/*.kt"], exclude=["**/z.kt"])
    assert [f.rel for f in files] == ["a/x.kt"]
