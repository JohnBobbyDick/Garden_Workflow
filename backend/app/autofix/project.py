"""Compose reviewed patches on a disposable source tree and package the recheck input."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import Session

from app import models as m
from app.analyzers.common.finding import Finding
from app.analyzers.runner import analyze_project
from app.autofix.context import SecretIndex
from app.autofix.sca_bump import plan_bump
from app.autofix.source import restored_source
from app.autofix.validator import FileEdit, Validation, apply_and_check, reapply
from app.config import get_settings
from app.core.masking import global_masker
from app.core.repo_guard import ExtractLimits, safe_extract
from app.engine.services import read_upload


def project_zip(root: Path) -> bytes:
    settings = get_settings()
    buf = io.BytesIO()
    size = count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if ".git" in rel.parts or p.is_symlink() or not p.is_file():
                continue
            count += 1
            file_size = p.stat().st_size
            size += file_size
            if (count > settings.upload_max_files or size > settings.upload_max_unpacked_bytes
                    or file_size > ExtractLimits().max_file_bytes):
                raise ValueError("проект превышает лимит размера или количества файлов")
            # safe_extract unwraps one top-level directory, including in single-directory projects.
            archive.write(p, "project/" + rel.as_posix())
    return buf.getvalue()


def download_zip(upload: m.Upload) -> bytes:
    data = read_upload(upload)
    settings = get_settings()
    limits = ExtractLimits(settings.upload_max_files, settings.upload_max_unpacked_bytes)
    masker = global_masker.child()
    with TemporaryDirectory() as tmp:
        root = safe_extract(data, upload.filename, Path(tmp), limits)
        masker.register(*SecretIndex.scan(root).all_values())

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as dest:
        for info in src.infolist():
            # Round-trip untouched bytes, including binary assets, and preserve original file modes.
            body = src.read(info).decode("utf-8", errors="surrogateescape")
            name = info.filename.removeprefix("project/")
            path = Path(name)
            config = path.suffix.lower() in {".properties", ".yaml", ".yml", ".json"} or path.name.startswith(".env")
            mask = masker.mask if config else masker.mask_known
            info.filename = masker.mask_known(name)
            dest.writestr(info, mask(body).encode("utf-8", errors="surrogateescape"))
    return buf.getvalue()


def patched_archive(s: Session, run: m.Run, fixes: list[m.Autofix]) -> tuple[bytes, list[str], list[str]]:
    applied: list[str] = []
    skipped: list[str] = []
    with restored_source(s, run) as root:
        for af in fixes:
            baseline = analyze_project(root).findings
            target = next((f for f in baseline if f.id == af.finding_id), None)
            if target is None:
                skipped.append(af.id)
                continue
            try:
                edits = _edits(root, target, af)
                checked = apply_and_check(Validation(), root, edits, target, baseline)
                if checked.status != "validated":
                    raise ValueError(checked.reason)
            except ValueError:
                if len(fixes) == 1:
                    raise
                skipped.append(af.id)
                continue
            for edit in edits:
                path = root / edit.path
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError("путь исправления выходит за пределы проекта")
                path.write_text(edit.after, encoding="utf-8")
            applied.append(af.id)
        if not applied:
            raise ValueError("ни одно исправление не применилось к текущим исходникам")
        return project_zip(root), applied, skipped


def _edits(root: Path, finding: Finding, af: m.Autofix) -> list[FileEdit]:
    if af.kind == "deterministic":
        return plan_bump(root, finding)[1]
    return reapply(root, af.proposal, SecretIndex.scan(root))
