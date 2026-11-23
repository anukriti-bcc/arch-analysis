"""Ingesting a human-verified review workbook: provenance is honest, overrides are applied, incomplete reviews are flagged."""
import shutil

import pandas as pd
import pytest
from openpyxl import load_workbook

from experiments.real_adrs.ingest_review import ingest, read_reviewer

REVIEW = "../results/real_adrs/review_sheet_for_human_verification.xlsx"
PASS2 = "../results/real_adrs/annotation_sheet_claude_pass2.csv"
Q1 = "Q1_about_dependencies (yes/no/partly)"


@pytest.fixture
def pass2():
    return pd.read_csv(PASS2, dtype=str, keep_default_na=False)


def filled(tmp_path, edits, done=True, name="Test Reviewer"):
    p = tmp_path / "r.xlsx"
    shutil.copy(REVIEW, p)
    wb = load_workbook(p)
    ws = wb["Review"]
    # Start from a BLANK template: the real workbook now holds the team's verification, so clear every human-entered cell
    # (YOUR_Q1/Q2/Q3, reviewed, note). The tests then do not depend on, or change, the real review data.
    for row in ws.iter_rows(min_row=2):
        if row[0].value:
            for col in "HJLNO":
                ws[f"{col}{row[0].row}"] = None
    for row in ws.iter_rows(min_row=2):
        rid = row[0].value
        if done:
            ws.cell(row=row[0].row, column=14, value="done")
        for col, val in edits.get(rid, {}).items():
            ws[f"{col}{row[0].row}"] = val
    h = wb["How to"]
    for c in h["A"]:
        if isinstance(c.value, str) and c.value.startswith("Your name for the record"):
            h.cell(row=c.row + 1, column=1, value=name)
    wb.save(p)
    return str(p)


def test_agreeing_with_everything_keeps_the_ai_labels_and_says_human_verified(tmp_path, pass2):
    df, s = ingest(filled(tmp_path, {"R006": {"H": "no"}}), pass2, "Test Reviewer")
    assert s["labels_changed_by_human"] == {"Q1": 0, "Q2": 0, "Q3": 0} and s["reviewed_done"] == 60
    assert (df["annotator"] == "AI draft (Claude), verified row by row by a human reviewer").all()
    assert df.loc[df.id == "R006", Q1].iloc[0] == "no"  # the row the AI left blank is filled by the human
    assert s["human_supplied_ids"]["Q1"] == ["R006"]  # filled in by the human, not counted as a change to an AI label
    assert s["ai_vs_final_q1"]["raw_agreement_3class"] == 1.0


def test_a_human_override_replaces_the_label_and_is_flagged(tmp_path, pass2):
    df, s = ingest(filled(tmp_path, {"R003": {"H": "no"}, "R034": {"H": "partly", "J": "yes"}, "R006": {"H": "no"}}), pass2)
    assert df.loc[df.id == "R003", Q1].iloc[0] == "no" and df.loc[df.id == "R003", "AI_draft_Q1"].iloc[0] == "partly"
    assert s["changed_ids"]["Q1"] == ["R003", "R034"] and s["changed_ids"]["Q2"] == ["R034"]
    assert df.loc[df.id == "R003", "human_changed_Q1"].iloc[0] and not df.loc[df.id == "R001", "human_changed_Q1"].iloc[0]
    assert s["ai_vs_final_q1"]["raw_agreement_3class"] < 1.0


def test_unreviewed_rows_make_the_provenance_say_incomplete(tmp_path, pass2):
    df, s = ingest(filled(tmp_path, {}, done=False), pass2)
    assert len(s["not_marked_done"]) == 60 and "INCOMPLETE" in df["annotator"].iloc[0] and not df["human_reviewed"].any()


def test_an_invalid_cell_is_reported_and_ignored(tmp_path, pass2):
    df, s = ingest(filled(tmp_path, {"R001": {"H": "maybe"}, "R006": {"H": "no"}}), pass2)
    assert s["invalid_cells"] and df.loc[df.id == "R001", Q1].iloc[0] == "no"


def test_the_reviewer_name_is_read_from_the_workbook(tmp_path):
    assert read_reviewer(filled(tmp_path, {}, name="A. Student")) == "A. Student"


def test_prevalence_uses_the_final_labels(tmp_path, pass2):
    df, s = ingest(filled(tmp_path, {"R001": {"H": "yes"}, "R006": {"H": "no"}}), pass2)
    assert s["prevalence_yes"]["k"] == 4 and s["prevalence_yes"]["n"] == 60
