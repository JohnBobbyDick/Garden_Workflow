"""SCA detector: build files → resolved dependencies → vulnerability snapshot → findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.common.files import safe_file
from app.analyzers.common.finding import CvssInfo, Finding, Location
from app.analyzers.common.severity import sca_severity
from app.analyzers.sca.cvss import cvss3_base_score
from app.analyzers.sca.gradle_parser import Dependency, module_build_files, parse_build_file
from app.analyzers.sca.lockfile import LockEntry, read_lockfile
from app.analyzers.sca.version_catalog import load_catalog
from app.analyzers.sca.versions import UnsupportedVersion, is_vulnerable, nearest_fixed_version, parse_version
from app.analyzers.sca.vulndb import VulnDB


@dataclass
class ScaResult:
    findings: list[Finding]
    notes: list[dict] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)


def _advisory_id(entry: dict) -> str:
    for alias in entry.get("aliases", []):
        if alias.startswith("CVE-"):
            return alias
    return entry["id"]


def _cvss(entry: dict) -> CvssInfo:
    for c in entry.get("cvss", []):
        if c.get("type", "").upper().startswith("CVSS_V3") and c.get("score", "").startswith("CVSS:3"):
            try:
                return CvssInfo(score=cvss3_base_score(c["score"]), vector=c["score"], source_severity=entry["severity"])
            except ValueError:
                continue
    return CvssInfo(score=None, vector=None, source_severity=entry.get("severity"))


def resolve_dependencies(root: Path, lock: dict[tuple[str, str], LockEntry] | None = None) -> list[Dependency]:
    catalog = load_catalog(root)
    deps: list[Dependency] = []
    for rel in module_build_files(root):
        deps.extend(parse_build_file(root, rel, catalog))
    return deps


def scan_sca(root: str | Path, db: VulnDB, include_transitive: bool = False, include_test_scopes: bool = True,
             build_files_override: dict[str, bytes] | None = None) -> ScaResult:
    root = Path(root)
    notes: list[dict] = []
    lock: dict[tuple[str, str], LockEntry] = {}
    for rel in ("gradle.lockfile",):
        lock.update(read_lockfile(safe_file(root, rel)))
    deps = resolve_dependencies(root, lock)
    findings: list[Finding] = []
    seen_coords: set[tuple[str, str]] = set()

    def check(group: str, artifact: str, version: str | None, declared: str | None, source: str, path: str,
              line: int, end_line: int, alts: list[Location], scope: str, direct: bool) -> None:
        if version is None:
            notes.append({"level": "info", "path": path, "line": line,
                          "message": f"{group}:{artifact}: версия не задана явно (BOM/platform) и не найдена в gradle.lockfile — пропущено"})
            return
        try:
            parse_version(version)
        except UnsupportedVersion:
            notes.append({"level": "info", "path": path, "line": line,
                          "message": f"{group}:{artifact}:{version[:64]}: версия не поддерживается снимком (квалификатор/динамическая) — пропущено"})
            return
        for entry in db.entries_for(group, artifact):
            if not is_vulnerable(version, entry["ranges"]):
                continue
            adv = _advisory_id(entry)
            cv = _cvss(entry)
            sev, reason = sca_severity(cv.score, entry.get("severity"))
            fix = nearest_fixed_version(version, entry.get("fixedVersions", []))
            remediation = (f"Обновить {group}:{artifact} до версии {fix} или новее" if fix
                           else f"Исправленной версии в справочнике нет: заменить {group}:{artifact} или изолировать использование")
            if source.startswith(("variable:", "gradle.properties:", "extra:", "catalog")):
                remediation += f" (версия задаётся в месте определения: {source})"
            findings.append(Finding(
                category="SCA", cls="known-vulnerable-dependency", rule_id="SCA-KNOWN-VULN",
                title=f"Уязвимая зависимость {group}:{artifact}:{version} ({adv})",
                description=(f"Зависимость {group}:{artifact} версии {version} ({'прямая' if direct else 'транзитивная'}, "
                             f"конфигурация/область: {scope}) попадает в уязвимый диапазон {adv} "
                             f"(GHSA {entry['id']}). CVSS: {cv.score if cv.score is not None else 'нет вектора'}."),
                remediation=remediation, severity=sev, severity_reason=reason, confidence=0.95,
                path=path, line=line, end_line=end_line, snippet=f"{group}:{artifact}:{version}",
                cwe="CWE-1395", alternate_locations=alts, context_key=f"{group}:{artifact}:{adv}",
                group=group, artifact=artifact, version=version, declared_version=declared, version_source=source,
                advisory_id=adv, aliases=[entry["id"], *entry.get("aliases", [])], cvss=cv,
                fixed_versions=list(entry.get("fixedVersions", [])), scope=scope, direct=direct,
                sources=list(entry.get("sources", [])), autofix="deterministic",
            ))

    for dep in deps:
        if dep.is_test and not include_test_scopes:
            continue
        seen_coords.add((dep.group, dep.artifact))
        locked = lock.get((dep.group, dep.artifact))
        version = locked.version if locked else dep.declared_version
        source = dep.version_source
        alts = list(dep.alternate_locations)
        if locked and locked.version != dep.declared_version:
            source = "gradle.lockfile"
            alts.append(Location(path="gradle.lockfile", line=locked.line, end_line=locked.line))
        check(dep.group, dep.artifact, version, dep.declared_version, source, dep.path, dep.line, dep.end_line, alts,
              "test" if dep.is_test else dep.configuration, True)

    if include_transitive:
        for (g, a), entry in lock.items():
            if (g, a) in seen_coords:
                continue
            check(g, a, entry.version, None, "gradle.lockfile", "gradle.lockfile", entry.line, entry.line, [],
                  "transitive", False)

    # one advisory per coordinates per file
    uniq: dict[tuple, Finding] = {}
    for f in findings:
        uniq.setdefault((f.path, f.group, f.artifact, f.advisory_id), f)
    return ScaResult(list(uniq.values()), notes, deps)
