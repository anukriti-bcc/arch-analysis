"""Score the pre-registered fresh-seed criteria P1-P8 (docs/ANALYSIS_PLAN.md) for M8 and M8+attribution.

  python -m experiments.verdict_m8 --runs ../results/m8_confirm_s41 ../results/m8_confirm_s42 ../results/m8_confirm_s43 \
      --benchmarks ../datasets/benchmark/hard_s41 ../datasets/benchmark/hard_s42 ../datasets/benchmark/hard_s43 --out ../results/m8_verdict

Pure analysis: reads predictions, never calls a model. Prints PASS/FAIL per criterion and writes verdict.md.
"""
from __future__ import annotations

import argparse
import math
import os

import pandas as pd

from experiments import metrics
from experiments.replay_attribution import apply_attribution
from experiments.replay_policy import replay

M7, M8, M8A = "M7_extract_compute", "M8_gated", "M8_gated_attr"
KEY = ["case_id", "source", "target"]


def _paired(pool: pd.DataFrame, a: str, b: str, metric: str, n_boot: int):
    d = metrics.paired_bootstrap(pool, "confirm", [a], [b], n_boot)
    r = d[(d["a"] == a) & (d["b"] == b) & (d["metric"] == metric)].iloc[0]
    return float(r["delta"]), float(r["ci_low"]), float(r["ci_high"])


def _same_predictions(live: pd.DataFrame, replayed: pd.DataFrame) -> tuple[bool, int]:
    a = live.set_index(KEY)["predicted_violation"].astype(bool)
    b = replayed.set_index(KEY)["predicted_violation"].astype(bool)
    j = a.to_frame("live").join(b.to_frame("replay"), how="outer")
    diff = int((j["live"] != j["replay"]).sum())
    return diff == 0, diff


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--benchmarks", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bootstrap", type=int, default=1000)
    a = ap.parse_args(argv)
    assert len(a.runs) == len(a.benchmarks), "one benchmark folder per run, in the same order"

    pooled, p5_diff, p8_diff = [], 0, 0
    for run, bench in zip(a.runs, a.benchmarks):
        tag = os.path.basename(os.path.normpath(run))
        preds = pd.read_csv(os.path.join(run, "predictions.csv"))
        rep, info = replay(bench, preds)                                            # P5: replay of M8 from the recorded M7 rows
        p5_diff += _same_predictions(preds[preds.method == M8], rep)[1] + info["replay_gaps"]
        rep_attr = apply_attribution(bench, rep, method=M8A)                          # P8: replay of the check over those rows
        p8_diff += _same_predictions(preds[preds.method == M8A], rep_attr)[1]
        preds = preds.copy()
        preds["case_id"] = tag + ":" + preds["case_id"].astype(str)
        pooled.append(preds)
    pool = pd.concat(pooled, ignore_index=True)
    pool["split"] = "confirm"

    lines, ok = [], {}

    def crit(name: str, passed: bool, text: str) -> None:
        ok[name] = passed
        lines.append(f"{'PASS' if passed else 'FAIL'}  {name}  {text}")

    def f1(m):
        return metrics.prf(metrics.confusion(pool[pool.method == m]))["f1"]

    d, lo, hi = _paired(pool, M8, M7, "f1", a.bootstrap)
    crit("P1 no regression (M8 - M7 paired F1, lower bound > -0.02)", lo > -0.02, f"delta {d:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}); F1 M7 {f1(M7):.3f}, M8 {f1(M8):.3f}, M8+attr {f1(M8A):.3f}")
    d, lo, hi = _paired(pool, M8, M7, "llm_calls", a.bootstrap)
    crit("P2 saving (M8 - M7 paired calls, upper bound < 0)", hi < 0, f"delta {d:+.1f} (95% CI {lo:+.1f} to {hi:+.1f}); calls M7 {int(pool[pool.method == M7].llm_called.sum())}, M8 {int(pool[pool.method == M8].llm_called.sum())}")
    v8 = pool[(pool.method == M8) & (pool.structural_status == "violation")]
    silent = v8[(~v8.llm_called.astype(bool)) & (v8.predicted_violation.astype(bool) != (v8.truth == "violation"))]
    crit("P3 safety (at most 2 wrong verdicts made without the model)", len(silent) <= 2, f"{len(silent)} wrong of {int((~v8.llm_called.astype(bool)).sum())} verdicts made without the model")
    cap = metrics.escalation_capture(pool)
    c = cap[cap["method"] == M8].iloc[0]
    crit("P4 capture (M8 escalates >= 95% of static false positives)", float(c["capture_rate"]) >= 0.95, f"capture {float(c['capture_rate']):.3f} ({int(c['captured_fp'])} of {int(c['static_false_positives'])})")
    crit("P5 replay = live for M8", p5_diff == 0, f"{p5_diff} predictions differ across {len(a.runs)} runs")

    t = pool[(pool.structural_status == "violation")].copy()
    t["ok"] = t.predicted_violation.astype(bool) == (t.truth == "violation")
    by = t.groupby(["scenario", "method"]).ok.sum().unstack()
    mrow = by[by.index.str.startswith("M")]
    n_m = int(t[(t.method == M8A) & t.scenario.str.startswith("M")].shape[0])
    need = math.ceil(16 / 18 * n_m)
    got = int(mrow[M8A].iloc[0]) if len(mrow) else 0
    crit(f"P6 attribution fix (scenario M correct >= {need} of {n_m})", got >= need, f"M8+attr {got} of {n_m}; M8 {int(mrow[M8].iloc[0]) if len(mrow) else 0}; M7 {int(mrow[M7].iloc[0]) if len(mrow) else 0}")
    worse = by[(by[M8] - by[M8A]) > 1]
    harm = t[(t.method == M8A) & t.get("attribution", pd.Series("", index=t.index)).fillna("").astype(str).str.startswith("rejected") & (t.truth == "justified")]
    crit("P7 no harm (no scenario loses > 1 case; no justified case rejected)", worse.empty and harm.empty, f"scenarios losing >1: {list(worse.index) or 'none'}; justified cases rejected: {len(harm)}")
    crit("P8 replay = live for the attribution check", p8_diff == 0, f"{p8_diff} predictions differ")

    text = "\n".join(lines)
    print(text)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "verdict.md"), "w", encoding="utf-8") as f:
        f.write("# M8 / M8+attribution fresh-seed verdict (criteria fixed in docs/ANALYSIS_PLAN.md before the run)\n\n```\n" + text + "\n```\n\n")
        f.write("## Correct per scenario (targeted+conformant violations)\n\n" + "```\n" + by.to_string() + "\n```\n")
    pool.to_csv(os.path.join(a.out, "pooled_predictions.csv"), index=False)
    print("\nwrote", os.path.join(a.out, "verdict.md"))
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
