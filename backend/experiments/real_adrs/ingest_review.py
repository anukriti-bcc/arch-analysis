"""Turn a human-verified review workbook into the final labels for the real-ADR sample, with honest provenance.

  python -m experiments.real_adrs.ingest_review --review ../results/real_adrs/review_sheet_for_human_verification.xlsx \
      --pass2 ../results/real_adrs/annotation_sheet_claude_pass2.csv --out ../results/real_adrs

Rule: a row's final label is the reviewer's when the YOUR_* cell is filled, otherwise the AI draft stands because the reviewer looked and
agreed (rows must be marked `done`). Writes `annotation_sheet_verified.csv` (same columns as the original sheet, plus who labelled what and which
labels the human changed) and `verification_summary.json`: rows reviewed, how many labels were changed, AI-vs-human agreement, and prevalence
with Wilson intervals. The annotator field says "AI draft, human-verified"; it never claims the labels were produced by a human alone.
"""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd
from openpyxl import load_workbook
from sklearn.metrics import cohen_kappa_score

from experiments.real_adrs.agreement import Q1, VALID, wilson

Q2 = "Q2_exception_or_condition (yes/no)"
Q3 = "Q3_wording (templated / plain paraphrase / irregular)"
ALLOWED = {"Q1": VALID, "Q2": {"yes", "no"}, "Q3": {"templated", "plain paraphrase", "irregular"}}
NAME_MARKER = "Your name for the record"


def _clean(v) -> str:
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip().lower()


def read_reviewer(path: str) -> str:
    ws = load_workbook(path)["How to"]
    rows = [c.value for c in ws["A"]]
    for i, v in enumerate(rows):
        if isinstance(v, str) and v.startswith(NAME_MARKER) and i + 1 < len(rows):
            return str(rows[i + 1]).strip() if rows[i + 1] else ""
    return ""


def ingest(review_path: str, pass2: pd.DataFrame, reviewer: str = "") -> tuple[pd.DataFrame, dict]:
    rev = pd.read_excel(review_path, sheet_name="Review", dtype=str).fillna("")
    problems: list[str] = []
    out = pass2.copy()
    by_id = rev.set_index("id")
    missing = sorted(set(out["id"]) - set(by_id.index))
    if missing:
        raise ValueError(f"review sheet lacks rows: {missing}")
    changed = {"Q1": [], "Q2": [], "Q3": []}
    supplied = {"Q1": [], "Q2": [], "Q3": []}  # the AI left it blank (no decision text), the human filled it in
    not_done = [i for i in out["id"] if _clean(by_id.at[i, "reviewed"]) != "done"]
    for q, col in (("Q1", Q1), ("Q2", Q2), ("Q3", Q3)):
        ai, final, flag = [], [], []
        for i in out["id"]:
            mine = _clean(out.loc[out["id"] == i, col].iloc[0])
            yours = _clean(by_id.at[i, f"YOUR_{q}"])
            if yours and yours not in ALLOWED[q]:
                problems.append(f"{i} YOUR_{q} = {yours!r} is not one of {sorted(ALLOWED[q])}")
                yours = ""
            ai.append(mine)
            use = yours or mine
            final.append(use)
            differs = bool(yours) and bool(mine) and yours != mine
            flag.append(differs)
            if differs:
                changed[q].append(i)
            elif yours and not mine:
                supplied[q].append(i)
        out[f"AI_draft_{q}"] = ai
        out[col] = final
        out[f"human_changed_{q}"] = flag
    out["annotator"] = "AI draft (Claude), verified row by row by a human reviewer" if not not_done else "AI draft (Claude); human verification INCOMPLETE"
    out["verified_by"] = reviewer or "(name not given)"
    out["human_reviewed"] = [i not in not_done for i in out["id"]]
    a, f = out["AI_draft_Q1"], out[Q1]
    ok = a.isin(VALID) & f.isin(VALID)
    binar = lambda s: s.map(lambda x: "dep" if x in ("yes", "partly") else "no")
    lab = f[f.isin(VALID)]
    n = len(lab)
    k_yes, k_dep = int((lab == "yes").sum()), int(lab.isin(["yes", "partly"]).sum())
    kappa = lambda x, y: float(cohen_kappa_score(x, y)) if len(x) and pd.concat([x, y]).nunique() > 1 else None
    summary = {
        "rows": len(out), "reviewed_done": len(out) - len(not_done), "not_marked_done": not_done, "invalid_cells": problems,
        "reviewer": reviewer, "labels_changed_by_human": {q: len(v) for q, v in changed.items()}, "changed_ids": changed, "human_supplied_ids": supplied,
        "ai_vs_final_q1": {"compared": int(ok.sum()), "raw_agreement_3class": float((a[ok] == f[ok]).mean()) if ok.any() else None,
                          "kappa_3class": kappa(a[ok], f[ok]), "raw_agreement_binary": float((binar(a[ok]) == binar(f[ok])).mean()) if ok.any() else None,
                          "kappa_binary": kappa(binar(a[ok]), binar(f[ok]))},
        "labelled_q1": n, "unlabelled_q1": out.loc[~f.isin(VALID), "id"].tolist(),
        "prevalence_yes": {"k": k_yes, "n": n, "share": k_yes / n if n else None, "wilson95": list(wilson(k_yes, n))},
        "prevalence_yes_or_partly": {"k": k_dep, "n": n, "share": k_dep / n if n else None, "wilson95": list(wilson(k_dep, n))},
    }
    return out, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review", required=True)
    ap.add_argument("--pass2", required=True, help="the AI-drafted sheet the review was built from")
    ap.add_argument("--out", required=True)
    ap.add_argument("--reviewer", default=None, help="overrides the name written in the workbook's 'How to' sheet")
    a = ap.parse_args(argv)
    reviewer = a.reviewer if a.reviewer is not None else read_reviewer(a.review)
    df, summary = ingest(a.review, pd.read_csv(a.pass2, dtype=str, keep_default_na=False), reviewer)
    os.makedirs(a.out, exist_ok=True)
    df.to_csv(os.path.join(a.out, "annotation_sheet_verified.csv"), index=False)
    with open(os.path.join(a.out, "verification_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("changed_ids",)}, indent=1))
    if summary["not_marked_done"] or summary["invalid_cells"]:
        print("\nWARNING: not every row is marked done, or a cell is invalid; the verification is incomplete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
