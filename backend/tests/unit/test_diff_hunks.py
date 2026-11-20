from app.analyzers.diff.hunks import parse_unified_diff, relativize

MULTI = """diff --git a/src/A.kt b/src/A.kt
index 1111111..2222222 100644
--- a/src/A.kt
+++ b/src/A.kt
@@ -3,0 +4,2 @@ class A {
+    val a = 1
+    val b = 2
@@ -10 +12 @@ fun x() {
-    old()
+    new()
@@ -20,3 +22,0 @@ fun y() {
-    gone1()
-    gone2()
-    gone3()
diff --git a/src/New.kt b/src/New.kt
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/New.kt
@@ -0,0 +1,3 @@
+package x
+
+val k = "v"
diff --git a/src/Old.kt b/src/Old.kt
deleted file mode 100644
index 4444444..0000000
--- a/src/Old.kt
+++ /dev/null
@@ -1,2 +0,0 @@
-package y
-val z = 1
diff --git a/src/Moved.kt b/src/pkg/Moved.kt
similarity index 100%
rename from src/Moved.kt
rename to src/pkg/Moved.kt
diff --git a/src/Ren.kt b/src/Ren2.kt
similarity index 90%
rename from src/Ren.kt
rename to src/Ren2.kt
index 5555555..6666666 100644
--- a/src/Ren.kt
+++ b/src/Ren2.kt
@@ -5 +5 @@
-val p = 1
+val p = 2
diff --git a/img.png b/img.png
index 7777777..8888888 100644
Binary files a/img.png and b/img.png differ
"""


def test_parses_multiple_hunks_new_deleted_renamed_binary():
    m = parse_unified_diff(MULTI)
    a = m["src/A.kt"]
    assert a.new_lines == {4, 5, 12}
    assert [(h.old_start, h.old_count, h.new_start, h.new_count) for h in a.hunks] == [(3, 0, 4, 2), (10, 1, 12, 1),
                                                                                       (20, 3, 22, 0)]
    assert a.hunks[0].header == "@@ -3,0 +4,2 @@"
    assert a.hunk_for(12).header == "@@ -10 +12 @@"
    assert m["src/New.kt"].status == "added" and m["src/New.kt"].new_lines == {1, 2, 3}
    assert "src/Old.kt" not in m  # deleted files cannot carry head findings
    moved = m["src/pkg/Moved.kt"]
    assert moved.renamed_from == "src/Moved.kt" and moved.new_lines == set()  # pure move: nothing new
    assert m["src/Ren2.kt"].renamed_from == "src/Ren.kt" and m["src/Ren2.kt"].new_lines == {5}
    assert m["img.png"].status == "binary" and m["img.png"].new_lines == set()


def test_quoted_paths_and_no_newline_marker():
    text = ('diff --git "a/src/\\321\\204.kt" "b/src/\\321\\204.kt"\n--- "a/src/\\321\\204.kt"\n'
            '+++ "b/src/\\321\\204.kt"\n@@ -1 +1 @@\n-x\n+y\n\\ No newline at end of file\n')
    m = parse_unified_diff(text)
    assert m["src/ф.kt"].new_lines == {1}


def test_whitespace_only_diff_is_empty():
    # produced by `git diff -w --ignore-blank-lines` on a reformat: header only, no hunks
    text = "diff --git a/src/A.kt b/src/A.kt\nindex 1..2 100644\n"
    m = parse_unified_diff(text)
    assert m.get("src/A.kt") is None or m["src/A.kt"].new_lines == set()


def test_relativize_to_project_root():
    m = parse_unified_diff(MULTI.replace("src/", "training-project/src/"))
    rel = relativize(m, "training-project")
    assert set(rel) >= {"src/A.kt", "src/New.kt"} and "img.png" not in rel
    assert rel["src/pkg/Moved.kt"].renamed_from == "src/Moved.kt"
    assert relativize(m, "") is m or set(relativize(m, "")) == set(m)
