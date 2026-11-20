"""Change map from ``git diff --unified=0 --find-renames <merge_base>...<head>``.

Result: ``{path: FileChange(new_lines, hunks, renamed_from, status)}`` with paths relative to the repository root;
``relativize`` re-roots them at the scanned project directory. Deleted files are dropped (no head findings can live
there); a pure rename has no new lines, so moved code is not reported as new.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DEFAULT_GLOBS = ("*.kt", "*.kts", "*.gradle", "*.properties", "*.yml", "*.yaml", "*.toml", "gradle.lockfile")


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str


@dataclass
class FileChange:
    path: str
    status: str = "modified"  # added | modified | renamed | binary
    renamed_from: str | None = None
    hunks: list[Hunk] = field(default_factory=list)
    new_lines: set[int] = field(default_factory=set)

    def hunk_for(self, line: int, end_line: int | None = None) -> Hunk | None:
        end = end_line or line
        for h in self.hunks:
            if h.new_count and h.new_start <= end and line <= h.new_start + h.new_count - 1:
                return h
        return None


def _unquote(p: str) -> str:
    """git C-quotes paths with special characters: "a/\\321\\204.kt" -> a/ф.kt"""
    p = p.strip()
    if not (len(p) >= 2 and p[0] == '"' and p[-1] == '"'):
        return p
    body, out, i = p[1:-1], bytearray(), 0
    simple = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r",
              "v": b"\v"}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567" and i + 3 < len(body) + 1 and re.match(r"[0-7]{3}", body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            out += simple.get(nxt, nxt.encode())
            i += 2
            continue
        out += ch.encode()
        i += 1
    return out.decode("utf-8", "replace")


def _strip_side(p: str, side: str) -> str | None:
    p = _unquote(p)
    if p == "/dev/null":
        return None
    return p[2:] if p.startswith(side + "/") else p


def _split_git_header(rest: str) -> tuple[str, str]:
    """`diff --git a/x b/y` (paths possibly quoted)."""
    if rest.startswith('"'):
        m = re.match(r'^("(?:[^"\\]|\\.)*")\s+(.*)$', rest)
        if m:
            return m.group(1), m.group(2)
    half = rest.find(" b/")
    if half != -1:
        return rest[:half], rest[half + 1:]
    a, _, b = rest.partition(" ")
    return a, b


def parse_unified_diff(text: str) -> dict[str, FileChange]:
    files: dict[str, FileChange] = {}
    cur: FileChange | None = None
    deleted = False

    def finish() -> None:
        if cur is not None and not deleted:
            files[cur.path] = cur

    for line in text.splitlines():
        if line.startswith("diff --git "):
            finish()
            _, b = _split_git_header(line[len("diff --git "):])
            cur = FileChange(path=_strip_side(b, "b") or "")
            deleted = False
            continue
        if cur is None:
            continue
        if line.startswith("rename from "):
            cur.renamed_from = _unquote(line[len("rename from "):])
            cur.status = "renamed"
        elif line.startswith("rename to "):
            cur.path = _unquote(line[len("rename to "):])
        elif line.startswith("new file mode"):
            cur.status = "added"
        elif line.startswith("deleted file mode"):
            deleted = True
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            cur.status = "binary"
        elif line.startswith("--- "):
            if _strip_side(line[4:], "a") is None:
                cur.status = "added"
        elif line.startswith("+++ "):
            p = _strip_side(line[4:], "b")
            if p is None:
                deleted = True
            else:
                cur.path = p
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            if not m:
                continue
            os_, oc, ns, nc = int(m[1]), int(m[2] if m[2] is not None else 1), int(m[3]), \
                int(m[4] if m[4] is not None else 1)
            cur.hunks.append(Hunk(os_, oc, ns, nc, m.group(0)))
            cur.new_lines.update(range(ns, ns + nc))
    finish()
    return files


def relativize(changes: dict[str, FileChange], prefix: str) -> dict[str, FileChange]:
    """Re-root repository paths at the scanned project directory (e.g. strip ``training-project/``)."""
    prefix = prefix.strip("/")
    if not prefix:
        return changes
    pre = prefix + "/"
    out: dict[str, FileChange] = {}
    for path, ch in changes.items():
        if not path.startswith(pre):
            continue
        rf = ch.renamed_from[len(pre):] if ch.renamed_from and ch.renamed_from.startswith(pre) else ch.renamed_from
        out[path[len(pre):]] = FileChange(path=path[len(pre):], status=ch.status, renamed_from=rf, hunks=ch.hunks,
                                          new_lines=ch.new_lines)
    return out
