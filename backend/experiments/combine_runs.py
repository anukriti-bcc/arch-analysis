"""Pool several runs of the SAME methods on DIFFERENT benchmark seeds into one analysis.

Why: one benchmark seed is 34 test cases, which is too few for tight intervals. The generator is deterministic and
cheap, so a confirmation set is several fresh seeds, run once with the frozen method, then pooled here. Every case
keeps its identity (`<run>:<case_id>`), all pooled cases form one split called `confirm`, and the same paired
bootstrap used everywhere else gives the intervals.

    python -m experiments.combine_runs --runs ../results/confirm_s11 ../results/confirm_s12 ../results/confirm_s13 \\
        --out ../results/confirm_all
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

from experiments import metrics
from experiments.run_experiments import build_paired_comparisons, fmt_table

SPLIT = "confirm"


def load_runs(run_dirs: list[str]) -> tuple[pd.DataFrame, list[dict]]:
    frames, configs = [], []
    for d in run_dirs:
        tag = os.path.basename(os.path.normpath(d))
        df = pd.read_csv(os.path.join(d, "predictions.csv"))
        df["case_id"] = tag + ":" + df["case_id"].astype(str)
        df["run"] = tag
        frames.append(df)
        cfg_path = os.path.join(d, "run_config.json")
        configs.append({"run": tag, **(json.load(open(cfg_path)) if os.path.exists(cfg_path) else {})})
    return pd.concat(frames, ignore_index=True), configs


def consistency_problems(frames_methods: dict[str, set], configs: list[dict]) -> list[str]:
    problems = []
    sets = {tuple(sorted(m)) for m in frames_methods.values()}
    if len(sets) > 1:
        problems.append("runs do not contain the same methods: " + "; ".join(f"{k}: {sorted(v)}" for k, v in frames_methods.items()))
    for key in ("model", "prompt_version", "prompt_variant", "benchmark_wording"):
        vals = {str(c.get(key)) for c in configs}
        if len(vals) > 1:
            problems.append(f"runs differ in {key}: {sorted(vals)}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True, help="result folders, each containing predictions.csv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--allow-mismatch", action="store_true", help="pool even if runs differ in model/prompt/methods")
    args = ap.parse_args(argv)

    preds, configs = load_runs(args.runs)
    problems = consistency_problems({r: set(g["method"]) for r, g in preds.groupby("run")}, configs)
    if problems and not args.allow_mismatch:
        sys.exit("Refusing to pool runs that are not comparable:\n  - " + "\n  - ".join(problems) + "\n(use --allow-mismatch to override)")
    preds["split"] = SPLIT
    os.makedirs(args.out, exist_ok=True)
    preds.to_csv(os.path.join(args.out, "predictions.csv"), index=False)

    summary = metrics.summarize(preds, n_boot=args.bootstrap)
    m4 = metrics.average_over_seeds(summary, "M4_generic_selective_s", "M4_generic_selective_mean")
    headline = pd.concat([summary[~summary["method"].str.startswith("M4_generic_selective_s")], m4], ignore_index=True)
    headline.to_csv(os.path.join(args.out, "metrics.csv"), index=False)
    scen = metrics.by_scenario(preds[~preds["method"].str.contains("M4_generic_selective_s", regex=False)])
    scen.to_csv(os.path.join(args.out, "metrics_by_scenario.csv"), index=False)
    paired = build_paired_comparisons(preds, [SPLIT], args.bootstrap)
    paired.to_csv(os.path.join(args.out, "paired_comparisons.csv"), index=False)
    capture = metrics.escalation_capture(preds)
    capture.to_csv(os.path.join(args.out, "escalation_capture.csv"), index=False)

    n_cases = preds["case_id"].nunique()
    cols = ["method", "split", "precision", "recall", "f1", "f1_ci_low", "f1_ci_high", "false_positive_rate", "llm_calls"]
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# Pooled confirmation run\n\nRuns: {', '.join(os.path.basename(os.path.normpath(r)) for r in args.runs)} "
                f"({n_cases} cases pooled into split `{SPLIT}`).\n\n")
        if any(c.get("provider") in ("mock", "dry-run") for c in configs):
            f.write("> **SMOKE TEST WITH A STAND-IN, NOT A LANGUAGE MODEL.** These numbers only show that the pipeline runs. "
                    "They are not results and must not be reported.\n\n")
        if problems:
            f.write("> **Warning: runs were pooled despite differences:** " + "; ".join(problems) + "\n\n")
        f.write(fmt_table(headline, cols) + "\n\n")
        if not paired.empty:
            keep = paired[paired["metric"].isin(["f1", "false_positive_rate", "llm_calls"])]
            f.write("## Paired comparison: a minus b (95% case-level bootstrap)\n\n")
            f.write(fmt_table(keep, ["a", "b", "metric", "a_value", "b_value", "delta", "ci_low", "ci_high"]) + "\n\n")
        if not capture.empty:
            f.write("## Escalation quality\n\n" + fmt_table(capture, ["method", "static_false_positives", "escalated", "captured_fp", "capture_rate",
                    "random_expected_capture", "capture_lift", "escalation_yield", "calls_over_oracle"]) + "\n\n")
        f.write("## Decision accuracy on the targeted dependency, by scenario\n\n")
        f.write(fmt_table(scen.pivot(index="scenario", columns="method", values="accuracy").reset_index(), ["scenario", *scen["method"].unique()]) + "\n")
    print(f"Pooled {n_cases} cases from {len(args.runs)} runs -> {os.path.abspath(args.out)}")
    print(fmt_table(headline, cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
