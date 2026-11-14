"""Export real API responses as JSON fixtures for the frontend tests.

The frontend tests must run against the API's true shapes, not hand-written
guesses. tests/test_frontend_contract.py fails if the committed fixtures drift
from what the backend actually returns.

    python scripts/export_frontend_fixtures.py            # rewrite ../frontend/src/__fixtures__
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from fastapi.testclient import TestClient  # noqa: E402

from analysis.semantic.llm_client import FunctionClient  # noqa: E402
from api.routes import analyze as routes  # noqa: E402
from experiments.benchmark.generate import SCENARIOS, build_case  # noqa: E402
from experiments.mock_llm import mock_model  # noqa: E402
from main import app  # noqa: E402


def scrub(obj, root: str):
    """Replace machine-specific temp paths so fixtures are stable and portable."""
    return json.loads(json.dumps(obj).replace(root, "/data/bench"))


def export(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    root = tempfile.mkdtemp(prefix="fixtures-")
    for scenario in SCENARIOS:
        if scenario[0] in "ACF":
            build_case(root, f"{scenario[0]}01", scenario, 7)

    routes.get_llm_client = lambda: FunctionClient(mock_model, "stub-model")
    client = TestClient(app)
    out: dict = {}

    def analyze(letter):
        r = client.post("/repositories/analyze", json={
            "repository_path": f"{root}/{letter}01/repo",
            "architecture_file": f"{root}/{letter}01/repo/architecture/rules.yaml"}).json()
        fid = next(f["id"] for f in r["findings"] if f["status"] == "violation")
        return r, fid

    ac, fid_c = analyze("C")   # needs semantic review (grandfather clause, depends on date)
    aa, fid_a = analyze("A")   # evidence sufficient
    af, fid_f = analyze("F")   # superseded ADR only
    out["analysis_c"] = ac
    out["graph_c"] = client.get(f"/analysis/{ac['analysis_id']}/graph").json()
    out["finding_c"] = client.get(f"/analysis/{ac['analysis_id']}/findings/{fid_c}").json()
    out["evidence_c"] = client.get(f"/findings/{fid_c}/evidence", params={"analysis_id": ac["analysis_id"]}).json()
    out["triage_c"] = client.get(f"/analysis/{ac['analysis_id']}/triage").json()
    out["semantic_c"] = client.post(f"/findings/{fid_c}/semantic-analysis", params={"analysis_id": ac["analysis_id"]}).json()
    out["evidence_a"] = client.get(f"/findings/{fid_a}/evidence", params={"analysis_id": aa["analysis_id"]}).json()
    out["semantic_a"] = client.post(f"/findings/{fid_a}/semantic-analysis", params={"analysis_id": aa["analysis_id"]}).json()
    out["evidence_f"] = client.get(f"/findings/{fid_f}/evidence", params={"analysis_id": af["analysis_id"]}).json()

    # experiment payloads from a smoke run (stand-in model) over these three cases
    from experiments.run_experiments import main as run
    with open(os.path.join(root, "manifest.json"), "w") as fh:
        json.dump({"seed": 7, "cases": [
            {"case_id": f"{l}01", "scenario": s, "label": SCENARIOS[s][0], "split": "test", "path": f"{l}01"}
            for s in SCENARIOS for l in [s[0]] if l in "ACF"]}, fh)
    results = os.path.join(root, "results")
    run(["--benchmark", root, "--out", os.path.join(results, "smoke"), "--provider", "mock", "--seeds", "2", "--bootstrap", "20"])
    os.environ["RESULTS_DIR"] = results
    out["experiment_runs"] = client.get("/experiments/runs").json()
    out["experiment_run"] = client.get("/experiments/runs/smoke").json()
    out["experiment_predictions"] = client.get("/experiments/runs/smoke/predictions", params={"limit": 40}).json()

    for name, payload in out.items():
        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(scrub(payload, root), f, indent=1, sort_keys=True)
            f.write("\n")
    return out


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "frontend", "src", "__fixtures__")
    produced = export(os.path.abspath(target))
    print(f"wrote {len(produced)} fixtures to {os.path.abspath(target)}")
