"""Remediation advice: rule-derived options always work; the AI layer is validated, grounded and never required."""
import json

import pytest
from fastapi.testclient import TestClient

from analysis.evidence.aggregator import EvidenceBundle
from analysis.semantic.llm_client import FunctionClient
from analysis.semantic.remediation import (
    RemediationAnalyzer, adr_draft, allowed_paths, parse_advice, template_options, unknown_references,
)
from api.routes import analyze as routes
from main import app
from models.rule import Architecture, ArchitectureRule, RelationType

A, F = RelationType.ALLOWED, RelationType.FORBIDDEN
ARCH = Architecture("layered", (
    ArchitectureRule("R001", "c-s", "controller", "service", A, "Controllers may call Services."),
    ArchitectureRule("R002", "s-r", "service", "repository", A, "Services may call Repositories."),
    ArchitectureRule("R003", "r-d", "repository", "database", A, "Repositories are the path to the database."),
    ArchitectureRule("R004", "no-s-d", "service", "database", F, "Services must not access the database directly."),
))


def bundle(**kw):
    d = dict(finding_key="k", finding_id="F001", rule_id="R004", rule_name="no-s-d", rule_relation="forbidden",
             rule_description="Services must not access the database directly.", source_path="app/services/order_service.py",
             target_path="app/database/connection.py", source_type="service", target_type="database", line=7,
             import_reference="app.database.connection", code_snippet="from app.database import connection\n", snapshot_date=None,
             adrs=[], evolution={"available": True, "introduced_at": "2025-03-04T10:00:00", "introducing_commit": {"sha": "abc", "message": "quick fix"}})
    d.update(kw)
    return EvidenceBundle(**d)


GOOD = {"summary": "order_service skips the repository layer.", "recommended_option": "route_via_repository",
        "steps": ["Add a method on a repository that returns the data order_service needs.", "Call it from order_service.py.", "Remove the connection import."],
        "risks": ["Behaviour could change if the query differs."]}


def client_returning(text):
    return FunctionClient(lambda system, prompt: text, "stub")


# ---------------------------------------------------------------- rule-derived layer
def test_allowed_path_is_found_through_the_rules():
    assert allowed_paths(ARCH, "service", "database") == [["service", "repository", "database"]]
    assert allowed_paths(ARCH, "controller", "database") == [["controller", "service", "repository", "database"]]


def test_no_route_means_no_routing_option():
    arch = Architecture("x", (ArchitectureRule("R1", "a", "service", "repository", A, ""),))
    assert allowed_paths(arch, "service", "database") == []
    assert [o["id"] for o in template_options(bundle(), arch)] == ["document_exception"]


def test_template_options_contain_routing_steps_and_an_adr_draft():
    opts = template_options(bundle(), ARCH)
    assert [o["id"] for o in opts] == ["route_via_repository", "document_exception"]
    assert "order_service" in " ".join(opts[0]["steps"]) and "connection" in " ".join(opts[0]["steps"])
    draft = opts[1]["adr_draft"]
    assert "order_service" in draft and "connection" in draft and "R004" in draft and "2025-03-04" in draft and "## Decision" in draft


def test_the_review_rule_option_appears_only_for_repeated_violations():
    assert "review_rule" not in [o["id"] for o in template_options(bundle(), ARCH, rule_violation_count=2)]
    assert "review_rule" in [o["id"] for o in template_options(bundle(), ARCH, rule_violation_count=3)]


def test_adr_draft_is_readable_by_the_projects_own_reader():
    from datetime import date
    from analysis.intent.adr import ADR
    from analysis.intent.reader import read_adr
    d = adr_draft(bundle())
    r = read_adr(ADR("ADR-1", "t", "accepted", "accepted", date(2025, 6, 1), "x.md", d), date(2025, 3, 4))
    assert r.permitted is True  # the draft, once filled in, would be recognised as permitting the dependency


# ---------------------------------------------------------------- AI layer
def test_without_a_model_only_rule_advice_is_returned():
    r = RemediationAnalyzer(None).suggest(bundle(), ARCH, finding_id="F001")
    assert r["source"] == "rules" and r["ai"] is None and "No language model" in r["note"] and r["recommended_option"] == "route_via_repository"


def test_a_good_reply_is_used_and_labelled_ai():
    r = RemediationAnalyzer(client_returning(json.dumps(GOOD))).suggest(bundle(), ARCH, finding_id="F001")
    assert r["source"] == "ai" and r["ai"]["steps"][0].startswith("Add a method") and r["warnings"] == [] and r["model"] == "stub"
    assert len(r["options"]) == 2  # the rule-derived options are still there next to the AI's steps


def test_a_reply_wrapped_in_text_or_fences_is_still_parsed():
    wrapped = "Sure! Here you go:\n```json\n" + json.dumps(GOOD) + "\n```"
    assert RemediationAnalyzer(client_returning(wrapped)).suggest(bundle(), ARCH)["source"] == "ai"


@pytest.mark.parametrize("bad", ["not json at all", "{}", json.dumps({**GOOD, "recommended_option": "rewrite_everything"}),
                                 json.dumps({**GOOD, "steps": []}), json.dumps({**GOOD, "steps": "do it"})])
def test_an_unusable_reply_falls_back_to_rule_advice(bad):
    r = RemediationAnalyzer(client_returning(bad)).suggest(bundle(), ARCH)
    assert r["source"] == "rules" and r["ai"] is None and "could not be used" in r["note"]


def test_a_failing_model_is_data_not_an_exception():
    def boom(system, prompt):
        raise RuntimeError("connection refused")
    r = RemediationAnalyzer(FunctionClient(boom, "stub")).suggest(bundle(), ARCH)
    assert r["source"] == "rules" and r["error"] and "could not be reached" in r["note"]


def test_files_the_model_invents_are_flagged():
    invented = {**GOOD, "steps": ["Edit payment_gateway.py and order_service.py.", "Then update ghost_helper.js."]}
    r = RemediationAnalyzer(client_returning(json.dumps(invented))).suggest(bundle(), ARCH, known_files={"app/services/order_service.py", "app/repositories/order_repository.py"})
    assert r["source"] == "ai" and "payment_gateway.py" in r["warnings"][0] and "ghost_helper.js" in r["warnings"][0] and "order_service.py" not in r["warnings"][0]


def test_known_files_and_the_two_files_in_question_are_not_flagged():
    adv = parse_advice(json.dumps({**GOOD, "steps": ["Open connection.py", "Edit order_repository.py"]}), ["route_via_repository"])
    assert unknown_references(adv, {"app/repositories/order_repository.py"}, bundle()) == []


def test_the_prompt_contains_the_facts_and_only_the_offered_options():
    seen = {}
    def spy(system, prompt):
        seen["p"] = prompt
        return json.dumps(GOOD)
    RemediationAnalyzer(FunctionClient(spy, "stub")).suggest(bundle(), ARCH)
    p = seen["p"]
    assert "R004" in p and "order_service.py" in p and "connection.py" in p and "route_via_repository" in p and "document_exception" in p and "quick fix" in p


def test_a_finding_already_justified_gets_no_fix_and_no_model_call():
    calls = []
    def spy(system, prompt):
        calls.append(1)
        return json.dumps(GOOD)
    r = RemediationAnalyzer(FunctionClient(spy, "stub")).suggest(bundle(), ARCH, justified=True)
    assert r["options"] == [] and "no fix is recommended" in r["summary"] and calls == []


# ---------------------------------------------------------------- the endpoint
@pytest.fixture
def client():
    routes._recommendations.clear()
    return TestClient(app)


@pytest.fixture
def analyze(client, bench_root):
    def go(letter):
        r = client.post("/repositories/analyze", json={"repository_path": f"{bench_root}/{letter}01/repo",
                                                       "architecture_file": f"{bench_root}/{letter}01/repo/architecture/rules.yaml"})
        body = r.json()
        return body["analysis_id"], next(f["id"] for f in body["findings"] if f["status"] == "violation")
    return go


def test_endpoint_works_with_no_model_configured(client, analyze, monkeypatch):
    monkeypatch.setattr(routes, "get_llm_client", lambda: None)
    aid, fid = analyze("A")
    r = client.post(f"/findings/{fid}/recommendation", params={"analysis_id": aid})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "rules" and body["options"] and body["disclaimer"] and body["finding_id"] == fid


def test_endpoint_uses_the_model_and_caches_the_answer(client, analyze, monkeypatch):
    calls = []
    def model(system, prompt):
        calls.append(1)
        ids = [l.split(":")[0][2:] for l in prompt.splitlines() if l.startswith("- ")]
        return json.dumps({"summary": "s", "recommended_option": ids[0], "steps": ["do the thing"], "risks": []})
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(model, "stub"))
    aid, fid = analyze("A")
    first = client.post(f"/findings/{fid}/recommendation", params={"analysis_id": aid}).json()
    second = client.post(f"/findings/{fid}/recommendation", params={"analysis_id": aid}).json()
    assert first["source"] == "ai" and not first["cached"] and second["cached"] and len(calls) == 1
    client.post(f"/findings/{fid}/recommendation", params={"analysis_id": aid, "refresh": True})
    assert len(calls) == 2


def test_endpoint_use_llm_false_never_calls_the_model(client, analyze, monkeypatch):
    def boom():
        raise AssertionError("model must not be built")
    monkeypatch.setattr(routes, "get_llm_client", boom)
    aid, fid = analyze("A")
    assert client.post(f"/findings/{fid}/recommendation", params={"analysis_id": aid, "use_llm": False}).json()["source"] == "rules"


def test_endpoint_rejects_conformant_findings_and_unknown_ids(client, analyze, monkeypatch):
    monkeypatch.setattr(routes, "get_llm_client", lambda: None)
    aid, _ = analyze("A")
    assert client.post("/findings/F999/recommendation", params={"analysis_id": aid}).status_code == 404
    conformant = next(f["id"] for f in client.get(f"/analysis/{aid}/findings").json() if f["status"] != "violation")
    assert client.post(f"/findings/{conformant}/recommendation", params={"analysis_id": aid}).status_code == 409


def test_a_model_error_is_not_cached(client, analyze, monkeypatch):
    state = {"fail": True}
    def model(system, prompt):
        if state["fail"]:
            raise RuntimeError("down")
        ids = [l.split(":")[0][2:] for l in prompt.splitlines() if l.startswith("- ")]
        return json.dumps({"summary": "s", "recommended_option": ids[0], "steps": ["x"], "risks": []})
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(model, "stub"))
    aid, fid = analyze("A")
    assert client.post(f"/findings/{fid}/recommendation", params={"analysis_id": aid}).json()["source"] == "rules"
    state["fail"] = False
    assert client.post(f"/findings/{fid}/recommendation", params={"analysis_id": aid}).json()["source"] == "ai"
