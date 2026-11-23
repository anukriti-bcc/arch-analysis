"""Triage, evidence and experiment-results endpoints used by the web UI."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from api.routes import experiments as exp
from main import app

# These tests describe the v1 policy (M7); the default gated policy (M8) is covered in test_product_policy.py.
pytestmark = pytest.mark.usefixtures("policy_v1")


@pytest.fixture
def client():
    return TestClient(app)


def analyze(client, bench_root, letter):
    r = client.post("/repositories/analyze", json={
        "repository_path": f"{bench_root}/{letter}01/repo",
        "architecture_file": f"{bench_root}/{letter}01/repo/architecture/rules.yaml"}).json()
    return r["analysis_id"], next(f["id"] for f in r["findings"] if f["status"] == "violation")


# ---------------------------------------------------------------- evidence

def test_evidence_endpoint_returns_bundle_and_policy_without_llm(client, bench_root):
    aid, fid = analyze(client, bench_root, "C")
    r = client.get(f"/findings/{fid}/evidence", params={"analysis_id": aid})
    assert r.status_code == 200
    body = r.json()
    assert body["policy"]["escalate"] is True and body["policy"]["reasons"][0].startswith("I1")
    ev = body["evidence"]
    assert ev["rule"]["id"] and ev["structural"]["code_snippet"] and ev["adrs"] and ev["evolution"]["introducing_commit"]
    assert ev["adrs"][0]["text"] if "text" in ev["adrs"][0] else True  # text is optional in the summary form


def test_evidence_for_plain_violation_says_sufficient(client, bench_root):
    aid, fid = analyze(client, bench_root, "A")
    body = client.get(f"/findings/{fid}/evidence", params={"analysis_id": aid}).json()
    assert body["policy"]["escalate"] is False and body["policy"]["direct_verdict"] == "violation"


def test_evidence_rejects_conformant_and_unknown(client, bench_root):
    r = client.post("/repositories/analyze", json={
        "repository_path": f"{bench_root}/A01/repo", "architecture_file": f"{bench_root}/A01/repo/architecture/rules.yaml"}).json()
    ok = next(f["id"] for f in r["findings"] if f["status"] == "conformant")
    assert client.get(f"/findings/{ok}/evidence", params={"analysis_id": r["analysis_id"]}).status_code == 409
    assert client.get("/findings/F999/evidence", params={"analysis_id": r["analysis_id"]}).status_code == 404


def test_semantic_response_includes_evidence_for_the_ui(client, bench_root, monkeypatch):
    from analysis.semantic.llm_client import FunctionClient
    from api.routes import analyze as routes
    from experiments.mock_llm import mock_model
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(mock_model))
    aid, fid = analyze(client, bench_root, "C")
    body = client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid}).json()
    assert body["evidence"]["adrs"] and body["decision"]["llm_called"]


# ------------------------------------------------------------------ triage

def test_triage_counts_match_per_item_decisions(client, bench_root):
    aid, _ = analyze(client, bench_root, "F")  # superseded-only ADR -> resolved without LLM
    t = client.get(f"/analysis/{aid}/triage").json()
    counts = {k: t["summary"][k] for k in ("violations", "resolved_directly", "needs_semantic_review")}
    assert counts == {"violations": 1, "resolved_directly": 1, "needs_semantic_review": 0}
    assert t["summary"]["by_route"] == {"direct_structural": 1, "direct_code": 0, "escalate": 0} and t["summary"]["policy"] == "v1"
    item = t["items"][0]
    assert item["escalate"] is False and item["direct_verdict"] == "violation" and item["reasons"][0].startswith("I2")
    assert item["adr_count"] == 1 and item["active_adr_count"] == 0


def test_triage_flags_cases_needing_review(client, bench_root):
    aid, _ = analyze(client, bench_root, "J")
    t = client.get(f"/analysis/{aid}/triage").json()
    assert t["summary"]["needs_semantic_review"] == 1
    assert t["items"][0]["introduced_at"] and t["items"][0]["active_adr_count"] == 1


def test_triage_unknown_analysis_is_404(client):
    assert client.get("/analysis/A9999/triage").status_code == 404


# ------------------------------------------------------------- experiments

@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path))
    run = tmp_path / "run1"
    run.mkdir()
    (run / "metrics.csv").write_text("method,split,f1,llm_calls\nM1_static,test,0.8,0\nM5_evidence_guided,test,,12\n")
    (run / "metrics_by_scenario.csv").write_text("method,scenario,cases,correct,llm_calls,accuracy\nM1_static,A_plain,3,3,0,1.0\n")
    (run / "run_config.json").write_text(json.dumps({"provider": "mock", "model": "mock-keyword-rules", "created": "2026-11-09"}))
    (run / "predictions.csv").write_text(
        "method,case_id,scenario,split,source,target,truth,predicted_violation,escalated,llm_called,outcome_source,verdict,explanation,policy_reasons,input_tokens,output_tokens,latency_s,error\n"
        "M5,A01,A_plain,test,a.py,b.py,violation,True,False,False,direct,,,sufficient,0,0,0,\n"
        "M5,B01,B_adr,test,a.py,b.py,justified,True,True,True,llm,violation,wrong call,I1,100,10,1.5,\n"
        "M5,C01,C_adr,test,a.py,b.py,justified,False,True,True,llm,justified,ok,I1,100,10,1.5,\n"
        "M5,A01,A_plain,test,x.py,y.py,conformant,False,False,False,static,,,,0,0,0,\n")
    (tmp_path / "not-a-run").mkdir()  # no metrics.csv -> not listed
    return tmp_path


def test_lists_only_real_runs_and_marks_smoke_tests(client, results):
    runs = client.get("/experiments/runs").json()
    assert [r["name"] for r in runs] == ["run1"] and runs[0]["smoke_test"] is True


def test_run_metrics_use_null_for_nan(client, results):
    body = client.get("/experiments/runs/run1").json()
    assert body["smoke_test"] is True and body["by_scenario"][0]["accuracy"] == 1.0
    assert body["metrics"][1]["f1"] is None


def test_predictions_omit_conformant_and_support_filters(client, results):
    allrows = client.get("/experiments/runs/run1/predictions").json()
    assert allrows["total"] == 3 and all(r["truth"] != "conformant" for r in allrows["rows"])
    wrong = client.get("/experiments/runs/run1/predictions", params={"wrong_only": True}).json()
    assert [r["case_id"] for r in wrong["rows"]] == ["B01"] and wrong["rows"][0]["explanation"] == "wrong call"
    llm = client.get("/experiments/runs/run1/predictions", params={"llm_only": True}).json()
    assert llm["total"] == 2
    assert client.get("/experiments/runs/run1/predictions", params={"scenario": "A_plain"}).json()["total"] == 1


def test_path_traversal_and_unknown_runs_are_rejected(client, results):
    assert client.get("/experiments/runs/..%2F..%2Fetc").status_code in (400, 404)
    assert client.get("/experiments/runs/.hidden").status_code == 400
    assert client.get("/experiments/runs/nope").status_code == 404
    assert client.get("/experiments/runs/not-a-run").status_code == 404  # folder exists but has no metrics.csv
    assert client.get("/experiments/runs/not-a-run/predictions").status_code == 404


def test_missing_results_dir_lists_nothing(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "does-not-exist"))
    assert client.get("/experiments/runs").json() == []


def test_limit_is_enforced(client, results):
    assert client.get("/experiments/runs/run1/predictions", params={"limit": 0}).status_code == 422
    assert client.get("/experiments/runs/run1/predictions", params={"limit": 1}).json()["returned"] == 1


def test_run_payload_includes_paired_and_density_when_present_and_empty_lists_otherwise(client, results):
    body = client.get("/experiments/runs/run1").json()
    assert body["paired"] == [] and body["density"] == []  # this run has neither file
    (results / "run1" / "paired_comparisons.csv").write_text("a,b,split,metric,a_value,b_value,delta,ci_low,ci_high,n_cases\nM5,M3,test,f1,0.9,0.9,0.0,-0.05,0.05,28\n")
    (results / "run1" / "density_sweep.csv").write_text("method,split,adr_density,f1,llm_calls_per_case,calls_saved_vs_m3\nM5,test,0.5,0.9,0.4,0.2\nM3,test,0.5,0.9,0.5,\n")
    body = client.get("/experiments/runs/run1").json()
    assert body["paired"][0]["metric"] == "f1" and body["paired"][0]["ci_low"] == -0.05
    assert body["density"][1]["calls_saved_vs_m3"] is None  # blank cell -> null, not NaN


# ---------------------------------------------------------------- real-ADR checks (saved outputs, nothing run)

def _probe_summary(k=0, routed_structural=44):
    c = {"k": k, "n": 44, "rate": k / 44, "ci_low": 0.0, "ci_high": 0.0803}
    return {"n_primary": 44, "n_inactive_control": 5, "n_excluded_empty": 1, "band": "LOW", "thresholds": {"LOW": "0-2"},
            "model_raw": {"dangerous": c, "misleading": c, "failure": 0}, "model_with_attribution": {"dangerous": c},
            "routing": {"selected_by_matcher": {"k": 1, "n": 44, "ci_low": 0.004, "ci_high": 0.118},
                        "direct_structural": routed_structural, "direct_code": 0, "escalate": 44 - routed_structural},
            "pipeline": {"false_justified": c}}


def _write_checks(root, summary=None, case_rows=None):
    if summary is not None:
        d = root / "real_adrs_false_permission"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(json.dumps(summary))
    if case_rows is not None:
        d = root / "real_adrs_case_study"
        d.mkdir(parents=True)
        import pandas as pd
        pd.DataFrame(case_rows).to_csv(d / "results.csv", index=False)


def test_real_adr_checks_summarises_both_outputs(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path))
    rows = [{"case_id": "C01", "expected": "violation", "m6_pipeline": "violation", "m7": "justified"},
            {"case_id": "C02", "expected": "violation", "m6_pipeline": "violation", "m7": "violation"},
            {"case_id": "C03", "expected": "justified", "m6_pipeline": "violation", "m7": "justified"}]
    _write_checks(tmp_path, _probe_summary(), rows)
    body = client.get("/experiments/real-adr-checks").json()
    fp, cs = body["false_permission"], body["case_study"]
    assert fp["band"] == "LOW" and fp["dangerous"]["k"] == 0 and fp["dangerous"]["n"] == 44
    assert fp["routes"] == {"structural": 44, "code_reader": 0, "model": 0}
    assert cs["n"] == 3 and cs["n_violations"] == 2 and cs["m7_correct"] == 2 and cs["m6_pipeline_correct"] == 2
    assert cs["hidden_violations"] == 1  # C01: a violation called justified
    assert [c["m7_correct"] for c in cs["cases"]] == [False, True, True]


def test_real_adr_checks_missing_or_broken_files_give_null_not_errors(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path))
    assert client.get("/experiments/real-adr-checks").json() == {"false_permission": None, "case_study": None}
    d = tmp_path / "real_adrs_false_permission"
    d.mkdir()
    (d / "summary.json").write_text("{not json")
    c = tmp_path / "real_adrs_case_study"
    c.mkdir()
    (c / "results.csv").write_text("case_id\n")  # no rows and no needed columns
    r = client.get("/experiments/real-adr-checks")
    assert r.status_code == 200 and r.json() == {"false_permission": None, "case_study": None}


def test_real_adr_checks_does_not_collide_with_run_names(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path))
    assert client.get("/experiments/runs/real-adr-checks").status_code == 404
