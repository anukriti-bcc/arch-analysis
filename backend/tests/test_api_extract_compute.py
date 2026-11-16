"""The product path uses extract-then-compute (method M7): the model extracts, code computes."""
import json
import re

import pytest

from analysis.semantic.llm_client import FunctionClient
from api.routes import analyze as routes
from tests.test_api_evidence import analyze, client, stub_llm  # noqa: F401  (fixtures)


def post(client, aid, fid, **params):
    r = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid, **params})
    assert r.status_code == 200
    return r.json()


def test_before_cutoff_is_justified_and_the_computation_is_shown(client, analyze, stub_llm):  # noqa: F811
    aid, fid = analyze("C")
    d = post(client, aid, fid)
    assert d["decision"]["resolution"] == "extract_compute" and d["decision"]["outcome_source"] == "llm_extract"
    assert d["decision"]["final_verdict"] == "justified" and stub_llm.calls == 1
    s = d["semantic_analysis"]
    assert s["mode"] == "extract_compute" and s["verdict"] == "justified" and "satisfies" in s["computed"]
    assert s["extraction"]["limit"] == "introduced_on_or_before" and s["extraction"]["grounding"] == "accepted"


def test_after_cutoff_is_a_violation_even_if_the_model_claims_otherwise(client, analyze, monkeypatch):  # noqa: F811
    """The measured failure of free-form review: the model said the dependency predates the freeze. Here the verdict is code."""
    def fn(system, prompt):
        m = re.search(r"on or before (\d{4}-\d{2}-\d{2})", prompt)
        return json.dumps({"adr_id": "A", "decision": "permits", "covers_this_dependency": "yes", "limit": "introduced_on_or_before",
                           "limit_date": m.group(1), "explanation": "The dependency was introduced before the freeze."})
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(fn, "liar"))
    aid, fid = analyze("D")
    d = post(client, aid, fid)
    assert d["decision"]["final_verdict"] == "violation" and "does not satisfy" in d["semantic_analysis"]["computed"]
    assert "before the freeze" in d["semantic_analysis"]["explanation"]  # shown, but it did not decide


def test_a_copied_record_date_is_rejected_by_grounding(client, analyze, monkeypatch):  # noqa: F811
    def fn(system, prompt):
        record = re.search(r"Date: (\d{4}-\d{2}-\d{2})", prompt)
        return json.dumps({"adr_id": None, "decision": "permits", "covers_this_dependency": "yes", "limit": "introduced_on_or_before",
                           "limit_date": record.group(1) if record else None, "explanation": "copied the header date"})
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(fn, "headerdate"))
    aid, fid = analyze("B")
    d = post(client, aid, fid)
    assert d["decision"]["final_verdict"] == "justified" and "record date" in d["semantic_analysis"]["extraction"]["grounding"]


def test_forcing_review_with_no_adr_uses_the_ordinary_review_prompt(client, analyze, stub_llm):  # noqa: F811
    aid, fid = analyze("A")
    d = post(client, aid, fid, force=True)
    assert d["decision"]["resolution"] == "review" and d["decision"]["forced"] and d["semantic_analysis"]["mode"] == "review"


def test_unparseable_reply_keeps_the_violation_and_is_labelled(client, analyze, monkeypatch):  # noqa: F811
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(lambda s, p: "no idea", "garbled"))
    aid, fid = analyze("B")
    d = post(client, aid, fid)
    assert d["decision"]["final_verdict"] == "violation" and d["decision"]["outcome_source"] == "fallback"
    assert d["semantic_analysis"]["parsed_ok"] is False and d["semantic_analysis"]["verdict"] is None


def test_direct_verdicts_record_their_resolution(client, analyze, stub_llm):  # noqa: F811
    aid, fid = analyze("F")  # superseded ADR: decided by the status rule, no model
    d = post(client, aid, fid)
    assert d["decision"]["resolution"] == "direct" and stub_llm.calls == 0
