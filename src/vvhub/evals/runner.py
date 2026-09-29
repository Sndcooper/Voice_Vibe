"""Run the routing eval: accuracy, latency and memory of the current Laya tier.

    python -m vvhub eval [--tier gpu|onnx|cpu|keywords] [--file F] [--json] [--limit N]

The first request pays the model load; it is reported separately
(`load_ms`) and left out of the latency percentiles, which are what a user
waits on once the hub is warm.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .. import laya_engine, smart_router

INTENTS = Path(__file__).with_name("intents.jsonl")


def load_intents(path: str | Path | None = None) -> list[dict]:
    rows = []
    with open(path or INTENTS, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(json.loads(line))
    return rows


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process(os.getpid()).memory_info().rss / 2**20, 1)
    except Exception:
        return None


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[index], 1)


async def _evaluate(rows: list[dict], hub: Any) -> dict:
    per: dict[str, dict[str, int]] = {}
    confusions, latencies = [], []
    action_total = action_right = 0
    critical_total = critical_caught = 0
    safe_total = safe_asked = 0
    asked: list[dict] = []
    action_misses: list[dict] = []
    rss_before = _rss_mb()
    started = time.perf_counter()
    laya_engine.engine().warm()  # raises LayaUnavailable; the router would swallow it
    load_ms = round((time.perf_counter() - started) * 1000, 1)
    rss_loaded = _rss_mb()
    for row in rows:
        started = time.perf_counter()
        decision = await smart_router.decide(hub, row["text"], row.get("context") or {})
        latencies.append((time.perf_counter() - started) * 1000)
        got = decision.category if decision else None
        bucket = per.setdefault(row["category"], {"n": 0, "correct": 0})
        bucket["n"] += 1
        if got == row["category"]:
            bucket["correct"] += 1
        else:
            confusions.append({"text": row["text"], "expected": row["category"], "got": got})
        if row.get("action") and decision is not None and decision.action:
            action_total += 1
            action_right += decision.action == row["action"]
            if decision.action != row["action"]:
                action_misses.append({"text": row["text"], "expected": row["action"],
                                      "got": decision.action})
        if row.get("critical"):
            critical_total += 1
            critical_caught += bool(decision and (decision.critical or decision.needs_approval))
        else:
            safe_total += 1
            if decision is not None and decision.action and decision.needs_approval:
                safe_asked += 1
                asked.append({"text": row["text"], "reason": decision.reason})
    n = len(rows)
    correct = sum(b["correct"] for b in per.values())
    report = {
        "n": n,
        "tier": laya_engine.engine().tier,
        "category_accuracy": round(correct / n, 4) if n else 0.0,
        "per_category": per,
        "confusions": confusions,
        "load_ms": load_ms,
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95),
                       "max": round(max(latencies), 1) if latencies else 0.0},
        "rss_mb": {"before": rss_before, "loaded": rss_loaded, "after": _rss_mb()},
    }
    if action_total:
        report["action_accuracy"] = round(action_right / action_total, 4)
        report["action_n"] = action_total
        report["action_misses"] = action_misses
    if critical_total:
        report["critical_caught"] = f"{critical_caught}/{critical_total}"
    report["safe_asked"] = f"{safe_asked}/{safe_total}"
    report["asked"] = asked
    return report


class _EvalHub:
    """Enough of a hub for the router: the real skills, nothing connected."""

    def __init__(self) -> None:
        from ..skills import discover

        self.skills = discover(self)
        self.store = self.bus = None


def run_eval(rows: list[dict], hub: Any = None) -> dict:
    return asyncio.run(_evaluate(rows, hub if hub is not None else _EvalHub()))


def format_report(report: dict) -> str:
    lines = [
        f"Laya tier: {report['tier']}   requests: {report['n']}",
        f"category accuracy: {report['category_accuracy'] * 100:.1f}%",
    ]
    if "action_accuracy" in report:
        lines.append(f"action accuracy:   {report['action_accuracy'] * 100:.1f}% "
                     f"(of {report['action_n']} with a known action)")
    if "critical_caught" in report:
        lines.append(f"critical flagged:  {report['critical_caught']}")
    if "safe_asked" in report:
        lines.append(f"asked on safe:     {report['safe_asked']}")
    lat = report["latency_ms"]
    lines.append(f"latency ms: load {report['load_ms']}, "
                 f"p50 {lat['p50']}, p95 {lat['p95']}, max {lat['max']}")
    rss = report["rss_mb"]
    lines.append(f"RSS MB: before {rss['before']}, model loaded {rss['loaded']}, "
                 f"after {rss['after']}")
    lines.append("per category:")
    for category, b in sorted(report["per_category"].items()):
        lines.append(f"  {category:<9} {b['correct']:>3}/{b['n']:<3}")
    if report["confusions"]:
        lines.append("misses:")
        for miss in report["confusions"]:
            lines.append(f"  {miss['expected']:>9} -> {str(miss['got']):<9} {miss['text']}")
    if report.get("action_misses"):
        lines.append("action misses:")
        for miss in report["action_misses"]:
            lines.append(f"  {miss['expected']:>14} -> {miss['got']:<14} {miss['text']}")
    if report.get("asked"):
        lines.append("asked on safe requests:")
        for a in report["asked"]:
            lines.append(f"  {a['text']}  [{a['reason']}]")
    return "\n".join(lines)


def _default_engine(tier: str | None) -> laya_engine.Engine:
    # No fallback: an eval must say which tier it really measured.
    return laya_engine.Engine(tier=tier or laya_engine.detect_tier(), idle_seconds=1e9)


def main(argv: list[str] | None = None,
         engine_factory: Callable[[str | None], Any] = _default_engine) -> int:
    parser = argparse.ArgumentParser(prog="vvhub eval", description=__doc__.splitlines()[0])
    parser.add_argument("--tier", choices=laya_engine.TIERS)
    parser.add_argument("--file", help="intents JSONL (default: the bundled one)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rows = load_intents(args.file)
    if args.limit:
        rows = rows[: args.limit]
    engine = engine_factory(args.tier)
    old = laya_engine.set_engine(engine) if engine is not None else None
    try:
        try:
            report = run_eval(rows)
        except laya_engine.LayaUnavailable as exc:
            print(f"Laya tier {laya_engine.engine().tier} unavailable: {exc}", file=sys.stderr)
            return 1
    finally:
        if engine is not None:
            laya_engine.set_engine(old)
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0
