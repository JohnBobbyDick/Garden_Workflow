from __future__ import annotations

from app.analyzers.common.finding import SEVERITY_ORDER
from app.engine.data import findings_of, severity_counts
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop

FAIL_ON = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "none"]


def gate_decision(findings, fail_on: str, verdict: dict | None = None) -> dict:
    if verdict is not None and verdict.get("verdict") in ("PASS", "FAIL"):
        counts = {k.upper(): int(v) for k, v in (verdict.get("new_counts_by_severity") or {}).items()}
        if fail_on == "none":
            failing = 0
        else:
            failing = sum(c for s, c in counts.items() if SEVERITY_ORDER.get(s, 0) >= SEVERITY_ORDER[fail_on])
        gate = "fail" if failing else "pass"
        return {"gate": gate, "basis": "new_findings", "fail_on": fail_on, "failing": failing,
                "reason": f"новых находок уровня ≥ {fail_on}: {failing}" if fail_on != "none" else "политика none"}
    if fail_on == "none":
        return {"gate": "pass", "basis": "all_findings", "fail_on": fail_on, "failing": 0, "reason": "политика none"}
    failing = [f for f in findings if SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER[fail_on]]
    return {"gate": "fail" if failing else "pass", "basis": "all_findings", "fail_on": fail_on,
            "failing": len(failing), "reason": f"находок уровня ≥ {fail_on}: {len(failing)}"}


@register_node
class CiGate(BaseNode):
    type = "output.ci_gate"
    category = "output"
    icon = "shield-check"
    title = {"ru": "CI gate", "en": "CI gate"}
    description = {
        "ru": "Итоговый статус для CI: fail при находках не ниже fail_on (по умолчанию CRITICAL). С входом verdict "
              "от diff-aware сканирования учитываются только новые находки.",
        "en": "Final CI status: fail when findings reach fail_on (CRITICAL by default). With a verdict input from the "
              "diff-aware scan only new findings count."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings"),
              Port("verdict", "json", required=False, title_ru="Вердикт diff", title_en="Diff verdict")]
    outputs = [Port("out", "json", title_ru="Gate", title_en="Gate")]
    config_schema = obj({
        "fail_on": prop("string", "Падать при", "Fail on", enum=FAIL_ON, default="CRITICAL"),
    })

    async def execute(self, ctx, inputs, config):
        findings = findings_of(inputs["in"])
        verdict = inputs["verdict"].data if "verdict" in inputs else None
        decision = gate_decision(findings, config.get("fail_on", "CRITICAL"), verdict)
        decision["counts"] = severity_counts(findings)
        ctx.state["gate"] = decision["gate"]
        if ctx.has_services:
            ctx.services.update_run(gate=decision["gate"])
        ctx.log("info", f"gate={decision['gate']}: {decision['reason']}")
        return {"out": Envelope.make("json", decision, ctx.node_id, f"gate {decision['gate']}")}
