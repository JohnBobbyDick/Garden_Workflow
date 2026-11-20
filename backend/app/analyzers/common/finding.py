"""Unified finding model shared by all analyzers, the engine, exports and the AI layer."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

Category = Literal["SECRET", "SAST", "SCA"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

SEVERITY_ORDER: dict[str, int] = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
MAX_RANGE_LINES = 15

# Higher = more specific. Used to pick one class when several rules flag the same problem.
CLASS_SPECIFICITY: dict[str, int] = {
    "private-key": 100,
    "aws-access-key": 95,
    "github-token": 94,
    "telegram-token": 93,
    "slack-token": 92,
    "stripe-key": 92,
    "google-api-key": 91,
    "jwt": 90,
    "db-credentials": 85,
    "recoverable-token": 80,
    "secret-fallback": 75,
    "configuration-token": 70,
    "password": 60,
    "api-key": 60,
    "basic-auth": 55,
    "url-credentials": 55,
    "generic-secret": 10,
}


class Location(BaseModel):
    path: str
    line: int
    end_line: int | None = None


class CvssInfo(BaseModel):
    score: float | None = None
    vector: str | None = None
    source_severity: str | None = None


class Finding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: Category
    cls: str = Field(alias="class")
    rule_id: str
    title: str
    description: str = ""
    remediation: str = ""
    severity: Severity = "MEDIUM"
    severity_reason: str = ""
    confidence: float = 0.8
    path: str
    line: int = 1
    end_line: int | None = None
    snippet: str = ""
    cwe: str | None = None
    alternate_locations: list[Location] = Field(default_factory=list)
    # context used for the stable id (symbol name, yaml key path, coordinates...), never a secret value
    context_key: str = ""
    # SCA
    group: str | None = None
    artifact: str | None = None
    version: str | None = None
    declared_version: str | None = None
    version_source: str | None = None
    advisory_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    cvss: CvssInfo | None = None
    fixed_versions: list[str] = Field(default_factory=list)
    scope: str | None = None
    direct: bool | None = None
    sources: list[str] = Field(default_factory=list)
    # SECRET
    value_fingerprint: str | None = None
    masked_value: str | None = None
    # diff-aware (only with diff context)
    diff_status: Literal["new", "existing"] | None = None
    diff_hunk: str | None = None
    introduced_in_commit: str | None = None
    author: str | None = None
    version_changed: bool | None = None  # SCA: same vulnerability as in base, but the version moved
    # remediation automation
    autofix: Literal["llm", "deterministic", "none"] = "none"
    # emitted by an analyzer node
    node_id: str | None = None

    @model_validator(mode="after")
    def _normalize_range(self) -> Finding:
        if self.line < 1:
            self.line = 1
        if self.end_line is None or self.end_line < self.line:
            self.end_line = self.line
        if self.end_line > self.line + MAX_RANGE_LINES - 1:
            self.end_line = self.line + MAX_RANGE_LINES - 1
        self.path = self.path.replace("\\", "/")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        if self.category == "SCA":
            key = f"SCA|{self.path}|{self.group}:{self.artifact}|{self.advisory_id}"
        else:
            ctx = self.context_key or (self.value_fingerprint or "") or str(self.line)
            key = f"{self.category}|{self.rule_id}|{self.path}|{ctx}"
        return "f_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    @property
    def severity_rank(self) -> int:
        return SEVERITY_ORDER[self.severity]


def _overlaps(a: Finding, b: Finding) -> bool:
    return a.line <= (b.end_line or b.line) and b.line <= (a.end_line or a.line)


def _better(a: Finding, b: Finding) -> Finding:
    sa, sb = CLASS_SPECIFICITY.get(a.cls, 50), CLASS_SPECIFICITY.get(b.cls, 50)
    if sa != sb:
        return a if sa > sb else b
    if a.confidence != b.confidence:
        return a if a.confidence > b.confidence else b
    return a if (a.end_line - a.line) >= (b.end_line - b.line) else b


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """One problem = one finding.

    SECRET: same file and (same value fingerprint or overlapping lines) → keep the most specific class.
    SAST: same file, same class, overlapping lines → keep one. SCA: same coordinates + advisory → keep one.
    """
    kept: list[Finding] = []
    for f in findings:
        merged = False
        for i, k in enumerate(kept):
            if k.category != f.category or k.path != f.path:
                continue
            same = False
            if f.category == "SECRET":
                same = bool(f.value_fingerprint and f.value_fingerprint == k.value_fingerprint) or _overlaps(f, k)
            elif f.category == "SAST":
                same = f.cls == k.cls and _overlaps(f, k)
            else:
                same = (f.group, f.artifact, f.advisory_id) == (k.group, k.artifact, k.advisory_id)
            if same:
                kept[i] = _better(k, f)
                merged = True
                break
        if not merged:
            kept.append(f)
    return kept
