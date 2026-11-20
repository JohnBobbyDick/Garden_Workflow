"""Secrets detector: orchestrates signature, name-context, Kotlin AST, fallback and entropy layers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.common.files import ProjectFile, walk_project
from app.analyzers.common.finding import Finding, dedupe_findings
from app.analyzers.common.kotlin_ast import (
    KotlinFile,
    ProjectIndex,
    is_string_literal,
    iter_nodes,
    node_line,
    plain_string_value,
)
from app.analyzers.common.masking import fingerprint, mask_in_text, mask_value
from app.analyzers.common.severity import is_test_or_doc_path, secret_severity
from app.analyzers.secrets import config_files
from app.analyzers.secrets.entropy import char_classes, entropy_threshold_for, shannon_entropy
from app.analyzers.secrets.kotlin_consts import Candidate, KotlinSecretAnalyzer
from app.analyzers.secrets.rules import (
    AWS_SECRET_NAME,
    HEX40,
    MAVEN_COORDINATE,
    SIGNATURES,
    UUID,
    basic_is_valid,
    jwt_is_valid,
    looks_like_secret,
)

SCANNED_SUFFIXES = {".kt", ".kts", ".java", ".properties", ".yml", ".yaml", ".json", ".xml", ".toml", ".gradle", ".sh",
                    ".sql", ".conf", ".cfg", ".ini", ".md", ".txt", ".pem", ".key", ".env", ".groovy", ".py", ".js",
                    ".ts", ".tf", ".bash", ".zsh"}
SCANNED_NAMES = {"Dockerfile", "docker-compose.yml", ".env", ".npmrc", ".netrc", ".pypirc"}

REMEDIATION = {
    "secret-fallback": "Удалить значение по умолчанию: при отсутствии переменной окружения отключать интеграцию или "
                       "падать с понятной ошибкой. Скомпрометированный секрет перевыпустить.",
    "recoverable-token": "Не собирать секрет из фрагментов в коде: передавать цельное значение из переменной окружения "
                         "или хранилища секретов. Токен перевыпустить.",
    "configuration-token": "Заменить значение ссылкой на переменную окружения без встроенного значения (например "
                           "`${SERVICE_TOKEN}`), а заголовок собирать в коде адаптера. Токен перевыпустить.",
}
DEFAULT_REMEDIATION = ("Вынести секрет в переменную окружения или хранилище секретов (Vault, Kubernetes Secret) без "
                       "литерала по умолчанию, маскировать при журналировании и перевыпустить скомпрометированное значение.")

CLASS_TITLES = {
    "password": "Встроенный пароль", "api-key": "Встроенный ключ API", "configuration-token": "Токен в конфигурации",
    "secret-fallback": "Встроенный секрет по умолчанию", "recoverable-token": "Токен, восстанавливаемый из исходников",
    "private-key": "Приватный ключ", "aws-access-key": "Ключ доступа AWS", "github-token": "Токен GitHub",
    "telegram-token": "Токен Telegram-бота", "jwt": "JSON Web Token", "db-credentials": "Учётные данные БД",
    "generic-secret": "Строка, похожая на секрет", "url-credentials": "Учётные данные в URL",
    "basic-auth": "Учётные данные Basic-аутентификации", "slack-token": "Токен Slack", "stripe-key": "Ключ Stripe",
    "google-api-key": "Ключ Google API",
}


@dataclass
class SecretsConfig:
    include: list[str] | None = None
    exclude: list[str] | None = None
    entropy_threshold: float = 4.0
    heuristics: bool = True
    max_file_size: int = 1_000_000
    extra_exclude: list[str] = field(default_factory=list)


def _in_scope(f: ProjectFile) -> bool:
    return f.suffix in SCANNED_SUFFIXES or f.name in SCANNED_NAMES or f.name.startswith(".env")


def _signature_candidates(text: str, docs: bool) -> list[Candidate]:
    out: list[Candidate] = []
    lines = text.splitlines()
    for sig in SIGNATURES:
        for m in sig.pattern.finditer(text):
            value = m.group(sig.group) if sig.group else m.group(0)
            if sig.cls == "jwt" and not jwt_is_valid(value):
                continue
            if sig.cls == "basic-auth" and not basic_is_valid(value):
                continue
            if sig.cls in ("url-credentials", "db-credentials") and not looks_like_secret(value, min_len=3):
                continue
            line = text.count("\n", 0, m.start()) + 1
            end = line
            if sig.cls == "private-key":
                end_m = re.search(r"-----END [A-Z ]*PRIVATE KEY[A-Z ]*-----", text[m.end():])
                end = min(line + 14, line + text.count("\n", m.end(), m.end() + end_m.start()) if end_m else line)
                body = text[m.end(): m.end() + (end_m.start() if end_m else 0)]
                value = re.sub(r"\s+", "", body) or m.group(0)
                body_lines = [b.strip() for b in body.splitlines() if b.strip()]
                out.append(Candidate(sig.cls, sig.rule_id, line, end, value, 0.95 * (0.6 if docs else 1.0), sig.cls,
                                     sig.title, f"Сигнатура известного формата: {sig.title}", fragments=body_lines))
                continue
            out.append(Candidate(sig.cls, sig.rule_id, line, end, value, 0.95 * (0.6 if docs else 1.0), sig.cls,
                                 sig.title, f"Сигнатура известного формата: {sig.title}"))
    # AWS secret access key near an access key id
    if any(c.cls == "aws-access-key" for c in out):
        for i, raw in enumerate(lines, start=1):
            m = re.search(r"([A-Za-z0-9/+=]{40})", raw)
            if m and AWS_SECRET_NAME.search(raw):
                out.append(Candidate("aws-access-key", "SEC-SIG-AWS-SECRET", i, i, m.group(1), 0.95, "aws-secret",
                                     "AWS Secret Access Key", "Секретный ключ AWS рядом с идентификатором ключа"))
    return out


def _entropy_candidates(kf: KotlinFile, threshold: float, docs: bool) -> list[Candidate]:
    out: list[Candidate] = []
    for n in iter_nodes(kf.root):
        if not is_string_literal(n):
            continue
        v = plain_string_value(n, kf.src)
        if not v or len(v) < 16 or not looks_like_secret(v):
            continue
        if UUID.match(v) or HEX40.match(v) or MAVEN_COORDINATE.match(v) or char_classes(v) < 3:
            continue
        if shannon_entropy(v) < entropy_threshold_for(v, threshold):
            continue
        line = node_line(n)
        out.append(Candidate("generic-secret", "SEC-ENTROPY", line, line, v, 0.45 * (0.6 if docs else 1.0), f"line{line}",
                             "Строка, похожая на секрет", "Высокая энтропия и разнообразие символов (эвристика)"))
    return out


def _to_finding(c: Candidate, f: ProjectFile, lines: list[str]) -> Finding:
    sev, reason = secret_severity(c.cls, f.rel)
    confidence = c.confidence
    if is_test_or_doc_path(f.rel) and not f.rel.lower().endswith(".md"):
        confidence *= 0.6
    secrets_to_mask = [c.value, *c.fragments]
    from app.analyzers.secrets.rules import strip_auth_scheme

    _, bare = strip_auth_scheme(c.value)
    secrets_to_mask.append(bare)
    snippet = mask_in_text("\n".join(lines[c.line - 1: c.end_line]), secrets_to_mask)
    return Finding(
        category="SECRET", cls=c.cls, rule_id=c.rule_id, title=CLASS_TITLES.get(c.cls, c.title),
        description=f"{c.title}: {c.detail}. Файл {f.rel}, строка {c.line}. Значение скрыто ({mask_value(c.value)}).",
        remediation=REMEDIATION.get(c.cls, DEFAULT_REMEDIATION), severity=sev, severity_reason=reason,
        confidence=round(min(confidence, 0.99), 2), path=f.rel, line=c.line, end_line=c.end_line, snippet=snippet,
        cwe="CWE-798", context_key=c.context, value_fingerprint=fingerprint(c.value), masked_value=mask_value(c.value),
        autofix="llm",
    )


def scan_secrets(root: str | Path, config: SecretsConfig | None = None) -> list[Finding]:
    config = config or SecretsConfig()
    root = Path(root)
    files = [f for f in walk_project(root, config.include, (config.exclude or []) + config.extra_exclude,
                                     config.max_file_size) if _in_scope(f)]
    kotlin_files: list[tuple[ProjectFile, KotlinFile]] = []
    for f in files:
        if f.suffix in (".kt", ".kts"):
            kotlin_files.append((f, KotlinFile.parse(f.rel, f.read_bytes())))
    project = ProjectIndex([kf for _, kf in kotlin_files])
    kotlin_by_rel = {f.rel: kf for f, kf in kotlin_files}

    findings: list[Finding] = []
    for f in files:
        text = f.read_text()
        lines = text.splitlines()
        docs = f.suffix in (".md", ".txt") or "/docs/" in f"/{f.rel}"
        cands: list[Candidate] = _signature_candidates(text, docs)
        if f.rel in kotlin_by_rel:
            kf = kotlin_by_rel[f.rel]
            cands += KotlinSecretAnalyzer(kf, project).run()
            if config.heuristics:
                cands += _entropy_candidates(kf, config.entropy_threshold, docs)
        elif f.suffix in (".yml", ".yaml"):
            cands += config_files.scan_yaml(text, docs)
        elif f.suffix == ".properties" or f.name.startswith(".env") or f.suffix == ".env":
            cands += config_files.scan_properties(text, docs)
        elif f.suffix == ".json":
            cands += config_files.scan_json(text, docs)
        elif f.suffix == ".xml":
            cands += config_files.scan_xml(text, docs)
        elif f.suffix not in (".pem", ".key"):
            cands += config_files.scan_generic(text, docs)
        findings.extend(_to_finding(c, f, lines) for c in cands)
    return dedupe_findings(findings)
