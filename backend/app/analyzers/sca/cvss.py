"""Own CVSS v3.0/v3.1 base score calculator (FIRST specification formulas)."""

from __future__ import annotations

import math

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_PR_U = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_C = {"N": 0.85, "L": 0.68, "H": 0.5}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}
_REQUIRED = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")


def _roundup(value: float) -> float:
    int_input = round(value * 100000)
    if int_input % 10000 == 0:
        return int_input / 100000.0
    return (math.floor(int_input / 10000) + 1) / 10.0


def parse_vector(vector: str) -> dict[str, str]:
    parts = vector.strip().split("/")
    if not parts or not parts[0].startswith("CVSS:3"):
        raise ValueError(f"not a CVSS v3 vector: {vector!r}")
    metrics: dict[str, str] = {}
    for part in parts[1:]:
        if ":" not in part:
            raise ValueError(f"malformed metric {part!r}")
        k, v = part.split(":", 1)
        metrics[k] = v
    for key in _REQUIRED:
        if key not in metrics:
            raise ValueError(f"missing metric {key} in {vector!r}")
    return metrics


def cvss3_base_score(vector: str) -> float:
    m = parse_vector(vector)
    try:
        scope_changed = m["S"] == "C"
        if m["S"] not in ("U", "C"):
            raise KeyError("S")
        av, ac, ui = _AV[m["AV"]], _AC[m["AC"]], _UI[m["UI"]]
        pr = (_PR_C if scope_changed else _PR_U)[m["PR"]]
        c, i, a = _CIA[m["C"]], _CIA[m["I"]], _CIA[m["A"]]
    except KeyError as exc:
        raise ValueError(f"invalid metric value in {vector!r}: {exc}") from exc
    iss = 1 - (1 - c) * (1 - i) * (1 - a)
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if scope_changed else 6.42 * iss
    exploitability = 8.22 * av * ac * pr * ui
    if impact <= 0:
        return 0.0
    if scope_changed:
        return _roundup(min(1.08 * (impact + exploitability), 10))
    return _roundup(min(impact + exploitability, 10))


def severity_from_score(score: float) -> str:
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"
