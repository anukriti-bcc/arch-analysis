"""Readability gates, the gated escalation policy (v2) and method M8.

The gates must (1) let clean, regular decisions through so code can decide them, (2) stop every known way a
cue-based reading goes wrong, and (3) fail SAFE. M8 must never escalate something M7 would not, and the offline
replay must agree with a live run row for row."""
import json
import os
from datetime import date

import pandas as pd
import pytest

from analysis.evidence.aggregator import EvidenceBundle
from analysis.intent.adr import ADR, ADRMatch
from analysis.intent.readability import assess, governing_adr, mentions, named_subjects, scope_of
from analysis.policy.gated import DIRECT_CODE, DIRECT_STRUCTURAL, ESCALATE, GatedDecision, ReadabilityGatedPolicy, apply_budget
from analysis.semantic.llm_client import FunctionClient
from experiments import pipeline, pipeline_m8
from experiments.mock_llm import mock_model
from experiments.replay_policy import replay

SRC, TGT = "app/services/order_service.py", "app/database/connection.py"


def adr(decision: str, *, status="accepted", id="ADR-001", on="2025-01-01", context="") -> ADR:
    text = f"# 1. T\n\nDate: {on}\n\n## Status\n\n{status.capitalize()}\n\n## Context\n\n{context}\n\n## Decision\n\n{decision}\n"
    return ADR(id, "T", status, status, date.fromisoformat(on), f"docs/adr/{id}.md", text)


def read(decision, introduced=date(2025, 6, 1), **kw):
    return assess(adr(decision, **kw), introduced=introduced, source_path=SRC, target_path=TGT)


CLEAN_PERMIT = "We accept that `order_service` will use `connection` directly. The exception is permanent."
CLEAN_PROHIBIT = "We reaffirm that `order_service` must not use `connection` directly."


# ---------------------------------------------------------------- gates: pass on regular text
def test_clean_permission_passes_every_gate_and_is_a_justified_verdict():
    r = read(CLEAN_PERMIT)
    assert r.decisive and r.failed == [] and r.verdict_violation is False


def test_clean_prohibition_passes_and_is_a_violation_verdict():
    r = read(CLEAN_PROHIBIT)
    assert r.decisive and r.verdict_violation is True


def test_a_cutoff_clause_that_the_reader_understands_passes_and_is_applied():
    d = ("`order_service` may keep using `connection` directly. Dependencies introduced on or before 2025-09-13 are "
         "grandfathered. Any dependency introduced after 2025-09-13 is NOT covered by this decision.")
    early, late = read(d, introduced=date(2025, 6, 1)), read(d, introduced=date(2025, 10, 1))
    assert early.decisive and early.verdict_violation is False  # 'NOT covered' is a cut-off, not a negated permission
    assert late.decisive and late.verdict_violation is True


def test_the_word_exception_is_not_a_hedge():
    assert "G_conditions" not in read(CLEAN_PERMIT).failed


# ---------------------------------------------------------------- gates: each failure mode fails safe
@pytest.mark.parametrize("gate,decision", [
    ("G_polarity", "We rejected routing through the proper layer. `order_service` will read from `connection` directly, an acceptable cost."),
    ("G_negation", "The proposal to allow `order_service` to use `connection` directly was not approved. Access stays behind the layer."),
    ("G_anchor", "`order_service` reads `connection` results only through a cache wrapper. Serving them 60 seconds stale is acceptable."),
    ("G_temporal", "`order_service` may use `connection` directly. The tolerance covers code merged up to the freeze on October 11, 2025."),
    ("G_temporal", "`order_service` may use `connection` directly while the migration is under way."),
    ("G_conditions", "`order_service` may use `connection` directly unless the storage approach changes."),
    ("G_subject", "`review_service` may use `connection` directly. `order_service` must keep going through the proper layer."),
    ("G_clear", "The team discussed `order_service` and `connection` at length."),
])
def test_each_failure_mode_is_caught(gate, decision):
    r = read(decision)
    assert gate in r.failed and not r.decisive and r.verdict_violation is None, r.notes


def test_missing_decision_section_fails_the_section_gate():
    a = ADR("ADR-002", "T", "accepted", "accepted", None, "x.md", "We accept that order_service may use connection directly.")
    r = assess(a, introduced=None, source_path=SRC, target_path=TGT)
    assert "G_section" in r.failed


def test_a_competing_strongly_scoped_adr_fails_the_single_gate():
    r = assess(adr(CLEAN_PERMIT), introduced=date(2025, 6, 1), source_path=SRC, target_path=TGT, other_strong_active=1)
    assert "G_single" in r.failed


# ---------------------------------------------------------------- scope
def test_mentions_accepts_names_and_descriptions_and_plurals():
    assert mentions("`order_service` was changed", SRC)
    assert mentions("the order service reads data", SRC)
    assert mentions("all order services are covered", SRC)
    assert not mentions("the invoice service reads data", SRC)
    assert mentions("the database connection module", TGT)


def match(a, reasons):
    return ADRMatch(a, tuple(reasons))


def test_scope_of_strong_described_weak():
    a_desc = adr("The team accepts that the order service reads from the database connection module directly.")
    a_other = adr("The shipment service may read from the database connection module directly.")
    assert scope_of(match(a_desc, ["component_types"]), SRC, TGT) == "described"
    assert scope_of(match(a_other, ["component_types"]), SRC, TGT) == "weak"
    assert scope_of(match(a_other, ["file_names"]), SRC, TGT) == "strong"
    assert scope_of(match(a_other, ["commit_reference"]), SRC, TGT) == "strong"


def test_named_subjects_reduces_dotted_names():
    assert named_subjects("`app.services.order_service` and `connection`") == {"order_service", "connection"}


def test_governing_adr_is_the_latest_relevant_active_one_and_counts_competitors():
    old, new = adr(CLEAN_PERMIT, id="ADR-001", on="2024-01-01"), adr(CLEAN_PERMIT, id="ADR-002", on="2025-01-01")
    inactive = adr(CLEAN_PERMIT, id="ADR-003", on="2026-01-01", status="superseded")
    gov, others = governing_adr([match(old, ["file_names"]), match(new, ["file_names"]), match(inactive, ["file_names"])], SRC, TGT)
    assert gov.adr.id == "ADR-002" and others == 1
    assert governing_adr([match(inactive, ["file_names"])], SRC, TGT) == (None, 0)


# ---------------------------------------------------------------- policy routing
def bundle(matches, evolution=None):
    return EvidenceBundle("k", "F-1", "R1", "r", "forbidden", "", SRC, TGT, "service", "database", 1, "x", "", None, matches, evolution)


def test_no_adr_and_quiet_history_is_a_structural_verdict():
    d = ReadabilityGatedPolicy().decide(bundle([]))
    assert d.route == DIRECT_STRUCTURAL and d.predicted_violation is True and not d.escalate


def test_all_inactive_adrs_are_a_structural_verdict_even_with_temporary_history():
    ev = {"available": True, "introducing_commit": "x", "message_signals": {"temporary_language": ["temp"]}}
    d = ReadabilityGatedPolicy().decide(bundle([match(adr(CLEAN_PERMIT, status="superseded"), ["file_names"])], ev))
    assert d.route == DIRECT_STRUCTURAL and "I2" in d.reasons[0]


def test_a_weakly_scoped_adr_alone_does_not_trigger_a_call():
    other = adr("The shipment service may read from the database connection module directly.")
    d = ReadabilityGatedPolicy().decide(bundle([match(other, ["component_types"])]))
    assert d.route == DIRECT_STRUCTURAL and d.reasons[0].startswith("W1")
    assert ReadabilityGatedPolicy(weak_irrelevant=False, use_gates=False).decide(bundle([match(other, ["component_types"])])).escalate


def test_temporary_history_escalates_even_without_a_relevant_adr():
    ev = {"available": True, "introducing_commit": "x", "message_signals": {"temporary_language": ["temp"]}}
    d = ReadabilityGatedPolicy().decide(bundle([], ev))
    assert d.escalate and d.reasons[0].startswith("H1")
    assert not ReadabilityGatedPolicy(use_history=False).decide(bundle([], ev)).escalate


def test_a_readable_adr_is_decided_by_code_with_no_call():
    d = ReadabilityGatedPolicy().decide(bundle([match(adr(CLEAN_PERMIT), ["file_names"])]))
    assert d.route == DIRECT_CODE and d.predicted_violation is False and not d.escalate and d.adr_id == "ADR-001"
    d2 = ReadabilityGatedPolicy().decide(bundle([match(adr(CLEAN_PROHIBIT), ["file_names"])]))
    assert d2.route == DIRECT_CODE and d2.predicted_violation is True


def test_an_unreadable_adr_escalates_and_names_the_failed_gates():
    bad = adr("`order_service` may use `connection` directly unless the storage approach changes.")
    d = ReadabilityGatedPolicy().decide(bundle([match(bad, ["file_names"])]))
    assert d.escalate and d.predicted_violation is None and "G_conditions" in d.failed_gates and d.risk > 0


def test_without_gates_every_relevant_adr_escalates():
    d = ReadabilityGatedPolicy(use_gates=False).decide(bundle([match(adr(CLEAN_PERMIT), ["file_names"])]))
    assert d.escalate


def test_apply_budget_keeps_the_riskiest_and_falls_back_safely():
    mk = lambda risk, esc=True: GatedDecision(ESCALATE if esc else DIRECT_STRUCTURAL, esc, None if esc else True, [], [], risk)
    ds = [mk(1), mk(3), mk(2), mk(0, esc=False)]
    out = apply_budget(ds, 2)
    assert [d.escalate for d in out] == [False, True, True, False]
    assert out[0].route == DIRECT_STRUCTURAL and out[0].predicted_violation is True and "budget" in out[0].reasons[-1]
    assert all(d.escalate == e for d, e in zip(apply_budget(ds, 99), [True, True, True, False]))
    assert not any(d.escalate for d in apply_budget(ds, 0))


# ---------------------------------------------------------------- M8 on the benchmark
def timed():
    return pipeline.TimedClient(FunctionClient(mock_model))


def targeted(rows):
    return [r for r in rows if r["truth"] != "conformant"][0]


def run_m8(ctx):
    return pipeline_m8.run_gated(ctx, timed(), pipeline_m8.route_all([ctx], ReadabilityGatedPolicy()))


def run_m7(ctx):
    return pipeline.run_extract_compute(ctx, timed())


def test_m8_never_escalates_what_m7_would_not(bench_cases):
    for ctx in bench_cases.values():
        m7 = {(r["source"], r["target"]): r for r in run_m7(ctx)}
        for r in run_m8(ctx):
            if r["escalated"]:
                assert m7[(r["source"], r["target"])]["escalated"], ctx.case_id


def test_m8_decides_regular_primary_cases_without_the_model(bench_cases):
    """On the templated primary wording the gates pass for the grandfathering and exception scenarios, so code decides."""
    calls = 0
    for letter in "BCDE":
        rows = run_m8(bench_cases[letter])
        t = targeted(rows)
        assert t["outcome_source"] in ("direct_code", "direct_structural"), (letter, t["outcome_source"], t["policy_reasons"])
        calls += sum(r["llm_called"] for r in rows)
    assert calls == 0


def test_m8_matches_m7_on_the_primary_scenarios_the_mock_reads(bench_cases):
    for letter in "ABCDEFGHK":
        ctx = bench_cases[letter]
        assert targeted(run_m8(ctx))["predicted_violation"] == targeted(run_m7(ctx))["predicted_violation"], letter


def test_m8_keeps_unreadable_commit_cited_adr_escalated(bench_cases):
    t = targeted(run_m8(bench_cases["J"]))
    assert t["escalated"] and t["llm_called"], t["policy_reasons"]


# ---------------------------------------------------------------- replay == live
def _frame(rows):
    return pd.DataFrame(rows)


def test_replay_reproduces_a_live_m8_run_row_for_row(bench_root, bench_cases):
    entries = [{"case_id": f"{l}01", "scenario": bench_cases[l].scenario, "split": "test", "path": f"{l}01"} for l in "ABCDEFGHJK"]
    json.dump({"seed": 7, "wording": "primary", "cases": entries}, open(os.path.join(bench_root, "manifest.json"), "w"))
    live, m7 = [], []
    for l in "ABCDEFGHJK":
        ctx = bench_cases[l]
        m7 += run_m7(ctx)
        live += run_m8(ctx)
    replayed, info = replay(bench_root, _frame(m7))
    assert info["replay_gaps"] == 0
    cols = ["case_id", "source", "target", "predicted_violation", "outcome_source", "escalated", "llm_called"]
    a = _frame(live)[cols].sort_values(["case_id", "source", "target"]).reset_index(drop=True)
    b = replayed[cols].sort_values(["case_id", "source", "target"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)
    budgeted, _ = replay(bench_root, _frame(m7), budget=0)
    assert budgeted["llm_called"].sum() == 0
