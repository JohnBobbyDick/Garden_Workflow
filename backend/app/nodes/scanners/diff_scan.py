from __future__ import annotations

import asyncio
from pathlib import Path

from app.analyzers.diff.classifier import all_new, classify, verdict
from app.analyzers.diff.git import DiffContext, DiffContextError, compute_platform, load_uploaded
from app.analyzers.diff.hunks import DEFAULT_GLOBS
from app.analyzers.diff.sca_diff import scan_base
from app.analyzers.sca.vulndb import VulnDB
from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop

SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
DIFF_FIELDS = ("diff_status", "diff_hunk", "introduced_in_commit", "author", "version_changed")


def find_git_dir(root: Path, boundary: Path) -> Path | None:
    """Nearest directory with ``.git`` from the project root up to (and including) the boundary, never above."""
    root, boundary = root.resolve(), boundary.resolve()
    if root != boundary and boundary not in root.parents:
        return None
    cur = root
    while True:
        if (cur / ".git").exists():
            return cur
        if cur == boundary:
            return None
        cur = cur.parent


@register_node
class DiffScan(BaseNode):
    type = "scanner.diff"
    category = "scanner"
    icon = "split"
    timeout_seconds = 600
    title = {"ru": "Diff-aware: только новые находки", "en": "Diff-aware: new findings only"}
    description = {
        "ru": "Делит готовые находки на новые (появились в этом diff) и существующие. SECRET/SAST — по изменённым "
              "строкам (git diff от merge-base, три точки), SCA — по версиям в base и head. Вердикт FAIL, если есть "
              "новая находка не ниже порога.",
        "en": "Splits finished findings into new (introduced by this diff) and existing. SECRET/SAST by changed lines "
              "(git diff from the merge base, three dots), SCA by base vs head versions. FAIL when a new finding "
              "reaches the threshold."}
    inputs = [Port("repo", "repo", title_ru="Код (git/diff)", title_en="Code (git/diff)"),
              Port("findings", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("new_findings", "findings", title_ru="Новые", title_en="New"),
               Port("existing_findings", "findings", title_ru="Существующие", title_en="Existing"),
               Port("verdict", "json", title_ru="Вердикт", title_en="Verdict")]
    config_schema = obj({
        "base_ref": prop("string", "Базовая ветка", "Base branch",
                         "Для ручного запуска и push без base (по умолчанию main)",
                         "For manual runs and pushes without a base (main by default)", default="main"),
        "threshold": prop("string", "Порог блокировки", "Blocking threshold", enum=SEVERITIES, default="CRITICAL"),
        "report_only": prop("boolean", "Только отчёт (не блокировать)", "Report only (never block)", default=False),
        "on_missing_diff": prop("string", "Если нет git/diff-контекста", "When there is no git/diff context",
                                enum=["fail", "treat_all_as_new"], default="fail"),
        "ignore_whitespace": prop("boolean", "Игнорировать пробельные изменения", "Ignore whitespace-only changes",
                                  default=True),
        "globs": prop("array", "Файлы diff (glob)", "Diff files (glob)", items={"type": "string"},
                      default=list(DEFAULT_GLOBS)),
    })

    def _context(self, ctx, repo: dict, config: dict) -> DiffContext:
        globs = config.get("globs") or list(DEFAULT_GLOBS)
        if repo.get("diff_context"):
            return load_uploaded(repo["diff_context"], globs)
        git = repo.get("git") or {}
        root = Path(repo["root"])
        repo_dir = find_git_dir(root, Path(git.get("boundary") or root))
        if repo_dir is None:
            raise DiffContextError("нет git-истории и diff-контекста: загрузите код через CLI в CI, используйте "
                                   "git_url или включите on_missing_diff = treat_all_as_new")
        token = ctx.secret(git["token_ref"]) if git.get("token_ref") and ctx.has_services else None
        base = git.get("base_sha") or git.get("base_ref") or config.get("base_ref") or "main"
        return compute_platform(repo_dir, root, base, git.get("head_sha") or None, globs,
                                bool(config.get("ignore_whitespace", True)), token)

    async def execute(self, ctx, inputs, config):
        repo = inputs["repo"].data
        findings = findings_of(inputs["findings"])
        threshold = config.get("threshold", "CRITICAL")
        try:
            dctx = await asyncio.to_thread(self._context, ctx, repo, config)
        except DiffContextError as exc:
            if config.get("on_missing_diff", "fail") != "treat_all_as_new":
                raise
            ctx.log("warning", f"diff-контекст недоступен ({exc}); все находки считаются новыми")
            dctx = None
        if dctx is None:
            res = all_new(findings)
            meta = {"base_sha": None, "head_sha": None, "merge_base": None, "diff_available": False}
        else:
            base_sca: list = []
            if any(f.category == "SCA" for f in findings) and dctx.base_files:
                base_sca = await asyncio.to_thread(scan_base, dctx.base_files, VulnDB.load())
            res = await asyncio.to_thread(classify, findings, dctx, base_sca)
            meta = {"base_sha": dctx.base_sha, "head_sha": dctx.head_sha, "merge_base": dctx.merge_base,
                    "diff_available": True, "changed_files": len(dctx.changes)}
        v = {**verdict(res, threshold, bool(config.get("report_only"))), **meta}
        if ctx.has_services:
            ctx.services.annotate_findings({f.id: {k: getattr(f, k) for k in DIFF_FIELDS}
                                            for f in res.new + res.existing})
            ctx.services.update_run(verdict=v)
        ctx.state["verdict"] = v
        ctx.log("info", f"diff: {len(res.new)} новых, {len(res.existing)} существующих → {v['verdict']}"
                        + (f" (порог {v['threshold']})" if v["verdict"] == "FAIL" else ""))
        return {"new_findings": findings_envelope(res.new, ctx.node_id),
                "existing_findings": findings_envelope(res.existing, ctx.node_id),
                "verdict": Envelope.make("json", v, ctx.node_id, f"{v['verdict']}: {len(res.new)} новых")}
