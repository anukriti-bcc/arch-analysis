"""A run whose paired_comparisons.csv is empty (e.g. an M2-only run) must load, not return 500."""
import shutil

from fastapi.testclient import TestClient

from main import app


def test_run_with_empty_optional_csv_loads(tmp_path, monkeypatch):
    run = tmp_path / "m2_only"
    run.mkdir()
    (run / "metrics.csv").write_text("method,split,f1\nM2_llm_only,test,0.18\n")
    (run / "paired_comparisons.csv").write_text("\n")  # one byte, no columns
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path))
    body = TestClient(app).get("/experiments/runs/m2_only")
    assert body.status_code == 200
    assert body.json()["paired"] == []
    assert body.json()["metrics"][0]["method"] == "M2_llm_only"
    shutil.rmtree(run)
