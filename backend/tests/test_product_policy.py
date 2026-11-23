"""The policy the product runs: M8 (gated) by default, v1 (M7) on request, one decision shape for both.

The adapter must not change what either policy decides; it only reduces both to the shape the API and UI use.
"""
import pytest

from analysis.policy.escalation import EvidenceGuidedPolicy
from analysis.policy.gated import DIRECT_CODE, DIRECT_STRUCTURAL, ESCALATE, ReadabilityGatedPolicy
from analysis.policy.product import (
    DEFAULT_POLICY, GATED, POLICY_ENV, V1, PolicyConfigError, policy_from_env, policy_name_from_env,
)

TRUTH = {"A": "violation", "B": "justified", "C": "justified", "D": "violation", "E": "violation",
         "F": "violation", "G": "violation", "H": "violation", "J": "justified", "K": "violation"}


def decisions(bench_cases, name, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, name)
    policy = policy_from_env()
    return {L: [(policy.decide(ctx.bundle(f))) for f in ctx.violations] for L, ctx in bench_cases.items()}


# ---------------------------------------------------------------- the switch
def test_the_default_is_the_confirmed_gated_policy(monkeypatch):
    monkeypatch.delenv(POLICY_ENV, raising=False)
    assert DEFAULT_POLICY == GATED and policy_name_from_env() == GATED and policy_from_env().name == GATED


@pytest.mark.parametrize("value,expected", [("v1", V1), ("V1", V1), (" gated ", GATED), ("", GATED)])
def test_the_setting_is_read_each_time_and_is_case_and_space_tolerant(monkeypatch, value, expected):
    monkeypatch.setenv(POLICY_ENV, value)
    assert policy_name_from_env() == expected


def test_an_unknown_setting_is_an_error_not_a_silent_fallback(monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "m9")
    with pytest.raises(PolicyConfigError, match="gated, v1"):
        policy_from_env()


# ---------------------------------------------------------------- the adapter changes nothing
def test_gated_adapter_reports_exactly_what_the_frozen_policy_decides(bench_cases, monkeypatch):
    got = decisions(bench_cases, GATED, monkeypatch)
    raw = ReadabilityGatedPolicy()
    for letter, ctx in bench_cases.items():
        for f, d in zip(ctx.violations, got[letter]):
            r = raw.decide(ctx.bundle(f))
            assert (d.route, d.escalate, d.reasons, d.failed_gates, d.adr_id) == (r.route, r.escalate, r.reasons, r.failed_gates, r.adr_id)
            assert d.direct_verdict == (None if r.escalate else ("violation" if r.predicted_violation else "justified"))


def test_v1_adapter_reports_exactly_what_the_frozen_policy_decides(bench_cases, monkeypatch):
    got = decisions(bench_cases, V1, monkeypatch)
    raw = EvidenceGuidedPolicy()
    for letter, ctx in bench_cases.items():
        for f, d in zip(ctx.violations, got[letter]):
            r = raw.decide(ctx.bundle(f))
            assert (d.escalate, d.direct_verdict, d.reasons) == (r.escalate, r.direct_verdict, r.reasons)
            assert d.route == (ESCALATE if r.escalate else DIRECT_STRUCTURAL) and d.failed_gates == [] and d.policy == V1


def test_both_policies_produce_the_same_keys_so_the_ui_needs_one_shape(bench_cases, monkeypatch):
    keys = {frozenset(d.to_dict()) for name in (GATED, V1) for ds in decisions(bench_cases, name, monkeypatch).values() for d in ds}
    assert keys == {frozenset({"policy", "route", "escalate", "direct_verdict", "reasons", "failed_gates", "adr_id"})}


# ---------------------------------------------------------------- what M8 does in the product (primary wording)
def test_routes_per_scenario_match_the_measured_policy(bench_cases, monkeypatch):
    got = {L: ds[0] for L, ds in decisions(bench_cases, GATED, monkeypatch).items()}
    assert {L: d.route for L, d in got.items()} == {
        "A": DIRECT_STRUCTURAL, "B": DIRECT_CODE, "C": DIRECT_CODE, "D": DIRECT_CODE, "E": DIRECT_CODE,
        "F": DIRECT_STRUCTURAL, "G": DIRECT_STRUCTURAL, "H": ESCALATE, "J": ESCALATE, "K": DIRECT_STRUCTURAL}


def test_no_wrong_verdict_is_made_without_the_model(bench_cases, monkeypatch):
    """The safety property of M8 (P3): every verdict made without the model is right."""
    for letter, ds in decisions(bench_cases, GATED, monkeypatch).items():
        for d in ds:
            if not d.escalate:
                assert d.direct_verdict == TRUTH[letter], (letter, d.route, d.reasons)


def test_code_reading_can_justify_a_finding_which_v1_could_not(bench_cases, monkeypatch):
    d = decisions(bench_cases, GATED, monkeypatch)["C"][0]
    assert d.route == DIRECT_CODE and d.direct_verdict == "justified" and d.adr_id and d.reasons[0].startswith("R1")
    assert decisions(bench_cases, V1, monkeypatch)["C"][0].escalate  # v1 would have called the model


def test_gated_never_escalates_what_v1_resolves_without_the_model(bench_cases, monkeypatch):
    g, v = decisions(bench_cases, GATED, monkeypatch), decisions(bench_cases, V1, monkeypatch)
    for letter in g:
        for dg, dv in zip(g[letter], v[letter]):
            assert not (dg.escalate and not dv.escalate), letter  # M8's escalations are a subset of M7's


def test_a_finding_sent_to_the_model_names_the_gates_that_failed(bench_cases, monkeypatch):
    d = decisions(bench_cases, GATED, monkeypatch)["J"][0]
    assert d.escalate and d.failed_gates and d.direct_verdict is None
    for gate in d.failed_gates:
        assert any(gate in r for r in d.reasons)


def test_wording_the_gates_cannot_read_goes_to_the_model_with_reasons(bench_cases_heldout, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, GATED)
    ctx = bench_cases_heldout["C"]
    d = policy_from_env().decide(ctx.bundle(ctx.violations[0]))
    assert d.route == ESCALATE and d.failed_gates and d.escalate
