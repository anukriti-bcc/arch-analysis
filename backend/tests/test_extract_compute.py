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
    assert EXTRACT_VERSION.startswith("x4")  # x4 = the x2 prompt + code-side grounding
    assert "introducing commit cites this ADR" in SYSTEM_EXTRACT and "purpose rather than by file name" in SYSTEM_EXTRACT
    assert "names or describes a different module" in SYSTEM_EXTRACT  # the rule must not turn every ADR into 'covers'


# ---------------------------------------------------------------- grounding (x4)

from analysis.semantic.extract import decision_dates, ground_limit, strip_adr_dates  # noqa: E402
from experiments.benchmark.generate import build_case  # noqa: E402


def adr_obj(text, date_=date(2025, 5, 20), adr_id="ADR-1"):
    from analysis.intent.adr import ADR, ADRMatch
    return ADRMatch(ADR(adr_id, "t", "accepted", "", date_, "a.md", text), ("file_names",))


def lim(d, adr_id="ADR-1", kind="introduced_on_or_before"):
    return x(adr_id=adr_id, limit=kind, limit_date=d)


def test_a_limit_date_written_in_the_decision_is_accepted():
    m = adr_obj("---\ndate: 2025-05-20\n---\n## Decision\n\nAllowed for code introduced on or before 13 September 2025.")
    out = ground_limit(lim(date(2025, 9, 13)), [m])
    assert out["limit"] == "introduced_on_or_before" and out["limit_date"] == date(2025, 9, 13) and out["grounding"] == "accepted"


def test_the_records_own_date_is_rejected_as_a_limit():
    """Development finding: 6 of 6 failing mixed-decision cases had the model report the ADR's header date as a limit."""
    m = adr_obj("---\ndate: 2025-05-20\n---\n## Decision\n\n`a` may use `b` directly. `c` must keep going through the layer.")
    out = ground_limit(lim(date(2025, 5, 20)), [m])
    assert out["limit"] == "none" and out["limit_date"] is None and "record date" in out["grounding"]
    assert resolve_extraction(out, date(2025, 7, 1)).outcome == "justified"  # no limit left, so the permission stands


def test_a_date_not_in_the_decision_is_replaced_by_its_only_date_or_left_unresolved():
    one = adr_obj("## Decision\n\nAllowed up to 2025-09-13.")
    out = ground_limit(lim(date(2025, 9, 30)), [one])  # e.g. the model converted 'end of September' itself
    assert out["limit_date"] == date(2025, 9, 13) and out["grounding"].startswith("replaced")
    many = adr_obj("## Decision\n\nAllowed up to 2025-09-13. Review on 2025-12-01.")
    out = ground_limit(lim(date(2025, 9, 30)), [many])
    assert out["limit_date"] is None and out["grounding"].startswith("unresolved")
    assert resolve_extraction(out, date(2025, 1, 1)).outcome == "unresolved"
    none = adr_obj("## Decision\n\nAllowed for now.")
    assert ground_limit(lim(date(2025, 9, 30)), [none])["limit_date"] is None


def test_no_limit_claimed_is_left_alone_and_adr_id_selects_the_record():
    assert ground_limit(x(), [adr_obj("## Decision\n\nAllowed.")])["grounding"] == "no limit claimed"
    a = adr_obj("## Decision\n\nAllowed through 2025-01-01.", adr_id="ADR-1")
    b = adr_obj("## Decision\n\nAllowed through 2025-02-02.", adr_id="ADR-2")
    assert ground_limit(lim(date(2025, 2, 2), adr_id="ADR-2"), [a, b])["grounding"] == "accepted"
    assert ground_limit(lim(date(2025, 2, 2), adr_id="ADR-1"), [a, b])["limit_date"] == date(2025, 1, 1)


def test_metadata_dates_are_not_decision_dates():
    text = "---\nid: A\ndate: 2025-01-02\n---\n# T\n\nDate: 2025-01-02\n\n## Decision\n\nAllowed up to 2025-09-13."
    assert "2025-01-02" not in strip_adr_dates(text)
    assert decision_dates(adr_obj(text).adr) == {date(2025, 9, 13)}
    no_heading = adr_obj("Date: 2025-01-02\n\nPlain text without a decision heading.")
    assert decision_dates(no_heading.adr) == set()  # header date still excluded when no Decision section is found


# The six real extractions that failed under prompt x2 (hard tier, development seeds 21 and 22). The model read each ADR
# correctly, then wrote the record date as `introduced_on_or_before`. With grounding, all six resolve as justified.
X2_L_FAILURES = [(21, "L02", "ADR-016", "2025-05-20"), (21, "L04", "ADR-017", "2025-06-22"), (21, "L06", "ADR-005", "2025-06-10"),
                 (22, "L01", "ADR-029", "2025-07-14"), (22, "L02", "ADR-015", "2025-06-24"), (22, "L03", "ADR-023", "2025-07-05")]


@pytest.mark.parametrize("seed,cid,adr_id,limit_date", X2_L_FAILURES)
def test_the_six_real_x2_mixed_decision_failures_are_fixed_by_grounding(tmp_path, seed, cid, adr_id, limit_date):
    build_case(str(tmp_path), cid, "L_adr_mixed_permits_target", seed, wording="hard")
    ctx = pipeline.CaseContext(str(tmp_path), {"case_id": cid, "scenario": "L_adr_mixed_permits_target", "split": "dev", "path": cid})
    f = next(f for f in ctx.findings if ctx.truth[ctx.edge(f)] != "conformant")
    bundle = ctx.bundle(f)
    pasted = parse_extraction_json(json.dumps({"adr_id": adr_id, "decision": "permits", "covers_this_dependency": "yes",
                                               "limit": "introduced_on_or_before", "limit_date": limit_date, "explanation": "as pasted"}))
    from analysis.intent.reader import introduction_date
    introduced = introduction_date(bundle.evolution)
    assert resolve_extraction(pasted, introduced).outcome == "violation"   # what x2 did: wrong
    grounded = ground_limit(pasted, bundle.adrs)
    assert grounded["limit"] == "none" and "record date" in grounded["grounding"]
    assert resolve_extraction(grounded, introduced).outcome == "justified" and ctx.truth[ctx.edge(f)] == "justified"


def test_pipeline_applies_grounding_end_to_end(bench_cases):
    """A model that reports the record date as a limit on a case with NO limit (scenario B) must still be justified."""
    ctx = bench_cases["B"]
    f = next(f for f in ctx.findings if ctx.truth[ctx.edge(f)] != "conformant")
    record_date = ctx.bundle(f).adrs[0].adr.date.isoformat()

    def fn(system, prompt):
        return json.dumps({"adr_id": None, "decision": "permits", "covers_this_dependency": "yes",
                           "limit": "introduced_on_or_before", "limit_date": record_date, "explanation": "copied the header date"})
    r = target(pipeline.run_extract_compute(ctx, pipeline.TimedClient(FunctionClient(fn, "headerdate"))))
    assert r["predicted_violation"] is False and r["truth"] == "justified" and "record date" in json.loads(r["extraction"])["grounding"]
