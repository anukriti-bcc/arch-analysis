"""Extract-then-compute (M7): the LLM extracts facts, code computes the verdict.

Uses scripted fake models, so these tests prove the DIVISION OF LABOUR (what the code decides, and that a model
cannot influence the date comparison), not how well a real model extracts."""
import json
import re
from datetime import date

import pytest

from analysis.semantic.extract import (
    SYSTEM_EXTRACT, LLMExtractAnalyzer, parse_extraction_json, render_extract_prompt, resolve_extraction,
)
from analysis.semantic.llm_client import FunctionClient
from experiments import pipeline


def x(**kw):
    base = {"adr_id": "ADR-1", "decision": "permits", "covers_this_dependency": "yes", "limit": "none",
            "limit_date": None, "explanation": ""}
    return {**base, **kw}


D = date(2025, 9, 13)


# ---------------------------------------------------------------- parsing

def test_parses_clean_fenced_and_chatty_replies():
    obj = {"adr_id": "ADR-7", "decision": "permits", "covers_this_dependency": "yes",
           "limit": "introduced_on_or_before", "limit_date": "2025-09-13", "explanation": "ok"}
    for text in (json.dumps(obj), f"```json\n{json.dumps(obj)}\n```", f"Sure! {json.dumps(obj)} Hope that helps."):
        got = parse_extraction_json(text)
        assert got["limit_date"] == D and got["limit"] == "introduced_on_or_before" and got["adr_id"] == "ADR-7"


def test_normalises_enumerations_and_rejects_invalid_ones():
    ok = parse_extraction_json('{"decision": "Does Not Address", "covers_this_dependency": "NO", "limit": "none"}')
    assert ok["decision"] == "does_not_address" and ok["covers_this_dependency"] == "no" and ok["limit_date"] is None
    assert parse_extraction_json('{"decision": "maybe", "covers_this_dependency": "yes", "limit": "none"}') is None
    assert parse_extraction_json('{"verdict": "violation"}') is None  # a review-style reply is not an extraction
    assert parse_extraction_json("") is None and parse_extraction_json("no json here") is None


def test_unusable_dates_become_none_not_errors():
    for bad in ("not a date", "2025-13-45", None, ""):
        got = parse_extraction_json(json.dumps({"decision": "permits", "covers_this_dependency": "yes",
                                                "limit": "introduced_before", "limit_date": bad}))
        assert got["limit_date"] is None


# ---------------------------------------------------------------- the computation

@pytest.mark.parametrize("limit,intro,expected", [
    ("introduced_on_or_before", date(2025, 9, 13), "justified"),   # boundary day is included
    ("introduced_on_or_before", date(2025, 9, 14), "violation"),
    ("introduced_on_or_before", date(2025, 9, 12), "justified"),
    ("introduced_before", date(2025, 9, 12), "justified"),
    ("introduced_before", date(2025, 9, 13), "violation"),         # strictly before
    ("introduced_after", date(2025, 9, 14), "justified"),
    ("introduced_after", date(2025, 9, 13), "violation"),          # strictly after
])
def test_date_limits_are_applied_in_code(limit, intro, expected):
    assert resolve_extraction(x(limit=limit, limit_date=D), intro).outcome == expected


def test_decision_and_scope_rules():
    assert resolve_extraction(x(), None).outcome == "justified"
    assert resolve_extraction(x(decision="prohibits"), None).outcome == "violation"
    assert resolve_extraction(x(decision="does_not_address"), None).outcome == "violation"
    assert resolve_extraction(x(covers_this_dependency="no"), None).outcome == "violation"
    assert resolve_extraction(x(covers_this_dependency="unclear"), None).outcome == "unresolved"


def test_missing_facts_are_unresolved_never_guessed():
    assert resolve_extraction(x(limit="introduced_before", limit_date=None), date(2025, 1, 1)).outcome == "unresolved"
    assert resolve_extraction(x(limit="introduced_before", limit_date=D), None).outcome == "unresolved"
    assert resolve_extraction(x(limit="introduced_before", limit_date=D), None).predicted_violation  # keeps the structural verdict


# ---------------------------------------------------------------- the prompt withholds the numbers a model would compare

def test_prompt_contains_no_introduction_date_snapshot_date_or_age(bench_cases):
    ctx = bench_cases["D"]
    f = next(f for f in ctx.findings if ctx.truth[ctx.edge(f)] != "conformant")
    bundle = ctx.bundle(f)
    prompt = render_extract_prompt(bundle)
    assert bundle.evolution["introduced_at"][:10] not in prompt
    assert bundle.snapshot_date[:10] not in prompt
    assert "days before" not in prompt and "introduced on" not in prompt.lower().split("<adr")[0]
    assert "arithmetic" in SYSTEM_EXTRACT  # the model is told not to compare dates


# ---------------------------------------------------------------- the pipeline

def fake_extractor(claim_dates_wrongly=False):
    """Extracts like a competent reader; if asked, also writes a WRONG date verdict in its explanation, which
    must have no effect because the verdict is computed in code."""
    def fn(system, prompt):
        if "report facts" not in system.lower():  # review prompt (history-only escalations)
            return json.dumps({"verdict": "violation", "confidence": 0.9, "explanation": "review", "evidence_used": []})
        m = re.search(r"on or before (\d{4}-\d{2}-\d{2})", prompt)
        return json.dumps({
            "adr_id": "ADR", "decision": "permits", "covers_this_dependency": "yes",
            "limit": "introduced_on_or_before" if m else "none", "limit_date": m.group(1) if m else None,
            "explanation": "The dependency was introduced before the freeze, so it is covered." if claim_dates_wrongly else "ok"})
    return pipeline.TimedClient(FunctionClient(fn, "fake"))


def target(rows):
    return next(r for r in rows if r["truth"] != "conformant")


def test_after_cutoff_is_a_violation_even_if_the_model_claims_otherwise(bench_cases):
    """THE measured failure: the model said 'introduced before the freeze' for an after-cutoff dependency."""
    r = target(pipeline.run_extract_compute(bench_cases["D"], fake_extractor(claim_dates_wrongly=True)))
    assert r["truth"] == "violation" and r["predicted_violation"] is True
    assert r["outcome_source"] == "llm_extract" and "does not satisfy" in r["computed"]


def test_before_cutoff_is_justified_by_computation(bench_cases):
    r = target(pipeline.run_extract_compute(bench_cases["C"], fake_extractor()))
    assert r["truth"] == "justified" and r["predicted_violation"] is False and "satisfies" in r["computed"]


def test_one_call_per_escalation_and_none_for_direct_cases(bench_cases):
    client = fake_extractor()
    for letter, calls, direct in (("A", 0, True), ("F", 0, True), ("B", 1, False), ("C", 1, False)):
        before = client.inner.calls
        r = target(pipeline.run_extract_compute(bench_cases[letter], client))
        assert client.inner.calls - before == calls
        assert (r["outcome_source"] == "direct") is direct


def test_history_only_escalation_uses_the_ordinary_review_prompt(bench_cases):
    """H has no ADR to extract from: same prompt (and cache key) as M5, so no extra cost."""
    seen = []
    base = fake_extractor()

    def spy(system, prompt):
        seen.append("report facts" in system.lower())
        return base.inner.fn(system, prompt)
    r = target(pipeline.run_extract_compute(bench_cases["H"], pipeline.TimedClient(FunctionClient(spy, "spy"))))
    assert r["escalated"] and seen == [False] and r["outcome_source"] == "llm"


def test_unparseable_reply_falls_back_to_the_structural_verdict_and_is_labelled(bench_cases):
    client = pipeline.TimedClient(FunctionClient(lambda s, p: "I am not sure.", "garbled"))
    r = target(pipeline.run_extract_compute(bench_cases["B"], client))
    assert r["predicted_violation"] is True and r["outcome_source"] == "fallback" and r["parsed_ok"] is False


def test_unclear_scope_is_a_labelled_fallback(bench_cases):
    fn = lambda s, p: json.dumps({"decision": "permits", "covers_this_dependency": "unclear", "limit": "none"})
    r = target(pipeline.run_extract_compute(bench_cases["B"], pipeline.TimedClient(FunctionClient(fn, "unclear"))))
    assert r["predicted_violation"] is True and r["outcome_source"] == "fallback" and r["verdict"] is None


def test_m7_escalates_exactly_what_m5_escalates(bench_cases):
    """The only difference from M5 must be how an escalated case is resolved."""
    client = fake_extractor()
    for letter, ctx in bench_cases.items():
        m5 = pipeline.run_evidence_guided(ctx, client)
        m7 = pipeline.run_extract_compute(ctx, client)
        assert [r["escalated"] for r in m5] == [r["escalated"] for r in m7], letter
        assert [r["policy_reasons"] for r in m5] == [r["policy_reasons"] for r in m7], letter


def test_prompt_version_and_the_commit_citation_scope_rule():
    """x2: an ADR cited by the introducing commit counts as covering the dependency (found on dev, scenario J)."""
    from analysis.semantic.extract import EXTRACT_VERSION
    assert EXTRACT_VERSION == "x2"
    assert "introducing commit cites this ADR" in SYSTEM_EXTRACT and "purpose rather than by file name" in SYSTEM_EXTRACT
    assert "names or describes a different module" in SYSTEM_EXTRACT  # the rule must not turn every ADR into 'covers'
