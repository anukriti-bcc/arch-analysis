"""Deterministic ADR reader (M6) and escalation-quality metrics.

These tests use generic ADR phrasings written for the purpose, plus the primary-wording benchmark
fixture. They deliberately do NOT touch the held-out wording: M6 is frozen before that run."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from analysis.intent.adr import ADR, ADRMatch, parse_adr
from analysis.intent.reader import (
    decide_deterministic, decision_section, find_dates, match_strength, read_adr, sentences,
)
from experiments import metrics, pipeline


def adr(text, status="Accepted", path="docs/adr/0001-x.md"):
    return parse_adr(path, f"# 1. X\n\nDate: 2025-01-01\n\n## Status\n\n{status}\n\n{text}")


def match(a, *reasons):
    return ADRMatch(a, reasons or ("file_names",))


# ---------------------------------------------------------------- sections and dates

def test_only_the_decision_section_is_read():
    text = "## Context\n\nRule R1 normally forbids this.\n\n## Decision\n\nWe allow it.\n\n## Consequences\n\nNone."
    section, found = decision_section(text)
    assert found and "allow" in section and "forbids" not in section and "None" not in section


def test_madr_decision_outcome_heading_and_fallback_without_heading():
    assert decision_section("## Decision Outcome\n\nChosen.\n\n### Consequences\n\nX")[0] == "Chosen."
    section, found = decision_section("Just prose without headings.")
    assert not found and "prose" in section


@pytest.mark.parametrize("text,expected", [
    ("by 2025-09-13", date(2025, 9, 13)),
    ("by 13 September 2025", date(2025, 9, 13)),
    ("by 13th of Sept 2025", date(2025, 9, 13)),
    ("by September 13, 2025", date(2025, 9, 13)),
    ("by 2025/09/13", date(2025, 9, 13)),
])
def test_common_date_formats(text, expected):
    assert [f.value for f in find_dates(text)] == [expected]


def test_impossible_dates_are_ignored():
    assert find_dates("on 2025-13-45") == []


def test_sentence_splitting_ignores_backticks():
    assert sentences("We accept `a` use of `b`. It is permanent.") == ["We accept a use of b.", "It is permanent."]


# ---------------------------------------------------------------- stance and dates

def test_permission_without_condition_permits():
    r = read_adr(adr("## Decision\n\nWe accept that `a` may use `b` directly."), date(2025, 6, 1))
    assert r.stance == "permits" and r.permitted is True


def test_prohibition_wins_even_when_the_text_mentions_an_exception():
    r = read_adr(adr("## Decision\n\nWe reaffirm that `a` must not use `b`. The request for an exception was rejected."), None)
    assert r.stance == "prohibits" and r.permitted is False


def test_context_quote_of_the_overridden_rule_does_not_flip_the_stance():
    text = "## Context\n\nThe rule normally forbids this.\n\n## Decision\n\nWe allow `a` to use `b`, as a permanent exception."
    assert read_adr(adr(text), None).permitted is True


@pytest.mark.parametrize("introduced,expected", [
    (date(2025, 9, 13), True),   # on the cut-off day: "on or before" includes it
    (date(2025, 9, 1), True),
    (date(2025, 9, 14), False),
])
def test_on_or_before_clause_is_applied_in_code(introduced, expected):
    text = ("## Decision\n\nThe service may continue to use the connection. Dependencies introduced on or before "
            "13 September 2025 are grandfathered. Any introduced after 13 September 2025 is NOT covered by this decision.")
    assert read_adr(adr(text), introduced).permitted is expected


def test_before_is_exclusive_and_after_permission_is_a_lower_bound():
    before = adr("## Decision\n\nWe allow it for code introduced before 2025-09-13.")
    assert read_adr(before, date(2025, 9, 12)).permitted is True and read_adr(before, date(2025, 9, 13)).permitted is False
    after = adr("## Decision\n\nWe allow it for code introduced after 2025-09-13.")
    assert read_adr(after, date(2025, 9, 14)).permitted is True and read_adr(after, date(2025, 9, 13)).permitted is False


def test_unknown_introduction_date_is_unclear_not_guessed():
    r = read_adr(adr("## Decision\n\nWe allow it through 2025-09-13."), None)
    assert r.stance == "permits" and r.permitted is None


def test_no_cue_is_unclear():
    r = read_adr(adr("## Decision\n\nThe controller tier will cache lookups for 60 seconds."), None)
    assert r.stance == "unclear" and r.permitted is None


def test_condition_that_is_not_a_date_is_not_interpreted():
    """'Until the migration completes' has no date, so code reads it as a plain permission. This is a documented
    limit of the code-only reader, asserted so it cannot silently change."""
    assert read_adr(adr("## Decision\n\nUntil the migration completes, `a` may use `b`."), date(2025, 1, 1)).permitted is True


# ---------------------------------------------------------------- decision across ADRs

def test_weak_matches_and_inactive_records_never_justify():
    permit = adr("## Decision\n\nWe allow it.")
    assert decide_deterministic([match(permit, "component_types")], None).outcome == "violation"
    assert decide_deterministic([match(permit, "rule_id")], None).outcome == "violation"
    old = adr("## Decision\n\nWe allow it.", status="Superseded by ADR-9")
    assert decide_deterministic([match(old)], None).outcome == "violation"
    assert decide_deterministic([], None).reason == "no relevant ADR"


def test_commit_cited_adr_counts_as_strong_and_latest_decision_governs():
    assert match_strength(match(adr("x"), "commit_reference")) == "strong"
    older = ADR("ADR-001", "t", "accepted", "", date(2025, 1, 1), "a.md", "## Decision\n\nWe allow it.")
    newer = ADR("ADR-002", "t", "accepted", "", date(2025, 6, 1), "b.md", "## Decision\n\nWe reaffirm it must not be used.")
    d = decide_deterministic([match(older), match(newer)], None)
    assert d.predicted_violation and d.adr_id == "ADR-002"


def test_unclear_reading_keeps_the_structural_verdict_but_is_labelled():
    d = decide_deterministic([match(adr("## Decision\n\nCache lookups."))], None)
    assert d.predicted_violation and d.outcome == "unclear"


# ---------------------------------------------------------------- M6 in the pipeline (primary wording only)

EXPECTED_PRIMARY = {"A": True, "B": False, "C": False, "D": True, "E": True, "F": True, "G": True, "H": True, "J": False, "K": True}


@pytest.mark.parametrize("letter,violation", sorted(EXPECTED_PRIMARY.items()))
def test_m6_decides_each_primary_scenario_without_an_llm(bench_cases, letter, violation):
    rows = pipeline.run_deterministic_adr(bench_cases[letter])
    t = [r for r in rows if r["truth"] != "conformant"][0]
    assert t["predicted_violation"] is violation and not any(r["llm_called"] for r in rows)
    assert t["predicted_violation"] == (t["truth"] == "violation")  # and agrees with ground truth


# ---------------------------------------------------------------- escalation metrics

def preds(rows):
    base = {"split": "test", "structural_status": "violation", "llm_called": False}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_capture_rate_oracle_gap_and_random_reference():
    df = preds([
        {"method": "M5", "case_id": "1", "truth": "justified", "escalated": True},
        {"method": "M5", "case_id": "2", "truth": "justified", "escalated": False},
        {"method": "M5", "case_id": "3", "truth": "violation", "escalated": True},
        {"method": "M5", "case_id": "4", "truth": "violation", "escalated": False},
    ])
    r = metrics.escalation_capture(df).iloc[0]
    assert (r.static_false_positives, r.escalated, r.captured_fp) == (2, 2, 1)
    assert r.capture_rate == 0.5 and r.escalation_rate == 0.5 and r.capture_lift == 0
    assert r.escalation_yield == 0.5 and r.oracle_calls == 2 and r.calls_over_oracle == 0 and r.wasted_escalations == 1


def test_methods_without_an_escalation_decision_are_omitted_and_m4_seeds_are_averaged():
    rows = [{"method": m, "case_id": "1", "truth": "justified", "escalated": False} for m in ("M1_static", "M2_llm_only", "M6_deterministic_adr")]
    rows += [{"method": f"M4_generic_selective_s{i}", "case_id": "1", "truth": "justified", "escalated": bool(i % 2)} for i in range(4)]
    out = metrics.escalation_capture(preds(rows))
    assert list(out["method"]) == ["M4_generic_selective_mean"] and out.iloc[0].capture_rate == 0.5


def test_capture_curve_matches_random_and_oracle_references():
    fp = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0], dtype=bool)
    perfect = metrics.capture_curve(np.where(fp, 1.0, 0.0), fp)
    assert perfect["capture_rate"].iloc[2] == 1.0 and perfect["capture_auc"].iloc[0] == pytest.approx(perfect["oracle_auc"].iloc[0]) == pytest.approx(0.9)
    worst = metrics.capture_curve(np.where(fp, 0.0, 1.0), fp)
    assert worst["capture_rate"].iloc[8] < 1.0 and worst["capture_auc"].iloc[0] < 0.1
    tied = metrics.capture_curve(np.zeros(10), fp)  # no information: capture is whatever the arbitrary order gives
    assert tied["k"].iloc[-1] == 10 and tied["capture_rate"].iloc[-1] == 1.0
