"""Compare two raters' labels on the real-ADR annotation sample (the team's filled sheet vs another set of labels).

    python -m experiments.real_adrs.agreement --sheet ../results/real_adrs/annotation_sheet.csv \\
        --other ../results/real_adrs/indicative_labels_claude.csv --out ../results/real_adrs/agreement.json

Reports raw agreement and Cohen's kappa on Q1 (3 classes and yes-or-partly vs no), the disagreements to discuss, and the prevalence of
dependency-governing ADRs from the sheet's own labels with a Wilson 95% interval.
"""
from __future__ import annotations

import argparse
import json
from math import sqrt

import pandas as pd
from sklearn.metrics import cohen_kappa_score

Q1 = "Q1_about_dependencies (yes/no/partly)"
VALID = {"yes", "no", "partly"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / d, (centre + half) / d


def normalise(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().replace({"nan": "", "y": "yes", "n": "no", "p": "partly"})


def compare(sheet: pd.DataFrame, other: pd.DataFrame) -> dict:
    a = sheet[["id", Q1]].assign(a=lambda d: normalise(d[Q1]))[["id", "a"]]
    b = other[["id", "Q1_about_dependencies"]].assign(b=lambda d: normalise(d["Q1_about_dependencies"]))[["id", "b"]]
    m = a.merge(b, on="id")
    unlabelled = m[~m.a.isin(VALID)].id.tolist()
    m = m[m.a.isin(VALID) & m.b.isin(VALID)]
    binar = lambda s: s.map(lambda x: "dep" if x in ("yes", "partly") else "no")
    out = {"compared": len(m), "unlabelled_in_sheet": unlabelled,
           "raw_agreement_3class": float((m.a == m.b).mean()) if len(m) else None,
           "kappa_3class": float(cohen_kappa_score(m.a, m.b)) if len(m) and m.a.nunique() + m.b.nunique() > 2 else None,
           "raw_agreement_binary": float((binar(m.a) == binar(m.b)).mean()) if len(m) else None,
           "kappa_binary": float(cohen_kappa_score(binar(m.a), binar(m.b))) if len(m) and binar(m.a).nunique() + binar(m.b).nunique() > 2 else None,
           "disagreements": m[m.a != m.b][["id", "a", "b"]].rename(columns={"a": "sheet", "b": "other"}).to_dict("records")}
    lab = a[a.a.isin(VALID)]
    for name, ks in (("yes", ["yes"]), ("yes_or_partly", ["yes", "partly"])):
        k = int(lab.a.isin(ks).sum())
        lo, hi = wilson(k, len(lab))
        out[f"prevalence_{name}"] = {"k": k, "n": len(lab), "share": k / len(lab) if len(lab) else None, "wilson95": [lo, hi]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--other", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    res = compare(pd.read_csv(args.sheet), pd.read_csv(args.other))
    text = json.dumps(res, indent=1)
    print(text)
    if args.out:
        open(args.out, "w").write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
