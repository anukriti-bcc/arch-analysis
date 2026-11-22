"""Score a completed blind human check against the AI-drafted labels (agreement, not prevalence).

  python -m experiments.real_adrs.ingest_blind_check --sheet <completed xlsx> --key ../results/real_adrs/blind_check_key.csv \
      --pass2 ../results/real_adrs/annotation_sheet_claude_pass2.csv --out ../results/real_adrs
"""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd
from openpyxl import load_workbook
from sklearn.metrics import cohen_kappa_score

from experiments.real_adrs.make_blind_check import Q1

Q2 = "Q2_exception_or_condition (yes/no)"


def _declarations(path: str) -> tuple[str, str]:
    ws = load_workbook(path)["How to"]
    return str(ws["A15"].value or "").strip(), str(ws["A17"].value or "").strip().lower()


def score(sheet: str, key: pd.DataFrame, pass2: pd.DataFrame) -> dict:
    chk = pd.read_excel(sheet, sheet_name="Check", dtype=str).fillna("")
    name, ai_used = _declarations(sheet)
    d = chk.merge(key, on="code").merge(pass2[["id", Q1, Q2]], on="id")
    d["h1"], d["h2"] = d["Q1"].str.strip().str.lower(), d["Q2"].str.strip().str.lower()
    done = d[(d.h1 != "") & (d.h2 != "")]
    kappa = lambda a, b: float(cohen_kappa_score(a, b)) if pd.concat([a, b]).nunique() > 1 else None
    dep = lambda s: s.map(lambda x: "dep" if x in ("yes", "partly") else "no")
    dis1 = done[done[Q1] != done.h1]
    dis2 = done[done[Q2] != done.h2]
    complete = len(done) == len(key) and bool(name) and ai_used in ("yes", "no")
    return {
        "reviewer": name, "declared_ai_assistance": ai_used, "rows": len(key), "rows_labelled": len(done), "complete": complete,
        "q1": {"raw_agreement": float((done[Q1] == done.h1).mean()), "kappa": kappa(done[Q1], done.h1),
               "raw_agreement_binary": float((dep(done[Q1]) == dep(done.h1)).mean()), "kappa_binary": kappa(dep(done[Q1]), dep(done.h1)),
               "disagreements": [{"id": r["id"], "ai": r[Q1], "human": r["h1"]} for _, r in dis1.iterrows()]},
        "q2": {"raw_agreement": float((done[Q2] == done.h2).mean()), "kappa": kappa(done[Q2], done.h2),
               "disagreements": [{"id": r["id"], "ai": r[Q2], "human": r["h2"]} for _, r in dis2.iterrows()]},
        "note": "Sample oversamples AI-labelled yes/partly rows, so this measures agreement, not prevalence.",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--sheet", "--key", "--pass2", "--out"):
        ap.add_argument(k, required=True)
    a = ap.parse_args(argv)
    r = score(a.sheet, pd.read_csv(a.key, dtype=str), pd.read_csv(a.pass2, dtype=str, keep_default_na=False))
    with open(os.path.join(a.out, "blind_check_result.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1)
    print(json.dumps(r, indent=1))
    if not r["complete"]:
        print("\nWARNING: not every row is labelled, or the name / AI-use declaration is missing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
