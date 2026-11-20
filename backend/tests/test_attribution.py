"""Stance-attribution check (fix for the mixed-decision scenario M) and the live `gated_attr` method."""
import json
from datetime import date

import pytest

from analysis.intent.adr import ADR, ADRMatch
from analysis.policy.gated import ReadabilityGatedPolicy
from analysis.semantic.attribution import check_attribution, clauses, foreign_subjects
from analysis.semantic.llm_client import FunctionClient
from experiments import pipeline, pipeline_m8, pipeline_m8_attr

SRC, TGT = "app/services/ticket_service.py", "app/database/connection.py"


def adr(decision, id="ADR-011"):
    text = f"# 11. T\n\nDate: 2025-01-01\n\n## Status\n\nAccepted\n\n## Context\n\nc\n\n## Decision\n\n{decision}\n"
    return ADR(id, "T", "accepted", "accepted", date(2025, 1, 1), "x.md", text)


def check(text, **x):
    base = {"adr_id": "ADR-011", "decision": "permits", "covers_this_dependency": "yes", "limit": "none", "limit_date": None, "explanation": ""}
    return check_attribution({**base, **x}, [ADRMatch(adr(text), ("file_names",))], SRC, TGT)


MIXED_OTHER = "`inventory_service` may use `connection` directly because latency matters. `ticket_service` must keep going through the proper layer."
MIXED_OWN = "`ticket_service` may use `connection` directly because latency matters. `report_service` must keep going through the proper layer."


def test_clauses_split_before_a_backticked_module_name():
    assert len(clauses(MIXED_OTHER)) == 2  # the reader's own splitter would return one sentence here


def test_permission_given_to_another_module_is_not_accepted():
    y = check(MIXED_OTHER)
    assert y["decision"] == "does_not_address" and y["attribution"].startswith("rejected")


def test_permission_for_this_module_is_accepted_even_when_others_are_named():
    y = check(MIXED_OWN)
    assert y["decision"] == "permits" and y["attribution"].startswith("accepted: a sentence about this module")


def test_decision_about_this_dependency_alone_is_untouched():
    y = check("We accept that `ticket_service` will use `connection` directly.")
    assert y["decision"] == "permits" and "alone" in y["attribution"]


@pytest.mark.parametrize("x", [{"decision": "prohibits"}, {"covers_this_dependency": "no"}, {"decision": "does_not_address"}])
def test_check_only_applies_to_a_permits_and_covers_reading(x):
    assert check(MIXED_OTHER, **x)["attribution"] == "not applicable"


def test_foreign_subjects_ignores_the_two_ends_and_descriptions_of_them():
    assert foreign_subjects("`ticket_service` reads `connection`; `app.database.connection` too", SRC, TGT) == set()
    assert foreign_subjects(MIXED_OTHER, SRC, TGT) == {"inventory_service"}


# ---- live method on a real mixed case, with a model that makes exactly the measured error
@pytest.fixture(scope="module")
def mixed_ctx(tmp_path_factory):
    from experiments.benchmark.generate import build_case

    root = str(tmp_path_factory.mktemp("hard_m"))
    build_case(root, "M01", "M_adr_mixed_prohibits_target", 21, wording="hard")
    meta = json.load(open(f"{root}/M01/labels.json"))
    return pipeline.CaseContext(root, {"case_id": "M01", "scenario": meta["scenario"], "split": "test", "path": "M01"})


def lazy_model(system, prompt):  # the measured failure: permission for the other module read as this module's
    return json.dumps({"adr_id": "ADR-011", "decision": "permits", "covers_this_dependency": "yes", "limit": "none", "limit_date": None, "explanation": "permits"})


def targeted(rows):
    return [r for r in rows if r["truth"] != "conformant"][0]


def test_without_the_check_the_lazy_model_calls_the_violation_justified(mixed_ctx):
    c = pipeline.TimedClient(FunctionClient(lazy_model))
    t = targeted(pipeline_m8.run_gated(mixed_ctx, c, pipeline_m8.route_all([mixed_ctx], ReadabilityGatedPolicy())))
    assert t["truth"] == "violation" and t["predicted_violation"] is False and t["escalated"]


def test_gated_attr_corrects_it_with_the_same_single_call(mixed_ctx):
    c = pipeline.TimedClient(FunctionClient(lazy_model))
    t = targeted(pipeline_m8_attr.run_gated_attr(mixed_ctx, c, pipeline_m8.route_all([mixed_ctx], ReadabilityGatedPolicy())))
    assert t["predicted_violation"] is True and t["llm_called"] and t["attribution"].startswith("rejected")
    assert c.inner.calls == 1


def test_gated_attr_equals_gated_when_there_is_no_mixed_decision(bench_cases):
    for letter in "ABCDEFGHJK":
        ctx = bench_cases[letter]
        d = pipeline_m8.route_all([ctx], ReadabilityGatedPolicy())
        from experiments.mock_llm import mock_model
        a = pipeline_m8.run_gated(ctx, pipeline.TimedClient(FunctionClient(mock_model)), d)
        b = pipeline_m8_attr.run_gated_attr(ctx, pipeline.TimedClient(FunctionClient(mock_model)), d)
        assert [r["predicted_violation"] for r in a] == [r["predicted_violation"] for r in b], letter
