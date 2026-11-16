"""API for evolution evidence (M2) and the evidence-guided semantic workflow (M3-M5)."""
import pytest
from fastapi.testclient import TestClient

from analysis.semantic.llm_client import FunctionClient
from api.routes import analyze as routes
from experiments.mock_llm import mock_model
from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def analyze(client, bench_root):
    def go(letter):
        r = client.post("/repositories/analyze", json={
            "repository_path": f"{bench_root}/{letter}01/repo",
            "architecture_file": f"{bench_root}/{letter}01/repo/architecture/rules.yaml"})
        assert r.status_code == 200
        body = r.json()
        fid = next(f["id"] for f in body["findings"] if f["status"] == "violation")
        return body["analysis_id"], fid
    return go


@pytest.fixture
def stub_llm(monkeypatch):
    stub = FunctionClient(mock_model, "stub-model")
    monkeypatch.setattr(routes, "get_llm_client", lambda: stub)
    return stub


def test_evolution_endpoint_returns_introducing_commit(client, analyze):
    aid, fid = analyze("C")
    r = client.get(f"/findings/{fid}/evolution", params={"analysis_id": aid})
    assert r.status_code == 200
    ev = r.json()["evolution_evidence"]
    assert ev["available"] and ev["introducing_commit"]["sha"] and ev["age_days"] > 0


def test_evolution_is_cached_on_the_finding(client, analyze):
    aid, fid = analyze("C")
    client.get(f"/findings/{fid}/evolution", params={"analysis_id": aid})
    detail = client.get(f"/analysis/{aid}/findings/{fid}").json()
    assert detail["evolution_evidence"]["introducing_commit"]


def test_unknown_finding_is_404_for_both_endpoints(client, analyze):
    aid, _ = analyze("A")
    assert client.get("/findings/F999/evolution", params={"analysis_id": aid}).status_code == 404
    assert client.post("/findings/F999/semantic-analysis", params={"analysis_id": aid}).status_code == 404


def test_sufficient_evidence_means_no_llm_call(client, analyze, stub_llm):
    aid, fid = analyze("A")
    r = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid})
    assert r.status_code == 200
    d = r.json()["decision"]
    assert d["llm_called"] is False and d["final_verdict"] == "violation" and d["outcome_source"] == "direct"
    assert stub_llm.calls == 0 and r.json()["semantic_analysis"] is None


def test_insufficient_evidence_escalates_and_stores_the_verdict(client, analyze, stub_llm):
    aid, fid = analyze("C")  # grandfathered before cutoff -> justified, needs ADR + date
    r = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid})
    assert r.status_code == 200
    d = r.json()
    assert d["decision"]["llm_called"] and d["decision"]["final_verdict"] == "justified"
    assert d["decision"]["reasons"][0].startswith("I1") and stub_llm.calls == 1
    stored = client.get(f"/analysis/{aid}/findings/{fid}").json()
    assert stored["semantic_analysis"]["verdict"] == "justified" and stored["decision"]["final_verdict"] == "justified"
    assert stored["architectural_intent"]["adrs"]


def test_force_calls_llm_even_when_policy_would_not(client, analyze, stub_llm):
    aid, fid = analyze("A")
    r = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid, "force": True})
    assert r.json()["decision"]["llm_called"] and r.json()["decision"]["forced"] and stub_llm.calls == 1


def test_missing_llm_configuration_is_a_clear_503(client, analyze, monkeypatch):
    monkeypatch.setattr(routes, "get_llm_client", lambda: None)
    aid, fid = analyze("C")
    r = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid})
    assert r.status_code == 503 and "LLM_BASE_URL" in r.json()["detail"]


def test_llm_failure_falls_back_to_violation_and_says_so(client, analyze, monkeypatch):
    def boom(s, p):
        raise TimeoutError("slow")
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(boom))
    aid, fid = analyze("C")
    d = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid}).json()["decision"]
    assert d["final_verdict"] == "violation" and d["outcome_source"] == "fallback"


def test_conformant_finding_is_rejected(client, bench_root):
    r = client.post("/repositories/analyze", json={
        "repository_path": f"{bench_root}/A01/repo", "architecture_file": f"{bench_root}/A01/repo/architecture/rules.yaml"}).json()
    ok = next(f["id"] for f in r["findings"] if f["status"] == "conformant")
    assert client.post(f"/findings/{ok}/semantic-analysis", params={"analysis_id": r["analysis_id"]}).status_code == 409


def test_cache_filled_by_the_experiment_serves_the_live_api_without_calling_the_model(client, bench_root, bench_cases, tmp_path, monkeypatch):
    """Demo safety net: responses cached during `run_experiments` are reused by the web app
    (same prompt => same cache key), so a demo can run instantly and offline."""
    from analysis.semantic.llm_client import CachingClient
    from experiments import pipeline
    stub = FunctionClient(mock_model, "demo-model")
    shared = CachingClient(stub, str(tmp_path / "shared.sqlite"))

    pipeline.run_extract_compute(bench_cases["C"], pipeline.TimedClient(shared))  # what the experiment (method M7) does
    calls_after_experiment = stub.calls
    assert calls_after_experiment == 1

    monkeypatch.setattr(routes, "get_llm_client", lambda: shared)
    r = client.post("/repositories/analyze", json={
        "repository_path": f"{bench_root}/C01/repo", "architecture_file": f"{bench_root}/C01/repo/architecture/rules.yaml"}).json()
    fid = next(f["id"] for f in r["findings"] if f["status"] == "violation")
    out = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": r["analysis_id"]}).json()

    assert stub.calls == calls_after_experiment            # the model was NOT called again
    assert out["semantic_analysis"]["cached"] is True
    assert out["decision"]["final_verdict"] == "justified"
