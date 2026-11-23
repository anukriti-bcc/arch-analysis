import math

import numpy as np
import pandas as pd
import pytest

from experiments import metrics


def frame(rows):
    cols = dict(method="M", case_id="c1", scenario="S", split="test", structural_status="violation",
                escalated=False, llm_called=False, outcome_source="static", verdict=None, error=None,
                input_tokens=0, output_tokens=0, latency_s=0.0, compute_s=0.0, tokens_estimated=None)
    return pd.DataFrame([{**cols, **r} for r in rows])


def test_confusion_and_prf_hand_computed():
    # truth/pred: TP, TP, FP, FN, TN, TN, TN
    df = frame([
        dict(truth="violation", predicted_violation=True), dict(truth="violation", predicted_violation=True),
        dict(truth="justified", predicted_violation=True), dict(truth="violation", predicted_violation=False),
        dict(truth="justified", predicted_violation=False), dict(truth="conformant", predicted_violation=False),
        dict(truth="conformant", predicted_violation=False),
    ])
    c = metrics.confusion(df)
    assert c == {"tp": 2, "fp": 1, "fn": 1, "tn": 3}
    m = metrics.prf(c)
    assert m["precision"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3) and m["false_positive_rate"] == pytest.approx(1 / 4)
    assert m["accuracy"] == pytest.approx(5 / 7)


def test_justified_reported_as_violation_is_a_false_positive():
    df = frame([dict(truth="justified", predicted_violation=True)])
    assert metrics.confusion(df)["fp"] == 1


def test_degenerate_cases_give_nan_not_exceptions():
    m = metrics.prf({"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    assert all(math.isnan(v) for v in m.values())
    m = metrics.prf({"tp": 0, "fp": 3, "fn": 0, "tn": 0})
    assert m["precision"] == 0 and math.isnan(m["recall"]) and math.isnan(m["f1"])


def test_bootstrap_is_seeded_and_contains_point_estimate():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(30):
        truth = "violation" if i % 3 else "justified"
        pred = truth == "violation" if rng.random() > 0.15 else truth != "violation"
        rows.append(dict(case_id=f"c{i}", truth=truth, predicted_violation=bool(pred)))
    df = frame(rows)
    lo, hi = metrics.bootstrap_f1(df, 300, seed=1)
    assert (lo, hi) == metrics.bootstrap_f1(df, 300, seed=1)
    assert lo <= metrics.prf(metrics.confusion(df))["f1"] <= hi


def test_bootstrap_with_single_case_is_nan():
    lo, hi = metrics.bootstrap_f1(frame([dict(truth="violation", predicted_violation=True)]), 50)
    assert math.isnan(lo) and math.isnan(hi)


def test_efficiency_counts_calls_tokens_failures_and_cost():
    df = frame([
        dict(truth="violation", predicted_violation=True, escalated=True, llm_called=True, input_tokens=1000, output_tokens=100, latency_s=2.0, outcome_source="llm", verdict="violation", tokens_estimated=False),
        dict(truth="violation", predicted_violation=True, escalated=True, llm_called=True, input_tokens=500, output_tokens=50, latency_s=1.0, outcome_source="fallback", verdict="uncertain", tokens_estimated=False),
        dict(truth="violation", predicted_violation=True, escalated=True, llm_called=True, outcome_source="fallback", error="HTTP 503"),
        dict(truth="violation", predicted_violation=True),
    ])
    e = metrics.efficiency(df, price_in=1.0, price_out=2.0)
    assert e["llm_calls"] == 3 and e["input_tokens"] == 1500 and e["output_tokens"] == 150
    assert e["llm_latency_s"] == 3.0 and e["fallbacks"] == 2 and e["llm_failures"] == 1 and e["uncertain_verdicts"] == 1
    assert e["escalation_rate_of_violations"] == pytest.approx(3 / 4)
    assert e["cost_usd"] == pytest.approx(1500 / 1e6 * 1 + 150 / 1e6 * 2, abs=1e-4)


def test_cost_is_nan_without_prices():
    assert math.isnan(metrics.efficiency(frame([dict(truth="violation", predicted_violation=True)]), None, None)["cost_usd"])


def test_by_scenario_ignores_conformant_edges():
    df = frame([
        dict(scenario="B", truth="justified", predicted_violation=False),
        dict(scenario="B", truth="justified", predicted_violation=True),
        dict(scenario="B", truth="conformant", predicted_violation=True),  # must be ignored
    ])
    r = metrics.by_scenario(df).iloc[0]
    assert (r["cases"], r["correct"], r["accuracy"]) == (2, 1, 0.5)


def test_average_over_seeds_reports_mean_and_sd():
    runs = [dict(method=f"M4_generic_selective_s{i}", split="test", precision=p, recall=1.0, f1=p, false_positive_rate=0.1, llm_calls=10) for i, p in enumerate([0.5, 0.7])]
    out = metrics.average_over_seeds(pd.DataFrame(runs), "M4_generic_selective_s", "M4_mean").iloc[0]
    assert out["f1"] == pytest.approx(0.6) and out["f1_sd"] == pytest.approx(np.std([0.5, 0.7], ddof=1)) and out["seeds"] == 2


def test_metrics_agree_with_scikit_learn_on_random_data():
    """scikit-learn serves as the reference for the metrics. Our own implementation (which
    handles degenerate cases explicitly) must agree with it wherever sklearn is defined."""
    sk = pytest.importorskip("sklearn.metrics")
    rng = np.random.default_rng(42)
    for trial in range(25):
        n = int(rng.integers(20, 80))
        truth = rng.choice(["violation", "justified", "conformant"], size=n, p=[0.5, 0.25, 0.25])
        pred = rng.random(n) < 0.55
        df = frame([dict(case_id=f"c{i}", truth=t, predicted_violation=bool(p)) for i, (t, p) in enumerate(zip(truth, pred))])
        y_true = truth == "violation"
        ours = metrics.prf(metrics.confusion(df))
        assert ours["precision"] == pytest.approx(sk.precision_score(y_true, pred, zero_division=0))
        assert ours["recall"] == pytest.approx(sk.recall_score(y_true, pred, zero_division=0))
        assert ours["f1"] == pytest.approx(sk.f1_score(y_true, pred, zero_division=0))
        assert ours["accuracy"] == pytest.approx(sk.accuracy_score(y_true, pred))
        tn, fp, fn, tp = sk.confusion_matrix(y_true, pred, labels=[False, True]).ravel()
        assert metrics.confusion(df) == {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)}


# ------------------------------------------------------- paired bootstrap / density sweep

def prow(method, case, scenario, truth, pred, called=False, split="test"):
    return dict(method=method, case_id=case, scenario=scenario, split=split, truth=truth,
                predicted_violation=pred, llm_called=called)


def two_method_frame(n_cases=20, b_error_every=4, seed=0):
    """A is perfect; B gets every `b_error_every`-th case wrong (None = never). A uses fewer calls."""
    rows = []
    for i in range(n_cases):
        scen = "A_plain" if i % 2 == 0 else "B_adr"
        truth = "violation" if i % 3 else "justified"
        pred = truth == "violation"
        rows.append(prow("A", f"c{i}", scen, truth, pred, called=(i % 2 == 1)))
        rows.append(prow("B", f"c{i}", scen, truth, (not pred) if (b_error_every and (i + 1) % b_error_every == 0) else pred, called=True))
    return pd.DataFrame(rows)


def test_paired_bootstrap_detects_a_real_difference_and_is_seeded():
    df = two_method_frame()
    out = metrics.paired_bootstrap(df, "test", ["A"], ["B"], n_boot=500, seed=3)
    assert metrics.paired_bootstrap(df, "test", ["A"], ["B"], n_boot=500, seed=3).equals(out)
    f1 = out[out.metric == "f1"].iloc[0]
    assert f1.delta > 0 and f1.ci_low > 0 and f1.n_cases == 20
    calls = out[out.metric == "llm_calls"].iloc[0]
    assert calls.delta < 0 and calls.ci_high < 0  # A makes fewer calls on the same cases


def test_paired_bootstrap_point_estimate_equals_difference_of_plain_metrics():
    df = two_method_frame()
    out = metrics.paired_bootstrap(df, "test", ["A"], ["B"], n_boot=50).set_index("metric")
    a = metrics.prf(metrics.confusion(df[df.method == "A"]))
    b = metrics.prf(metrics.confusion(df[df.method == "B"]))
    assert out.loc["f1", "delta"] == pytest.approx(a["f1"] - b["f1"])
    assert out.loc["precision", "a_value"] == pytest.approx(a["precision"])
    assert out.loc["false_positive_rate", "b_value"] == pytest.approx(b["false_positive_rate"])


def test_identical_methods_have_a_zero_delta_and_zero_width_interval():
    df = two_method_frame(b_error_every=None)
    f1 = metrics.paired_bootstrap(df, "test", ["A"], ["B"], n_boot=100).query("metric == 'f1'").iloc[0]
    assert f1.delta == 0 and f1.ci_low == 0 and f1.ci_high == 0


def test_paired_bootstrap_averages_a_group_of_seeded_methods_metric_by_metric():
    df = two_method_frame()
    seeds = pd.concat([df[df.method == "B"].assign(method=f"S{i}") for i in range(3)])
    out = metrics.paired_bootstrap(pd.concat([df[df.method == "A"], seeds]), "test", ["A"], ["S0", "S1", "S2"], n_boot=50)
    assert out.query("metric == 'f1'").iloc[0].b_value == pytest.approx(
        metrics.prf(metrics.confusion(df[df.method == "B"]))["f1"])


def test_paired_bootstrap_on_an_empty_split_is_empty():
    assert metrics.paired_bootstrap(two_method_frame(), "dev", ["A"], ["B"]).empty


def test_density_sweep_at_the_observed_density_reproduces_the_plain_metrics():
    df = two_method_frame(n_cases=20)
    observed = 10 / 20  # odd-indexed cases carry an ADR scenario
    out = metrics.density_sweep(df, "test", densities=(observed,)).set_index("method")
    for m in "AB":
        plain = metrics.prf(metrics.confusion(df[df.method == m]))
        assert out.loc[m, "f1"] == pytest.approx(plain["f1"])
        assert out.loc[m, "llm_calls_per_case"] == pytest.approx(df[df.method == m].llm_called.sum() / 20)


def test_density_sweep_moves_llm_calls_with_the_share_of_adr_cases():
    df = two_method_frame(n_cases=20)
    out = metrics.density_sweep(df, "test", densities=(0.1, 0.5, 1.0))
    a = out[out.method == "A"].set_index("adr_density")["llm_calls_per_case"]
    assert a[0.1] == pytest.approx(0.1) and a[1.0] == pytest.approx(1.0)  # A only calls where an ADR exists
    b = out[out.method == "B"].set_index("adr_density")["llm_calls_per_case"]
    assert b.tolist() == pytest.approx([1.0, 1.0, 1.0])  # B calls everywhere, whatever the density


def test_density_sweep_reports_savings_against_the_full_hybrid_when_present():
    df = two_method_frame()
    df["method"] = df["method"].replace({"A": "M5_evidence_guided", "B": "M3_full_hybrid"})
    out = metrics.density_sweep(df, "test", densities=(0.25, 1.0))
    m5 = out[out.method == "M5_evidence_guided"].set_index("adr_density")["calls_saved_vs_m3"]
    assert m5[0.25] == pytest.approx(0.75) and m5[1.0] == pytest.approx(0.0)


def test_density_sweep_needs_both_kinds_of_case():
    only_adr = pd.DataFrame([prow("M", f"c{i}", "B_adr", "violation", True) for i in range(4)])
    assert metrics.density_sweep(only_adr, "test").empty


def test_density_sweep_groups_m4_seeds_into_one_mean_row():
    df = two_method_frame()
    seeds = pd.concat([df[df.method == "B"].assign(method=f"M4_generic_selective_s{i}") for i in range(3)])
    out = metrics.density_sweep(seeds, "test", densities=(0.5,))
    assert list(out.method) == ["M4_generic_selective_mean"]
