from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath

from app.analyzers.common.files import count_loc, walk_project
from app.config import get_settings
from app.core.repo_guard import ExtractLimits, RepoGuardError, check_ref, check_scan_path, clone_repo, safe_extract
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import credential, obj, prop

MODES = ["project", "upload", "git_url", "path"]


def _subdir(root: Path, sub: str | None) -> Path:
    if not sub:
        return root
    p = PurePosixPath(sub.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        raise RepoGuardError("подкаталог должен быть относительным путём внутри проекта")
    target = (root / Path(*p.parts)).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_dir():
        raise RepoGuardError(f"подкаталог «{sub}» не найден в проекте")
    return target


@register_node
class RepoSource(BaseNode):
    type = "source.repo"
    category = "source"
    icon = "folder-git"
    timeout_seconds = 600
    title = {"ru": "Исходный код", "en": "Source code"}
    description = {
        "ru": "Готовит проверяемый код: загруженный архив, git-репозиторий из allowlist или каталог внутри "
              "разрешённых корней. Код никогда не исполняется.",
        "en": "Prepares the code under test: uploaded archive, allowlisted git repository or a directory inside "
              "allowed roots. The code is never executed."}
    inputs = [Port("in", "trigger", title_ru="Старт", title_en="Start")]
    outputs = [Port("out", "repo", title_ru="Код", title_en="Code")]
    config_schema = obj({
        "mode": prop("string", "Источник", "Source", "project — источник из настроек проекта запуска",
                     "project — source configured in the run's project", enum=MODES, default="project"),
        "git_url": prop("string", "Git URL (https, из allowlist)", "Git URL (https, allowlisted)",
                        **{"x-required-user-input": True}),
        "ref": prop("string", "Ветка / тег / commit", "Branch / tag / commit"),
        "path": prop("string", "Путь (внутри APP_SCAN_ROOTS)", "Path (inside APP_SCAN_ROOTS)"),
        "upload_id": prop("string", "Загруженный архив", "Uploaded archive", **{"x-widget": "upload"}),
        "subdir": prop("string", "Подкаталог проекта", "Project subdirectory",
                       "Корень проверки внутри репозитория, например training-project",
                       "Scan root inside the repository, e.g. training-project"),
        "access_token": credential("Токен доступа (приватный репозиторий)", "Access token (private repo)",
                                   "repo_token"),
    })

    @classmethod
    def validate_config(cls, config):
        errors = []
        mode = config.get("mode", "project")
        if mode == "git_url" and not config.get("git_url"):
            errors.append("для режима git_url укажите URL репозитория")
        if mode == "path" and not config.get("path"):
            errors.append("для режима path укажите путь")
        if config.get("ref"):
            try:
                check_ref(config["ref"])
            except RepoGuardError as exc:
                errors.append(str(exc))
        return errors

    async def execute(self, ctx, inputs, config):
        trig = inputs.get("in")
        spec = dict(config)
        override = (trig.data.get("source") if trig is not None else None) or {}
        # code supplied by the trigger (CI upload, webhook clone) is used only in "project" mode: an explicitly
        # fixed source (path / git_url / upload) is never silently replaced
        if spec.get("mode", "project") == "project" and override.get("mode"):
            spec.update({k: v for k, v in override.items() if v not in (None, "")})
        elif spec.get("mode", "project") == "project":
            project = ctx.services.project_source()
            if not project:
                raise RepoGuardError("у запуска нет проекта: выберите источник кода в ноде или привяжите проект")
            spec = {**project, **{k: v for k, v in spec.items() if k != "mode" and v not in (None, "")},
                    "mode": project.get("mode")}
        mode = spec.get("mode")
        settings = get_settings()
        work = ctx.services.workdir() / f"src-{ctx.node_id}"
        info: dict = {"mode": mode}
        if mode == "path":
            root = check_scan_path(str(spec.get("path") or ""), settings.scan_root_paths())
            info["path"] = root.name
        elif mode == "upload":
            if not spec.get("upload_id"):
                raise RepoGuardError("не указан загруженный архив")
            filename, data = ctx.services.open_upload(spec["upload_id"])
            limits = ExtractLimits(settings.upload_max_files, settings.upload_max_unpacked_bytes)
            root = await asyncio.to_thread(safe_extract, data, filename, work, limits)
            info.update({"upload_id": spec["upload_id"], "filename": filename})
        elif mode == "git_url":
            token = ctx.secret(spec["access_token"]) if spec.get("access_token") else None
            ref = spec.get("ref") or spec.get("head_sha") or None
            meta = await asyncio.to_thread(clone_repo, str(spec.get("git_url") or ""), ref, work,
                                           ctx.services.allowlist(), token)
            root = work
            info.update(meta)
            ctx.services.update_run(source={**info})
        else:
            raise RepoGuardError(f"неизвестный режим источника {mode!r}")
        root = _subdir(root, spec.get("subdir"))
        files = await asyncio.to_thread(walk_project, root)
        loc = count_loc(files)
        ctx.log("info", f"источник {mode}: {len(files)} файлов, {loc} строк")
        data = {"root": str(root), "files": len(files), "loc": loc, "source": info,
                "project_name": ctx.run.project_name or root.name, "diff_context": (trig.data.get("diff_context")
                                                                                   if trig is not None else None)}
        ctx.state["repo"] = data
        return {"out": Envelope.make("repo", data, ctx.node_id, f"{len(files)} файлов")}
