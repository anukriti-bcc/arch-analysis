"""Evidence aggregation (Milestone 3) and the escalation policy (Milestone 5),
checked scenario by scenario against how the benchmark was designed."""
import pytest

from analysis.evidence.aggregator import EvidenceBundle
from analysis.intent.adr import ADR, ADRMatch
from analysis.policy.escalation import EvidenceGuidedPolicy


def violation(ctx):
    return ctx.violations[0]


def ids(bundle):
    return [m.adr.id for m in bundle.adrs]


# ----------------------------------------------------------- aggregation

def test_bundle_has_all_three_evidence_sources(bench_cases):
    ctx = bench_cases["B"]
    b = ctx.bundle(violation(ctx))
    assert b.rule_id in {"R004", "R005", "R006"} and b.rule_description
    assert b.code_snippet and b.adrs
    assert b.evolution["introducing_commit"] and b.snapshot_date


def test_commit_cited_adr_is_linked_only_when_evolution_is_used(bench_cases):
    ctx = bench_cases["J"]
    f = violation(ctx)
    with_history = ctx.bundle(f, use_evolution=True)
    without = ctx.bundle(f, use_evolution=False)
    assert len(with_history.adrs) == 1 and "commit_reference" in with_history.adrs[0].reasons
    assert without.adrs == []  # wording shares nothing with the code -> text matching misses it


def test_adrs_can_be_switched_off(bench_cases):
    ctx = bench_cases["B"]
    b = ctx.aggregator.build(violation(ctx), use_adrs=False, use_evolution=True)
    assert b.adrs == [] and b.evolution is not None


def test_bundle_without_evolution_analyzer_still_has_snapshot_date(bench_cases):
    from analysis.evidence.aggregator import EvidenceAggregator
    ctx = bench_cases["A"]
    agg = EvidenceAggregator(ctx.repo, ctx.architecture, ctx.adrs, evolution_analyzer=None)
    b = agg.build(violation(ctx))
    assert b.evolution is None and b.snapshot_date


def test_bundle_serialises_to_plain_json(bench_cases):
    import json
    ctx = bench_cases["C"]
    json.dumps(ctx.bundle(violation(ctx)).to_dict())


def test_citing_an_unknown_adr_is_ignored(bench_cases):
    from analysis.evidence.aggregator import EvidenceAggregator
    ctx = bench_cases["J"]
    agg = EvidenceAggregator(ctx.repo, ctx.architecture, [], ctx.aggregator.evolution_analyzer)  # no ADRs loaded
    assert agg.build(violation(ctx)).adrs == []


# ---------------------------------------------------------------- policy

POLICY = EvidenceGuidedPolicy()


@pytest.mark.parametrize("letter,escalate", [
    ("A", False),  # plain violation: evidence sufficient
    ("B", True),   # active ADR relevant
    ("C", True), ("D", True), ("E", True),
    ("F", False),  # only a superseded record exists
    ("G", True),   # decoy: passing mention still escalates (documented cost)
    ("H", True),   # 'temporary' language in the introducing commit
    ("J", True),   # ADR reached through the commit's citation
    ("K", True),
])
def test_policy_decision_per_scenario(bench_cases, letter, escalate):
    ctx = bench_cases[letter]
    d = POLICY.decide(ctx.bundle(violation(ctx)))
    assert d.escalate is escalate
    assert (d.direct_verdict is None) == escalate
    assert d.reasons


def test_superseded_only_is_resolved_without_llm_with_reason(bench_cases):
    ctx = bench_cases["F"]
    d = POLICY.decide(ctx.bundle(violation(ctx)))
    assert d.direct_verdict == "violation" and d.reasons[0].startswith("I2")


def test_history_off_loses_the_commit_cited_adr(bench_cases):
    ctx = bench_cases["J"]
    d = EvidenceGuidedPolicy(use_history=False).decide(ctx.bundle(violation(ctx), use_evolution=False))
    assert d.escalate is False  # this is the evolution-evidence ablation


def test_intent_off_relies_on_history_signals_only(bench_cases):
    ctx = bench_cases["B"]
    d = EvidenceGuidedPolicy(use_intent=False).decide(ctx.bundle(violation(ctx), use_adrs=False))
    assert d.escalate is False
    ctx = bench_cases["H"]
    assert EvidenceGuidedPolicy(use_intent=False).decide(ctx.bundle(violation(ctx), use_adrs=False)).escalate is True


def _bundle(adrs=(), evolution=None):
    return EvidenceBundle(
        finding_key="k", finding_id="F001", rule_id="R004", rule_name="n", rule_relation="forbidden",
        rule_description="d", source_path="a.py", target_path="b.py", source_type="service",
        target_type="database", line=1, import_reference="x", code_snippet="", snapshot_date=None,
        adrs=list(adrs), evolution=evolution,
    )


def _match(status):
    return ADRMatch(ADR("ADR-001", "t", status, status, None, "p", "text"), ("rule_id",))


def _evo(**signals):
    base = {"temporary_language": [], "migration_language": [], "issue_references": [], "adr_references": []}
    return {"available": True, "introducing_commit": {"sha": "x"}, "reintroduced": signals.pop("reintroduced", False),
            "message_signals": {**base, **signals}}


def test_unknown_status_adr_escalates_rather_than_being_discarded():
    assert POLICY.decide(_bundle([_match("unknown")])).escalate is True


def test_mixed_active_and_inactive_adrs_escalate():
    assert POLICY.decide(_bundle([_match("superseded"), _match("accepted")])).escalate is True


@pytest.mark.parametrize("evo,code", [
    (_evo(temporary_language=["temp"]), "H1"),
    (_evo(migration_language=["legacy"]), "H2"),
    (_evo(reintroduced=True), "H3"),
])
def test_each_history_rule_triggers_alone(evo, code):
    d = POLICY.decide(_bundle(evolution=evo))
    assert d.escalate and d.reasons[0].startswith(code)


def test_unavailable_history_never_escalates_by_itself():
    assert POLICY.decide(_bundle(evolution={"available": False})).escalate is False
    assert POLICY.decide(_bundle(evolution=None)).escalate is False


def test_no_evidence_is_sufficient():
    d = POLICY.decide(_bundle())
    assert d.escalate is False and d.direct_verdict == "violation"
