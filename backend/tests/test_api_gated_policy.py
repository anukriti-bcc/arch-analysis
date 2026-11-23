"""The API runs the gated policy (M8) by default and exposes the route and the failed readability gates."""
import pytest

from api.routes import analyze as routes
from tests.test_api_evidence import analyze, client, stub_llm  # noqa: F401  (fixtures)


def test_health_reports_the_policy(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ESCALATION_POLICY", raising=False)
    assert client.get("/health").json()["escalation_policy"] == "gated"
    monkeypatch.setenv("ESCALATION_POLICY", "v1")
    assert client.get("/health").json()["escalation_policy"] == "v1"


def test_a_clear_adr_is_read_by_code_and_the_model_is_never_called(client, analyze, stub_llm, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ESCALATION_POLICY", raising=False)
    aid, fid = analyze("C")
    ev = client.get(f"/findings/{fid}/evidence", params={"analysis_id": aid}).json()["policy"]
    assert ev["policy"] == "gated" and ev["route"] == "direct_code" and ev["escalate"] is False and ev["direct_verdict"] == "justified"
    r = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid})
    d = r.json()
    assert d["decision"]["final_verdict"] == "justified" and d["decision"]["llm_called"] is False
    assert d["decision"]["route"] == "direct_code" and d["decision"]["adr_id"] and d["semantic_analysis"] is None
    assert stub_llm.calls == 0
    stored = client.get(f"/analysis/{aid}/findings/{fid}").json()["decision"]
    assert stored["route"] == "direct_code" and stored["final_verdict"] == "justified"


def test_a_plain_violation_is_resolved_structurally(client, analyze, stub_llm, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ESCALATION_POLICY", raising=False)
    aid, fid = analyze("A")
    d = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid}).json()["decision"]
    assert d["route"] == "direct_structural" and d["final_verdict"] == "violation" and d["llm_called"] is False and stub_llm.calls == 0


def test_a_finding_the_gates_cannot_decide_goes_to_the_model_and_says_why(client, analyze, stub_llm, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ESCALATION_POLICY", raising=False)
    aid, fid = analyze("J")  # permitting ADR that shares no wording with the code
    pol = client.get(f"/findings/{fid}/evidence", params={"analysis_id": aid}).json()["policy"]
    assert pol["route"] == "escalate" and pol["failed_gates"]
    d = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid}).json()["decision"]
    assert d["llm_called"] is True and d["route"] == "escalate" and d["failed_gates"] == pol["failed_gates"]
    assert d["resolution"] == "extract_compute" and stub_llm.calls == 1


def test_forcing_the_model_on_a_code_resolved_finding_is_recorded_as_forced(client, analyze, stub_llm, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ESCALATION_POLICY", raising=False)
    aid, fid = analyze("C")
    d = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid, "force": True}).json()["decision"]
    assert d["llm_called"] is True and d["forced"] is True and d["route"] == "direct_code"


def test_triage_counts_each_route(client, analyze, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ESCALATION_POLICY", raising=False)
    aid, _ = analyze("C")
    t = client.get(f"/analysis/{aid}/triage").json()
    assert t["summary"]["policy"] == "gated"
    assert t["summary"]["by_route"] == {"direct_structural": 0, "direct_code": 1, "escalate": 0}
    assert t["summary"]["resolved_directly"] == 1 and t["summary"]["needs_semantic_review"] == 0
    assert t["items"][0]["route"] == "direct_code" and t["items"][0]["failed_gates"] == []


def test_the_old_policy_is_still_available_by_setting(client, analyze, stub_llm, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ESCALATION_POLICY", "v1")
    aid, fid = analyze("C")
    pol = client.get(f"/findings/{fid}/evidence", params={"analysis_id": aid}).json()["policy"]
    assert pol["policy"] == "v1" and pol["escalate"] is True and pol["reasons"][0].startswith("I1")
    d = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid}).json()["decision"]
    assert d["llm_called"] is True and stub_llm.calls == 1


def test_a_bad_setting_is_a_clear_server_error(client, analyze, monkeypatch):  # noqa: F811
    aid, fid = analyze("A")
    monkeypatch.setenv("ESCALATION_POLICY", "nonsense")
    r = client.get(f"/findings/{fid}/evidence", params={"analysis_id": aid})
    assert r.status_code == 500 and "ESCALATION_POLICY" in r.json()["detail"]
