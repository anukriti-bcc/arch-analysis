"""Replay a routing policy over recorded M7 results: exact M8 rows, no model needed.

M8 differs from M7 only in WHICH findings are escalated. Every finding M8 escalates is also one M7 escalated
(checked below), with the same bundle and the same prompt, so the model's answer for it is already on record in
the M7 rows (or in the response cache). Replaying the new routing over those rows therefore gives exactly what a
live M8 run would give, at zero cost. `experiments.pipeline_m8` runs M8 live and a test checks the two agree.

  python -m experiments.replay_policy --benchmark /tmp/bench_hard_21 --results ../results/dev_s21_x4/predictions.csv
"""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd

from analysis.policy.gated import ESCALATE, ReadabilityGatedPolicy, apply_budget
from experiments import pipeline
from models.finding import FindingStatus

COPY_FROM_M7 = [
    "predicted_violation", "escalated", "llm_called", "outcome_source", "verdict", "parsed_ok", "error",
    "input_tokens", "output_tokens", "latency_s", "cached", "tokens_estimated", "explanation", "extraction", "computed",
]


def replay(
    benchmark_root: str, m7_rows: pd.DataFrame, *, policy: ReadabilityGatedPolicy | None = None,
    method: str = "M8_gated", budget: int | None = None, splits: tuple[str, ...] | None = None,
    resolver: str = "M7_extract_compute",
) -> tuple[pd.DataFrame, dict]:
    policy = policy or ReadabilityGatedPolicy()
    with open(os.path.join(benchmark_root, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    m7 = m7_rows[m7_rows["method"] == resolver]  # the recorded method whose model answers are reused
    index = {(r.case_id, r.source, r.target): r for r in m7.itertuples(index=False)}
    rows: list[dict] = []
    gaps = 0
    for entry in manifest["cases"]:
        if splits and entry["split"] not in splits:
            continue
        ctx = pipeline.CaseContext(benchmark_root, entry)
        pending: list[tuple[dict, object]] = []
        for f in ctx.findings:
            r = pipeline._row(ctx, method, f)
            if f.status == FindingStatus.VIOLATION:
                d = policy.decide(ctx.bundle(f))
                pending.append((r, d, f))
            rows.append(r)
        decisions = [d for _, d, _ in pending]
        if budget is not None:
            decisions = apply_budget(decisions, budget)
        for (r, _, f), d in zip(pending, decisions):
            r["policy_reasons"] = " | ".join(d.reasons)
            r["failed_gates"] = ",".join(d.failed_gates)
            if not d.escalate:
                r["predicted_violation"] = bool(d.predicted_violation)
                r["outcome_source"] = d.route
                continue
            key = (ctx.case_id, r["source"], r["target"])
            src = index.get(key)
            if src is None or not bool(src.escalated):
                gaps += 1  # M8 escalated something M7 did not: cannot replay, keep structural verdict, report it
                r["outcome_source"] = "replay_gap"
                continue
            for col in COPY_FROM_M7:
                if hasattr(src, col):
                    val = getattr(src, col)
                    r[col] = None if (isinstance(val, float) and val != val) else val
    return pd.DataFrame(rows), {"replay_gaps": gaps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--results", required=True, help="predictions.csv containing M7_extract_compute rows")
    ap.add_argument("--out")
    ap.add_argument("--no-gates", action="store_true")
    ap.add_argument("--keep-weak", action="store_true")
    args = ap.parse_args(argv)
    preds = pd.read_csv(args.results)
    pol = ReadabilityGatedPolicy(weak_irrelevant=not args.keep_weak, use_gates=not args.no_gates)
    out, info = replay(args.benchmark, preds, policy=pol)
    print(info, len(out))
    if args.out:
        out.to_csv(args.out, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
