"""Replay the stance-attribution check over recorded extraction-based rows (M7/M8): exact result, no model needed.

  python -m experiments.replay_attribution --benchmark /tmp/bench_hard_21 --rows ../results/m8_replay/dev_s21_m8.csv --out out.csv
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

import pandas as pd

from analysis.intent.reader import introduction_date
from analysis.semantic.attribution import check_attribution
from analysis.semantic.extract import resolve_extraction
from experiments import pipeline
from models.finding import FindingStatus


def apply_attribution(benchmark_root: str, rows: pd.DataFrame, *, method: str) -> pd.DataFrame:
    rows = rows.copy()
    with open(os.path.join(benchmark_root, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    by_case = {e["case_id"]: e for e in manifest["cases"]}
    rows["method"] = method
    rows["attribution"] = ""
    for case_id, g in rows[rows["extraction"].notna() & (rows["outcome_source"].isin(["llm_extract", "fallback"]))].groupby("case_id"):
        ctx = pipeline.CaseContext(benchmark_root, by_case[case_id])
        for i, r in g.iterrows():
            x = json.loads(r["extraction"])
            if x.get("decision") != "permits":
                continue
            f = next(f for f in ctx.violations if ctx.edge(f) == (r["source"], r["target"]))
            b = ctx.bundle(f)
            x["limit_date"] = date.fromisoformat(x["limit_date"]) if x.get("limit_date") else None
            y = check_attribution(x, b.adrs, b.source_path, b.target_path)
            rows.at[i, "attribution"] = y["attribution"]
            if y["decision"] != x["decision"]:
                res = resolve_extraction(y, introduction_date(b.evolution))
                rows.at[i, "predicted_violation"] = res.predicted_violation
                rows.at[i, "computed"] = res.note
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--method", default="M8_gated_attr")
    a = ap.parse_args(argv)
    apply_attribution(a.benchmark, pd.read_csv(a.rows), method=a.method).to_csv(a.out, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
