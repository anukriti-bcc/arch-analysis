"""Pooling several benchmark seeds into one confirmation analysis."""
import json

import pandas as pd
import pytest

from experiments.combine_runs import consistency_problems, main as combine
from experiments.run_experiments import main as run
from tests.test_methods_and_runner import mini_benchmark  # noqa: F401  (fixture)


@pytest.fixture()
def two_runs(mini_benchmark, tmp_path):  # noqa: F811
    outs = []
    for tag in ("s1", "s2"):
        out = tmp_path / tag
        run(["--benchmark", mini_benchmark, "--out", str(out), "--provider", "mock", "--seeds", "2", "--bootstrap", "20",
             "--methods", "static,deterministic_adr,full_hybrid,evidence_guided,extract_compute"])
        outs.append(str(out))
    return outs


def test_pooling_makes_one_confirm_split_with_unique_cases_and_paired_m7_vs_m5(two_runs, tmp_path):
    out = tmp_path / "pooled"
    assert combine(["--runs", *two_runs, "--out", str(out), "--bootstrap", "30"]) == 0
    p = pd.read_csv(out / "predictions.csv")
    assert set(p["split"]) == {"confirm"} and p["case_id"].str.contains(":").all()
    assert p["case_id"].nunique() == 2 * 10  # the same case ids in two runs stay distinct
    paired = pd.read_csv(out / "paired_comparisons.csv")
    assert ((paired["a"] == "M7_extract_compute") & (paired["b"] == "M5_evidence_guided")).any()
    text = (out / "summary.md").read_text()
    assert "Pooled confirmation run" in text and "NOT A LANGUAGE MODEL" in text  # mock runs stay labelled when pooled
    assert {"M7_extract_compute", "M5_evidence_guided"} <= set(pd.read_csv(out / "escalation_capture.csv")["method"])


def test_refuses_to_pool_runs_that_are_not_comparable(two_runs, tmp_path):
    cfg = json.load(open(f"{two_runs[1]}/run_config.json"))
    cfg["model"] = "a-different-model"
    json.dump(cfg, open(f"{two_runs[1]}/run_config.json", "w"))
    with pytest.raises(SystemExit) as e:
        combine(["--runs", *two_runs, "--out", str(tmp_path / "x")])
    assert "model" in str(e.value)
    assert combine(["--runs", *two_runs, "--out", str(tmp_path / "y"), "--bootstrap", "20", "--allow-mismatch"]) == 0
    assert "Warning" in (tmp_path / "y" / "summary.md").read_text()


def test_consistency_check_flags_different_method_sets():
    assert consistency_problems({"a": {"M1", "M5"}, "b": {"M1"}}, [])
    assert not consistency_problems({"a": {"M1"}, "b": {"M1"}}, [{"model": "m"}, {"model": "m"}])
