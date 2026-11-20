"""``git blame --porcelain`` parser → {final_line: (commit_sha, author)}.

``author`` is personal data: it is shown only to workspace members and never passed to the LLM or templates.
"""

from __future__ import annotations

import re

HEADER_RE = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)(?: (\d+))?$")


def parse_porcelain(text: str) -> dict[int, tuple[str, str]]:
    commits: dict[str, dict[str, str]] = {}
    out: dict[int, tuple[str, str]] = {}
    cur_sha: str | None = None
    cur_line = 0
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            cur_sha, cur_line = m.group(1), int(m.group(3))
            commits.setdefault(cur_sha, {})
            continue
        if cur_sha is None:
            continue
        if line.startswith("author-mail "):
            commits[cur_sha]["mail"] = line[len("author-mail "):].strip().strip("<>")
        elif line.startswith("author "):
            commits[cur_sha]["name"] = line[len("author "):].strip()
        elif line.startswith("\t"):
            info = commits.get(cur_sha, {})
            out[cur_line] = (cur_sha, info.get("mail") or info.get("name") or "")
    return out
