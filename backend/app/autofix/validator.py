"""AutoFix validator (12A.3 §2). Every step is recorded and shown in the UI as a checklist; only ``validated`` fixes
may become a PR. Checked code is never executed: syntax = tree-sitter (no compiler, no Gradle).

Steps: schema → location → old_snippet (masked view, whitespace-normalized) → new_snippet safety (no mask artifacts,
no original secret values, no new secret literals) → apply to a temporary copy → syntax (no new ERROR nodes) →
self-check (all three analyzers on the whole patched copy: the finding is gone, no new findings).
"""

from __future__ import annotations

import difflib
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.ai.validator import schema_errors
from app.analyzers.common.finding import Finding
from app.analyzers.common.kotlin_ast import KotlinFile, iter_nodes
from app.analyzers.common.masking import mask_in_text
from app.analyzers.runner import analyze_project
from app.analyzers.secrets.detector import _signature_candidates
from app.autofix.context import MASK_ARTIFACTS, SecretIndex, allowed_files, read_text
from app.core.masking import Masker

RELOCATE_TOLERANCE = 3
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

FIX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["file", "start_line", "end_line", "old_snippet", "new_snippet", "explanation"],
    "properties": {
        "file": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"},
        "old_snippet": {"type": "string"}, "new_snippet": {"type": "string"}, "explanation": {"type": "string"},
        "requires_config": {"type": "array", "items": {"type": "object", "required": ["name", "description"],
                                                       "properties": {"name": {"type": "string"},
                                                                      "description": {"type": "string"}}}},
    },
}


@dataclass
class FileEdit:
    path: str
    before: str
    after: str


@dataclass
class Validation:
    status: str = "rejected"  # validated | rejected
    reason: str | None = None
    steps: list[dict] = field(default_factory=list)
    edits: list[FileEdit] = field(default_factory=list)
    proposal: dict = field(default_factory=dict)
    self_check: dict = field(default_factory=dict)

    def step(self, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append({"name": name, "ok": ok, "detail": detail})
        if not ok and self.reason is None:
            self.reason = f"{name}: {detail}"
        return ok

    def errors(self) -> list[str]:
        return [f"{s['name']}: {s['detail']}" for s in self.steps if not s["ok"]]


def norm(text: str) -> str:
    return " ".join(text.split())


def finding_key(f: Finding) -> tuple:
    return (f.category, f.rule_id, f.cls, f.path, f.group, f.artifact, f.advisory_id)


def error_count(path: str, text: str) -> int | None:
    """Syntax error measure of a file; None = this file type is not syntax-checked."""
    if path.endswith((".kt", ".kts")):
        kf = KotlinFile.parse(path, text)
        return sum(1 for n in iter_nodes(kf.root) if n.type == "ERROR" or n.is_missing)
    if path.endswith((".yml", ".yaml")):
        try:
            list(yaml.safe_load_all(text))
            return 0
        except yaml.YAMLError:
            return 1
    return None


def replace_lines(text: str, start: int, end: int, new_snippet: str) -> str:
    lines = text.splitlines(keepends=True)
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    tail = lines[end - 1] if end - 1 < len(lines) else ""
    new = new_snippet.rstrip("\r\n")
    repl = [ln + nl for ln in new.split("\n")] if new else []
    if repl and not tail.endswith(("\n", "\r")):  # the replaced range was the last line without a newline
        repl[-1] = repl[-1].rstrip("\r\n")
    return "".join(lines[: start - 1] + repl + lines[end:])


def masked_patch(edits: list[FileEdit], secrets: SecretIndex, masker: Masker | None = None) -> str:
    """Unified diff for UI / download. Lines with secrets are masked: a patch removing a secret is for review; patches
    without secrets in changed lines apply with ``git apply``."""
    m = masker or Masker()
    out: list[str] = []
    for e in edits:
        values = secrets.by_file.get(e.path, set())
        for line in difflib.unified_diff(e.before.splitlines(keepends=True), e.after.splitlines(keepends=True),
                                         fromfile=f"a/{e.path}", tofile=f"b/{e.path}"):
            body, nl = (line[:-1], "\n") if line.endswith("\n") else (line, "")
            # added lines are validated secret-free code: only known values/token shapes are masked there
            masker_fn = m.mask_known if body.startswith("+") and not body.startswith("+++") else m.mask
            out.append(masker_fn(mask_in_text(body, values)) + nl)
            if not nl:
                out.append("\n\\ No newline at end of file\n")
    return "".join(out)


def copy_project(root: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="aisw-autofix-"))
    dest = tmp / "p"
    shutil.copytree(root, dest, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    return dest


def apply_and_check(v: Validation, root: Path, edits: list[FileEdit], finding: Finding,
                    baseline: list[Finding]) -> Validation:
    """Steps 5–7: apply to a temporary copy, syntax, self-check with all analyzers."""
    copy = copy_project(root)
    try:
        for e in edits:
            target = (copy / e.path).resolve()
            if not target.is_relative_to(copy.resolve()):
                v.step("apply", False, f"путь вне проекта: {e.path}")
                return v
            target.write_text(e.after, encoding="utf-8")
        v.step("apply", True, f"патч применён к временной копии ({len(edits)} файл(ов))")
        notes = []
        for e in edits:
            before, after = error_count(e.path, e.before), error_count(e.path, e.after)
            if before is None:
                notes.append(f"{e.path}: тип файла не разбирается")
            elif after is not None and after > before:
                v.step("syntax", False, f"{e.path}: новые синтаксические ошибки ({before} → {after})")
                return v
        v.step("syntax", True, "; ".join(["новых ERROR-узлов tree-sitter нет", *notes]))
        after_findings = analyze_project(copy).findings
        base_keys, new_keys = Counter(map(finding_key, baseline)), Counter(map(finding_key, after_findings))
        added = [k for k in new_keys if new_keys[k] > base_keys.get(k, 0)]
        gone = finding.id not in {f.id for f in after_findings} and \
            new_keys.get(finding_key(finding), 0) < base_keys.get(finding_key(finding), 0)
        added_titles = sorted({f"{f.title} ({f.path}:{f.line})" for f in after_findings if finding_key(f) in added})
        v.self_check = {"before": len(baseline), "after": len(after_findings), "finding_gone": gone,
                        "new_findings": added_titles}
        if not gone:
            v.step("self_check", False, "исходная находка не исчезла после патча")
        elif added:
            v.step("self_check", False, f"патч добавляет находки: {'; '.join(added_titles)[:500]}")
        else:
            v.step("self_check", True, f"находка устранена, 0 новых (было {len(baseline)}, стало "
                                       f"{len(after_findings)})")
            v.status, v.reason = "validated", None
        return v
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)


def validate_llm_fix(data: Any, ctx: dict, root: Path, finding: Finding, secrets: SecretIndex,
                     baseline: list[Finding], masker: Masker | None = None) -> Validation:
    v = Validation()
    # 1. schema
    errs = schema_errors(data, FIX_SCHEMA) if isinstance(data, dict) else ["ответ не JSON-объект"]
    if not v.step("schema", not errs, "; ".join(errs[:5]) or "ответ соответствует схеме"):
        return v
    req = [{"name": str(r["name"]), "description": str(r["description"])[:300]}
           for r in data.get("requires_config") or []]
    bad_env = [r["name"] for r in req if not ENV_NAME.match(r["name"])]
    # 2. file and lines
    files = allowed_files(ctx)
    path, start, end = str(data["file"]).replace("\\", "/"), int(data["start_line"]), int(data["end_line"])
    if path not in files:
        v.step("location", False, f"файл {path!r} не входит в контекст находки")
        return v
    if not (1 <= start <= end <= files[path]):
        v.step("location", False, f"строки {start}–{end} вне файла ({files[path]} строк)")
        return v
    if bad_env:
        v.step("location", False, f"недопустимые имена переменных окружения: {', '.join(bad_env)[:200]}")
        return v
    v.step("location", True, f"{path}:{start}–{end}")
    # 3. old_snippet literally matches the masked view of those lines (whitespace-normalized)
    text = read_text(root, path) or ""
    masked = secrets.masked_lines(path, text, masker)
    want = norm(str(data["old_snippet"]))
    span = end - start
    found = None
    for delta in sorted(range(-RELOCATE_TOLERANCE, RELOCATE_TOLERANCE + 1), key=abs):
        s = start + delta
        if 1 <= s and s + span <= len(masked) and norm("\n".join(masked[s - 1: s + span])) == want and want:
            found = s
            break
    if found is None:
        v.step("old_snippet", False, "old_snippet не совпадает с указанными строками файла (возможна галлюцинация)")
        return v
    v.step("old_snippet", True, "совпадает с файлом" if found == start else
           f"совпадает с файлом (строки скорректированы на {found - start:+d})")
    start, end = found, found + span
    # 4. new_snippet safety
    new = str(data["new_snippet"])
    problems = []
    if any(a in new for a in MASK_ARTIFACTS):
        problems.append("содержит артефакты маскирования")
    if any(len(val) >= 4 and val in new for val in secrets.all_values()):
        problems.append("содержит исходное значение секрета")
    if _signature_candidates(new, False):
        problems.append("содержит новый литерал, похожий на секрет")
    if not v.step("new_snippet", not problems, "; ".join(problems) or "без секретов и масок"):
        return v
    v.proposal = {"file": path, "start_line": start, "end_line": end, "old_snippet": str(data["old_snippet"]),
                  "new_snippet": new, "explanation": str(data["explanation"])[:4000], "requires_config": req}
    edits = [FileEdit(path, text, replace_lines(text, start, end, new))]
    v.edits = edits
    return apply_and_check(v, root, edits, finding, baseline)


def reapply(root: Path, proposal: dict, secrets: SecretIndex) -> list[FileEdit]:
    """Re-create real file contents from a stored (masked, secret-free) proposal on freshly restored sources."""
    path, start, end = proposal["file"], int(proposal["start_line"]), int(proposal["end_line"])
    text = read_text(root, path)
    if text is None:
        raise ValueError(f"файл {path} не найден в восстановленных исходниках")
    masked = secrets.masked_lines(path, text)
    if norm("\n".join(masked[start - 1: end])) != norm(proposal["old_snippet"]):
        raise ValueError("исходники изменились: old_snippet больше не совпадает")
    return [FileEdit(path, text, replace_lines(text, start, end, proposal["new_snippet"]))]
