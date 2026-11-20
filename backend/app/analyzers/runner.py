"""Runs all three analyzers over one project root and returns a single deduplicated finding set."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.common.finding import Finding
from app.analyzers.sast.detector import SastConfig, scan_sast
from app.analyzers.sca.detector import scan_sca
from app.analyzers.sca.vulndb import VulnDB
from app.analyzers.secrets.detector import SecretsConfig, scan_secrets


@dataclass
class AnalysisResult:
    findings: list[Finding]
    notes: list[dict] = field(default_factory=list)


def analyze_project(root: str | Path, db: VulnDB | None = None, secrets: SecretsConfig | None = None,
                    sast: SastConfig | None = None, include_transitive: bool = False) -> AnalysisResult:
    root = Path(root)
    db = db or VulnDB.load()
    sca = scan_sca(root, db, include_transitive=include_transitive)
    findings = scan_secrets(root, secrets) + scan_sast(root, sast) + sca.findings
    return AnalysisResult(findings, sca.notes)
