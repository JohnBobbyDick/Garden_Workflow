"""SCA diff by versions, not lines: the same SCA parser runs on the base build files and on head.

Key ``(group, artifact, advisoryId)``: new = not vulnerable in base (dependency added, or the version moved into a
vulnerable range — also via ``gradle.properties`` / ``val`` / catalog / lockfile only); existing = was in base, even if
the version changed (``version_changed``); vulnerabilities that were in base and disappeared → ``fixed_in_diff``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath

from app.analyzers.common.finding import Finding
from app.analyzers.sca.detector import scan_sca
from app.analyzers.sca.vulndb import VulnDB


def sca_key(f: Finding) -> tuple[str, str, str]:
    return (f.group or "", f.artifact or "", f.advisory_id or "")


def scan_base(base_files: dict[str, str], db: VulnDB, include_transitive: bool = False,
              include_test_scopes: bool = True) -> list[Finding]:
    """Run the SCA analyzer over the base versions of the build files (materialized in a private temp dir)."""
    with tempfile.TemporaryDirectory(prefix="aisw-base-") as tmp:
        root = Path(tmp)
        for rel, content in base_files.items():
            pp = PurePosixPath(rel)
            if pp.is_absolute() or ".." in pp.parts or not pp.parts:
                continue
            dst = root.joinpath(*pp.parts)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content, encoding="utf-8")
        return scan_sca(root, db, include_transitive, include_test_scopes).findings


def diff_sca(head: list[Finding], base: list[Finding]) -> tuple[dict[str, dict], list[dict]]:
    """Returns ({finding_id: {diff_status, version_changed}}, fixed_in_diff)."""
    base_by_key = {sca_key(f): f for f in base if f.category == "SCA"}
    head_keys = set()
    status: dict[str, dict] = {}
    for f in head:
        if f.category != "SCA":
            continue
        key = sca_key(f)
        head_keys.add(key)
        prev = base_by_key.get(key)
        if prev is None:
            status[f.id] = {"diff_status": "new", "version_changed": None}
        else:
            status[f.id] = {"diff_status": "existing", "version_changed": (prev.version or "") != (f.version or "")}
    fixed = [{"group": k[0], "artifact": k[1], "advisory_id": k[2], "version": f.version, "severity": f.severity,
              "path": f.path, "line": f.line} for k, f in sorted(base_by_key.items()) if k not in head_keys]
    return status, fixed
