"""The product applies the stance-attribution check (M8_gated_attr) by default; ATTRIBUTION_CHECK=off runs plain M8.

The mixed case is the one measured in tests/test_attribution.py: one decision permits ANOTHER module and requires the flagged one to keep to
the rule. The model below makes exactly the measured error (it reports the other module's permission as this module's). Without the check the
product would call the real violation justified; with it, code rejects the reading.
"""
import json

import pytest
from fastapi.testclient import TestClient

from analysis.semantic.llm_client import FunctionClient
from api.routes import analyze as routes
from experiments.benchmark.generate import build_case
from main import app


@pytest.fixture(scope="module")
def mixed_root(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("api_mixed"))
    build_case(root, "M01", "M_adr_mixed_prohibits_target", 21, wording="hard")
    return root


@pytest.fixture
def client():
    return TestClient(app)


def lazy_model(system, prompt):
    return json.dumps({"adr_id": "ADR-011", "decision": "permits", "covers_this_dependency": "yes", "limit": "none",
                       "limit_date": None, "explanation": "permits"})


def resolve_mixed(client, root, monkeypatch):
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(lazy_model, "lazy-model"))
    r = client.post("/repositories/analyze", json={
        "repository_path": f"{root}/M01/repo", "architecture_file": f"{root}/M01/repo/architecture/rules.yaml"})
    assert r.status_code == 200
    body = r.json()
    fid = next(f["id"] for f in body["findings"] if f["status"] == "violation")
    return client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": body["analysis_id"], "force": True})


def test_by_default_a_permission_written_for_another_module_is_rejected(client, mixed_root, monkeypatch):
    monkeypatch.delenv("ATTRIBUTION_CHECK", raising=False)
    r = resolve_mixed(client, mixed_root, monkeypatch)
    assert r.status_code == 200
    d, x = r.json()["decision"], r.json()["semantic_analysis"]["extraction"]
    assert d["final_verdict"] == "violation" and d["resolution"] == "extract_compute"
    assert x["decision"] == "does_not_address" and x["attribution"].startswith("rejected")


def test_switched_off_the_product_shows_the_measured_weakness(client, mixed_root, monkeypatch):
    monkeypatch.setenv("ATTRIBUTION_CHECK", "off")
    r = resolve_mixed(client, mixed_root, monkeypatch)
    assert r.status_code == 200
    d, x = r.json()["decision"], r.json()["semantic_analysis"]["extraction"]
    assert d["final_verdict"] == "justified"  # the real violation is hidden: this is what the check exists to prevent
    assert "attribution" not in x


def test_a_bad_setting_is_a_server_error_not_a_silent_default(client, mixed_root, monkeypatch):
    monkeypatch.setenv("ATTRIBUTION_CHECK", "maybe")
    r = resolve_mixed(client, mixed_root, monkeypatch)
    assert r.status_code == 500 and "ATTRIBUTION_CHECK" in r.json()["detail"]


@pytest.mark.parametrize("value, shown", [(None, "on"), ("on", "on"), ("OFF", "off"), ("0", "off")])
def test_health_reports_the_setting(client, monkeypatch, value, shown):
    if value is None:
        monkeypatch.delenv("ATTRIBUTION_CHECK", raising=False)
    else:
        monkeypatch.setenv("ATTRIBUTION_CHECK", value)
    assert client.get("/health").json()["attribution_check"] == shown
