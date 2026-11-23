"""Read-only access to experiment outputs (results/<run>/...), so the UI can
show an evaluation run without anyone opening CSV files.

Nothing here can read outside RESULTS_DIR: run names are validated and the
resolved path is checked to stay inside it.
"""
from __future__ import annotations

import json
import os
import re

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/experiments")

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PREDICTION_COLUMNS = [
    "method", "case_id", "scenario", "split", "source", "target", "truth", "predicted_violation",
    "escalated", "llm_called", "outcome_source", "verdict", "explanation", "policy_reasons",
    "input_tokens", "output_tokens", "latency_s", "error",
]


def results_dir() -> str:
    return os.path.abspath(os.environ.get("RESULTS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "..", "results")))


def _run_dir(name: str) -> str:
    if not _NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid run name.")
    root = results_dir()
    path = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([root, path]) != root or not os.path.isdir(path):
        raise HTTPException(status_code=404, detail=f"Run '{name}' not found.")
    return path


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))  # NaN -> null


def _config(path: str) -> dict:
    cfg = os.path.join(path, "run_config.json")
    if not os.path.isfile(cfg):
        return {}
    with open(cfg, encoding="utf-8") as f:
        return json.load(f)


def _count(d: dict | None) -> dict | None:
    """{k, n, ci_low, ci_high} from a probe summary entry, or None if it is not there."""
    if not isinstance(d, dict) or "k" not in d or "n" not in d:
        return None
    return {"k": d["k"], "n": d["n"], "ci_low": d.get("ci_low"), "ci_high": d.get("ci_high")}


def _false_permission(root: str) -> dict | None:
    file = os.path.join(root, "real_adrs_false_permission", "summary.json")
    if not os.path.isfile(file):
        return None
    try:
        with open(file, encoding="utf-8") as f:
            s = json.load(f)
        raw, attr, routing, pipe = s["model_raw"], s["model_with_attribution"], s["routing"], s["pipeline"]
        return {
            "band": s.get("band"), "thresholds": s.get("thresholds"),
            "n_primary": s["n_primary"], "n_inactive_control": s.get("n_inactive_control"),
            "n_excluded_empty": s.get("n_excluded_empty"),
            "dangerous": _count(raw.get("dangerous")), "misleading": _count(raw.get("misleading")),
            "failures": raw.get("failure"), "dangerous_after_attribution": _count(attr.get("dangerous")),
            "selected_by_matcher": _count(routing.get("selected_by_matcher")),
            "routes": {"structural": routing.get("direct_structural"), "code_reader": routing.get("direct_code"), "model": routing.get("escalate")},
            "pipeline_false_justified": _count(pipe.get("false_justified")),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _case_study(root: str) -> dict | None:
    file = os.path.join(root, "real_adrs_case_study", "results.csv")
    if not os.path.isfile(file):
        return None
    try:
        df = pd.read_csv(file)
        n = len(df)
        if n == 0:
            return None
        truth = df["expected"].astype(str)
        m7 = df["m7"].astype(str)
        return {
            "n": n, "n_violations": int((truth == "violation").sum()),
            "m7_correct": int((m7 == truth).sum()),
            "m6_pipeline_correct": int((df["m6_pipeline"].astype(str) == truth).sum()),
            # a violation the model called "justified": the dangerous direction
            "hidden_violations": int(((truth == "violation") & (m7 == "justified")).sum()),
            "cases": [{"case_id": r["case_id"], "expected": r["expected"], "m7": r["m7"], "m7_correct": bool(r["m7"] == r["expected"])} for r in df.to_dict("records")],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


@router.get("/real-adr-checks")
def real_adr_checks() -> dict:
    """The two checks of the model on real ADR text (summaries of saved outputs; nothing is run). Either part is null if its files are absent."""
    root = results_dir()
    return {"false_permission": _false_permission(root), "case_study": _case_study(root)}


@router.get("/runs")
def list_runs() -> list[dict]:
    root = results_dir()
    if not os.path.isdir(root):
        return []
    runs = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not (_NAME.match(name) and os.path.isfile(os.path.join(path, "metrics.csv"))):
            continue
        cfg = _config(path)
        runs.append({"name": name, "created": cfg.get("created"), "provider": cfg.get("provider"),
                     "model": cfg.get("model"), "smoke_test": cfg.get("provider") == "mock"})
    return runs


@router.get("/runs/{name}")
def get_run(name: str) -> dict:
    path = _run_dir(name)
    cfg = _config(path)
    metrics_file = os.path.join(path, "metrics.csv")
    if not os.path.isfile(metrics_file):
        raise HTTPException(status_code=404, detail="This run has no metrics.csv.")
    metrics = pd.read_csv(metrics_file)
    def optional(filename: str) -> list[dict]:
        file = os.path.join(path, filename)
        return _records(pd.read_csv(file)) if os.path.isfile(file) else []

    return {"name": name, "config": cfg, "smoke_test": cfg.get("provider") == "mock",
            "metrics": _records(metrics), "by_scenario": optional("metrics_by_scenario.csv"),
            "paired": optional("paired_comparisons.csv"), "density": optional("density_sweep.csv")}


@router.get("/runs/{name}/predictions")
def get_predictions(
    name: str,
    method: str | None = None,
    scenario: str | None = None,
    wrong_only: bool = False,
    llm_only: bool = False,
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Per-edge predictions, for manually checking what a method decided and why.
    Conformant edges are omitted (they are not the interesting decisions)."""
    path = _run_dir(name)
    file = os.path.join(path, "predictions.csv")
    if not os.path.isfile(file):
        raise HTTPException(status_code=404, detail="This run has no predictions.csv.")
    df = pd.read_csv(file)
    df = df[df["truth"] != "conformant"]
    if method:
        df = df[df["method"] == method]
    if scenario:
        df = df[df["scenario"] == scenario]
    if wrong_only:
        df = df[df["predicted_violation"].astype(bool) != (df["truth"] == "violation")]
    if llm_only:
        df = df[df["llm_called"].astype(bool)]
    total = len(df)
    cols = [c for c in PREDICTION_COLUMNS if c in df.columns]
    return {"total": total, "returned": min(total, limit), "rows": _records(df[cols].head(limit))}
