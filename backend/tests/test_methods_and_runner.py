import json
import os

import pandas as pd
import pytest

from analysis.semantic.llm_client import FunctionClient
from experiments import pipeline
from experiments.mock_llm import mock_model
from experiments.run_experiments import BudgetedClient, BudgetExceeded, main


def timed(fn=mock_model):
    return pipeline.TimedClient(FunctionClient(fn))


def targeted(rows):
    return [r for r in rows if r["truth"] != "conformant"][0]


def test_static_predicts_every_structural_violation(bench_cases):
    for ctx in bench_cases.values():
        rows = pipeline.run_static(ctx)
        assert sum(r["predicted_violation"] for r in rows) == 1 and not any(r["llm_called"] for r in rows)


def test_full_hybrid_calls_llm_only_on_violations(bench_cases):
    ctx, client = bench_cases["B"], timed()
    rows = pipeline.run_full_hybrid(ctx, client)
    assert sum(r["llm_called"] for r in rows) == 1 == client.inner.calls
    assert targeted(rows)["predicted_violation"] is False  # mock reads the permanent-exception ADR


def test_llm_only_calls_on_every_edge_and_has_no_structural_fallback(bench_cases):
    ctx, client = bench_cases["A"], timed()
    rows = pipeline.run_llm_only(ctx, client)
    assert sum(r["llm_called"] for r in rows) == len(ctx.findings) == client.inner.calls
    failing = pipeline.run_llm_only(ctx, timed(lambda s, p: "garbage"))
    assert not any(r["predicted_violation"] for r in failing)  # failure => no detection...
    assert {r["outcome_source"] for r in failing} == {"llm_failed"}  # ...and it is visible


def test_evidence_guided_skips_llm_when_evidence_is_sufficient(bench_cases):
    ctx, client = bench_cases["A"], timed()
    rows = pipeline.run_evidence_guided(ctx, client)
    assert client.inner.calls == 0
    t = targeted(rows)
    assert t["outcome_source"] == "direct" and t["predicted_violation"] is True and "sufficient" in t["policy_reasons"]


def test_evidence_guided_escalates_and_overrides_structure_when_justified(bench_cases):
    ctx, client = bench_cases["C"], timed()
    t = targeted(pipeline.run_evidence_guided(ctx, client))
    assert t["escalated"] and t["llm_called"] and t["predicted_violation"] is False and t["truth"] == "justified"


def test_no_history_ablation_misses_the_commit_cited_adr(bench_cases):
    ctx, client = bench_cases["J"], timed()
    t = targeted(pipeline.run_evidence_guided(ctx, client, method="A1", use_history=False))
    assert t["escalated"] is False and t["predicted_violation"] is True and t["truth"] == "justified"


@pytest.mark.parametrize("bad,source", [
    ('{"verdict":"uncertain","confidence":0.1}', "fallback"),
    ("not json", "fallback"),
])
def test_uncertain_or_unparseable_falls_back_to_structure_visibly(bench_cases, bad, source):
    t = targeted(pipeline.run_full_hybrid(bench_cases["B"], timed(lambda s, p: bad)))
    assert t["predicted_violation"] is True and t["outcome_source"] == source


def test_provider_failure_is_flagged_and_does_not_flip_the_verdict(bench_cases):
    def boom(s, p):
        raise TimeoutError("slow")
    t = targeted(pipeline.run_full_hybrid(bench_cases["B"], timed(boom)))
    assert t["predicted_violation"] is True and "TimeoutError" in t["error"] and t["outcome_source"] == "fallback"


def test_generic_selective_escalates_exactly_k_and_is_seeded(bench_cases):
    ctxs = list(bench_cases.values())
    runs = {}
    for seed in (0, 0, 1):
        client = timed()
        rows = pipeline.run_generic_selective(ctxs, client, 4, seed, f"M4_s{seed}")
        assert sum(r["llm_called"] for r in rows) == 4 == client.inner.calls
        runs.setdefault(seed, []).append(sorted(r["case_id"] for r in rows if r["llm_called"]))
    assert runs[0][0] == runs[0][1]  # same seed -> same selection
    assert runs[0][0] != runs[1][0]  # different seed -> (here) a different selection


def test_generic_selective_cannot_exceed_available_violations(bench_cases):
    ctxs = list(bench_cases.values())
    rows = pipeline.run_generic_selective(ctxs, timed(), 999, 0, "M4")
    assert sum(r["llm_called"] for r in rows) == len(ctxs)


def test_compute_time_excludes_time_spent_inside_the_llm(bench_cases):
    import time
    def slow(s, p):
        time.sleep(0.05)
        return mock_model(s, p)
    t = targeted(pipeline.run_full_hybrid(bench_cases["B"], timed(slow)))
    assert t["compute_s"] < 0.05


def test_budget_guard_counts_only_real_calls_and_stops(tmp_path):
    from analysis.semantic.llm_client import CachingClient
    stub = FunctionClient(lambda s, p: "x")
    guarded = CachingClient(BudgetedClient(stub, max_calls=2), str(tmp_path / "c.sqlite"))
    guarded.complete("s", "a"); guarded.complete("s", "b")
    guarded.complete("s", "a")  # cache hit: free
    with pytest.raises(BudgetExceeded):
        guarded.complete("s", "c")


# ------------------------------------------------------------------ runner

@pytest.fixture(scope="module")
def mini_benchmark(tmp_path_factory, bench_root):
    manifest = {"seed": 7, "cases": [
        {"case_id": f"{l}01", "scenario": json.load(open(f"{bench_root}/{l}01/labels.json"))["scenario"],
         "label": json.load(open(f"{bench_root}/{l}01/labels.json"))["label"],
         "split": "dev" if i % 2 == 0 else "test", "path": f"{l}01"} for i, l in enumerate("ABCDEFGHJK")]}
    with open(f"{bench_root}/manifest.json", "w") as f:
        json.dump(manifest, f)
    return bench_root


def test_runner_smoke_writes_all_outputs_and_flags_mock(mini_benchmark, tmp_path):
    out = tmp_path / "res"
    rc = main(["--benchmark", mini_benchmark, "--out", str(out), "--provider", "mock", "--seeds", "2", "--bootstrap", "50"])
    assert rc == 0
    for name in ("predictions.csv", "metrics.csv", "metrics_by_scenario.csv", "metrics_per_run.csv", "summary.md", "run_config.json", "frontier.png"):
        assert (out / name).exists(), name
    assert "NOT a language model".lower() in (out / "summary.md").read_text().lower()
    m = pd.read_csv(out / "metrics.csv")
    assert {"M1_static", "M2_llm_only", "M3_full_hybrid", "M5_evidence_guided", "A1_no_history", "M4_generic_selective_mean"} <= set(m["method"])
    p = pd.read_csv(out / "predictions.csv")
    assert set(p["truth"]) == {"violation", "justified", "conformant"}
    assert "explanation" in p.columns
    assert p[p.llm_called.astype(bool)]["explanation"].fillna("").str.len().gt(0).all()  # kept for manual checking


def test_m4_budget_equals_m5_escalations_per_split(mini_benchmark, tmp_path):
    out = tmp_path / "res2"
    main(["--benchmark", mini_benchmark, "--out", str(out), "--provider", "mock", "--seeds", "3", "--bootstrap", "20"])
    p = pd.read_csv(out / "predictions.csv")
    for split in ("dev", "test"):
        m5 = p[(p.method == "M5_evidence_guided") & (p.split == split)]["escalated"].sum()
        for s in range(3):
            assert p[(p.method == f"M4_generic_selective_s{s}") & (p.split == split)]["llm_called"].sum() == min(m5, p[(p.method == "M1_static") & (p.split == split)]["structural_status"].eq("violation").sum())


def test_dry_run_makes_no_llm_calls_and_writes_no_results(mini_benchmark, tmp_path, capsys):
    out = tmp_path / "dry"
    assert main(["--benchmark", mini_benchmark, "--out", str(out), "--dry-run", "--seeds", "1"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not (out / "predictions.csv").exists()


def test_runner_requires_llm_config_for_real_provider(mini_benchmark, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(SystemExit):
        main(["--benchmark", mini_benchmark, "--out", str(tmp_path / "x"), "--provider", "env"])


def test_runner_rejects_unknown_method(mini_benchmark, tmp_path):
    with pytest.raises(SystemExit):
        main(["--benchmark", mini_benchmark, "--out", str(tmp_path / "x"), "--provider", "mock", "--methods", "bogus"])


def test_limit_cases_is_stratified_across_scenarios():
    from experiments.run_experiments import select_cases
    entries = [{"case_id": f"{s}{i}", "scenario": s} for s in ("A", "B", "C") for i in range(5)]
    picked = select_cases(entries, 6)
    assert [e["scenario"] for e in picked] == ["A", "B", "C", "A", "B", "C"]
    assert len({e["case_id"] for e in picked}) == 6
    assert select_cases(entries, None) == entries and select_cases(entries, 99) == entries


def test_default_cache_is_shared_between_output_folders(tmp_path, monkeypatch):
    """Pilot, dev and full runs write to different --out folders but must share one cache."""
    import experiments.run_experiments as rx
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    class A:  # minimal stand-in for parsed args
        provider, max_calls, cache = "env", None, None
        out = str(tmp_path / "results" / "pilot")
    c1, _ = rx.build_client(A)
    A.out = str(tmp_path / "results" / "full")
    c2, _ = rx.build_client(A)
    paths = {q.inner.model for q in (c1, c2)}
    assert (tmp_path / "results" / "llm_cache.sqlite").exists()
    assert not (tmp_path / "results" / "pilot" / "llm_cache.sqlite").exists()



def test_runner_writes_paired_comparisons_and_density_sweep(mini_benchmark, tmp_path):
    out = tmp_path / "res_paired"
    main(["--benchmark", mini_benchmark, "--out", str(out), "--provider", "mock", "--seeds", "2", "--bootstrap", "40"])
    paired = pd.read_csv(out / "paired_comparisons.csv")
    assert {"M1_static", "M2_llm_only", "M3_full_hybrid", "A1_no_history", "A2_no_intent"} <= set(paired["b"].str.split("+").str[0]) | set(paired["b"])
    assert {"f1", "llm_calls"} <= set(paired["metric"])
    assert set(paired["a"]) == {"M5_evidence_guided", "M7_extract_compute", "M8_gated", "M8_gated_attr"}  # M7 minus M5 isolates extract-then-compute; M8 is routing-only
    assert ((paired["a"] == "M7_extract_compute") & (paired["b"] == "M5_evidence_guided")).any()
    assert not ((paired["a"] == "M5_evidence_guided") & (paired["b"] == "M7_extract_compute")).any()  # no duplicate in the other direction
    density = pd.read_csv(out / "density_sweep.csv")
    assert {0.1, 1.0} <= set(density["adr_density"]) and "calls_saved_vs_m3" in density.columns
    text = (out / "summary.md").read_text()
    assert "Paired comparison" in text and "re-weighted, not new data" in text


def test_a2_is_a_runner_method_and_appears_in_metrics(mini_benchmark, tmp_path):
    out = tmp_path / "res_a2"
    main(["--benchmark", mini_benchmark, "--out", str(out), "--provider", "mock", "--methods", "static,no_intent", "--bootstrap", "20"])
    assert set(pd.read_csv(out / "metrics.csv")["method"]) == {"M1_static", "A2_no_intent"}


def test_prompt_variant_and_wording_are_recorded_in_the_run_config(mini_benchmark, tmp_path):
    out = tmp_path / "res_cfg"
    main(["--benchmark", mini_benchmark, "--out", str(out), "--provider", "mock", "--methods", "static,evidence_guided",
          "--prompt-variant", "minimal", "--bootstrap", "20"])
    cfg = json.load(open(out / "run_config.json"))
    assert cfg["prompt_variant"] == "minimal" and cfg["benchmark_wording"] == "primary"
    assert "variant: minimal" in (out / "summary.md").read_text()


def test_runner_rejects_an_unknown_prompt_variant(mini_benchmark, tmp_path):
    with pytest.raises(SystemExit):
        main(["--benchmark", mini_benchmark, "--out", str(tmp_path / "x"), "--provider", "mock", "--prompt-variant", "weird"])


@pytest.mark.parametrize("methods", ["static", "static,evidence_guided", "evidence_guided,no_history", "full_hybrid"])
def test_runner_completes_for_any_subset_of_methods(mini_benchmark, tmp_path, methods):
    """Regression: a subset without M3 used to crash while writing summary.md, AFTER the LLM
    calls had been made. Every subset must run to the end and write every output file."""
    out = tmp_path / "subset"
    assert main(["--benchmark", mini_benchmark, "--out", str(out), "--provider", "mock", "--methods", methods, "--bootstrap", "20"]) == 0
    for name in ("metrics.csv", "summary.md", "paired_comparisons.csv", "density_sweep.csv", "run_config.json"):
        assert (out / name).exists(), (methods, name)
