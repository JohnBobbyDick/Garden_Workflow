"""Score history helpers: scanner-set signature and least-squares trend (points per week)."""

from __future__ import annotations

from datetime import datetime


def scanner_set_signature(graph: dict | None) -> str:
    """Which analyzers produced the findings: a different set makes scores incomparable (marker on the chart)."""
    types = {n.get("type", "") for n in (graph or {}).get("nodes", [])
             if str(n.get("type", "")).startswith("scanner.") and n.get("type") != "scanner.diff"
             and not n.get("disabled")}
    return "+".join(sorted(types))


def linear_trend(points: list[tuple[datetime, float]]) -> dict:
    """OLS slope of score over time, in points per week; fewer than 3 points → not enough data."""
    if len(points) < 3:
        return {"enough_data": False, "slope_per_week": None, "points": len(points)}
    t0 = min(t for t, _ in points)
    xs = [(t - t0).total_seconds() / 86400 / 7 for t, _ in points]
    ys = [float(v) for _, v in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return {"enough_data": False, "slope_per_week": None, "points": n}
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    return {"enough_data": True, "slope_per_week": round(slope, 4), "points": n,
            "intercept": round(my - slope * mx, 4)}
