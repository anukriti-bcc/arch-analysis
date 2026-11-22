"""Build a small BLIND human check of the AI-drafted real-ADR labels.

Why: two review sheets came back with identical changes (the second was the first plus one row), so independent human verification is not established.
A blind check fixes that cheaply: 20 excerpts, shown in shuffled order with NO AI labels, labelled from scratch by a person.

  python -m experiments.real_adrs.make_blind_check --pass2 ../results/real_adrs/annotation_sheet_claude_pass2.csv --out ../results/real_adrs

Sample: every row the AI labelled yes or partly on Q1 (so there are positives to agree on) plus 9 randomly drawn "no" rows (fixed seed). The code to id key is
written to a separate CSV that is NOT given to the reviewer. Because positives are oversampled, this estimates AGREEMENT, not prevalence.
"""
from __future__ import annotations

import argparse
import os
import random

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

Q1 = "Q1_about_dependencies (yes/no/partly)"
SEED, N_NO = 2026, 9


def sample(pass2: pd.DataFrame) -> pd.DataFrame:
    pos = pass2[pass2[Q1].isin(["yes", "partly"])]
    neg = pass2[(pass2[Q1] == "no")]
    neg = neg.sample(n=N_NO, random_state=SEED)
    s = pd.concat([pos, neg]).sample(frac=1, random_state=SEED).reset_index(drop=True)
    s.insert(0, "code", [f"B{i + 1:02d}" for i in range(len(s))])
    return s


def build(s: pd.DataFrame, path: str) -> None:
    F = "Arial"
    wb = Workbook()
    h = wb.active
    h.title = "How to"
    lines = [
        ("Blind check of AI-drafted labels (about 15 minutes)", True),
        ("", False),
        ("You will label 20 ADR excerpts yourself, from scratch. You are NOT shown any AI label. This only works if the labels are your own judgement.", False),
        ("Please do not use an AI assistant, and do not look at any earlier review sheet or label file, for this check.", True),
        ("", False),
        ("Q1  Does the decision restrict or permit which parts of the system (modules, layers, services, packages) may depend on, call or import each other?", False),
        ("      yes = explicitly;   partly = defines structure or responsibilities but states no explicit restriction;   no = not about that.", False),
        ("      A choice of library, tool, language, API shape or deployment is normally 'no'.", False),
        ("Q2  Does it grant an exception or a condition (a date, 'temporary', 'for now', 'currently', 'postponed', 'except when ...')?   yes / no", False),
        ("", False),
        ("Steps: read the excerpt (column D), open the URL (column E) only if you need more context, choose Q1 and Q2 from the dropdowns, add a note if unsure.", False),
        ("Fill every row. Then fill in the two yellow cells below and send the file back.", False),
        ("", False),
        ("Your name:", True),
        ("", False),
        ("Did you use an AI assistant for ANY row of this check?  (yes / no)", True),
        ("", False),
    ]
    for i, (t, b) in enumerate(lines, 1):
        c = h.cell(row=i, column=1, value=t)
        c.font = Font(name=F, bold=b, size=12 if i == 1 else 10)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in (15, 17):
        h.cell(row=r, column=1).fill = PatternFill("solid", fgColor="FFFF00")
    dv = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
    h.add_data_validation(dv)
    dv.add("A17")
    h.column_dimensions["A"].width = 150

    ws = wb.create_sheet("Check")
    cols = ["code", "repo", "status", "decision_excerpt", "url", "Q1", "Q2", "note"]
    ws.append(cols)
    for _, r in s.iterrows():
        ws.append([r["code"], r["repo"], r["status"], r["decision_excerpt"], r["url"], None, None, None])
    thin = Side(style="thin", color="BBBBBB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for i, w in enumerate([7, 26, 11, 100, 28, 12, 10, 40], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for c in ws[1]:
        c.font = Font(name=F, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.border = border
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.font = Font(name=F, size=10)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = border
            if c.column_letter in "FGH":
                c.fill = PatternFill("solid", fgColor="FFFF00")
        ws.row_dimensions[row[0].row].height = 120
    ws.freeze_panes = "E2"
    n = ws.max_row
    for col, opts in (("F", '"yes,partly,no"'), ("G", '"yes,no"')):
        d = DataValidation(type="list", formula1=opts, allow_blank=True, showErrorMessage=True)
        ws.add_data_validation(d)
        d.add(f"{col}2:{col}{n}")
    wb.move_sheet("Check", offset=0)
    wb.active = 1
    wb.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pass2", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    s = sample(pd.read_csv(a.pass2, dtype=str, keep_default_na=False))
    build(s, os.path.join(a.out, "blind_check_for_human.xlsx"))
    s[["code", "id"]].to_csv(os.path.join(a.out, "blind_check_key.csv"), index=False)
    print(f"{len(s)} rows; key written separately (do not send it to the reviewer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
