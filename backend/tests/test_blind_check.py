"""The blind human check: sampling is balanced and reproducible, the key stays out of the sheet, and scoring reports agreement honestly."""
import shutil

import pandas as pd
from openpyxl import load_workbook

from experiments.real_adrs.ingest_blind_check import Q2, score
from experiments.real_adrs.make_blind_check import Q1, build, sample

PASS2 = "../results/real_adrs/annotation_sheet_claude_pass2.csv"


def setup(tmp_path):
    p2 = pd.read_csv(PASS2, dtype=str, keep_default_na=False)
    s = sample(p2)
    path = str(tmp_path / "b.xlsx")
    build(s, path)
    return p2, s, path


def fill(path, s, p2, flips=(), name="A. Person", ai="no"):
    wb = load_workbook(path)
    ws = wb["Check"]
    lab = p2.set_index("id")
    for i, row in enumerate(ws.iter_rows(min_row=2), start=0):
        rid = s.loc[i, "id"]
        q1, q2 = lab.loc[rid, Q1], lab.loc[rid, Q2]
        if rid in flips:
            q1 = "no" if q1 != "no" else "yes"
        ws[f"F{row[0].row}"], ws[f"G{row[0].row}"] = q1, q2
    wb["How to"]["A15"], wb["How to"]["A17"] = name, ai
    wb.save(path)


def test_sample_has_every_positive_and_nine_negatives_and_is_reproducible():
    p2 = pd.read_csv(PASS2, dtype=str, keep_default_na=False)
    s1, s2 = sample(p2), sample(p2)
    assert list(s1["id"]) == list(s2["id"]) and len(s1) == 20
    assert (s1[Q1] == "no").sum() == 9 and s1[Q1].isin(["yes", "partly"]).sum() == 11
    assert list(s1["code"]) == [f"B{i:02d}" for i in range(1, 21)]


def test_the_sheet_shows_no_ai_labels_and_no_ids(tmp_path):
    _, s, path = setup(tmp_path)
    ws = load_workbook(path)["Check"]
    header = [c.value for c in ws[1]]
    assert header == ["code", "repo", "status", "decision_excerpt", "url", "Q1", "Q2", "note"]
    text = " ".join(str(c.value) for row in ws.iter_rows(min_row=2, max_col=3) for c in row)
    assert not any(i in text for i in s["id"])  # R0xx ids (and so the key) are not in the sheet


def test_full_agreement_and_declarations(tmp_path):
    p2, s, path = setup(tmp_path)
    fill(path, s, p2)
    r = score(path, s[["code", "id"]], p2)
    assert r["complete"] and r["reviewer"] == "A. Person" and r["declared_ai_assistance"] == "no"
    assert r["q1"]["raw_agreement"] == 1.0 and r["q1"]["disagreements"] == []


def test_disagreements_are_listed_and_lower_agreement(tmp_path):
    p2, s, path = setup(tmp_path)
    flip = set(s["id"].iloc[:3])
    fill(path, s, p2, flips=flip)
    r = score(path, s[["code", "id"]], p2)
    assert {d["id"] for d in r["q1"]["disagreements"]} == flip and abs(r["q1"]["raw_agreement"] - 17 / 20) < 1e-9


def test_a_missing_name_or_ai_declaration_makes_it_incomplete(tmp_path):
    p2, s, path = setup(tmp_path)
    fill(path, s, p2, name="", ai="")
    assert not score(path, s[["code", "id"]], p2)["complete"]
