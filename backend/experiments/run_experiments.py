"""Run the evaluation: methods M1-M5 + ablation over the generated benchmark.

Typical use (from backend/):

  python -m experiments.benchmark.generate --out ../datasets/benchmark/generated
  python -m experiments.run_experiments --dry-run                    # count calls/tokens, no LLM
  LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:7b-instruct \
  python -m experiments.run_experiments --splits dev,test --max-calls 500
  python -m experiments.run_experiments --provider mock              # pipeline smoke test ONLY

Every successful LLM response is cached on disk, so re-running (or resuming
after hitting --max-calls / a provider quota) costs nothing for finished work,
and the reported tokens/latency are those of the original call.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

from analysis.evolution.git_evolution import GitEvolutionAnalyzer
from analysis.semantic.llm_client import (
    CachingClient, FunctionClient, LLMClient, LLMResponse, OpenAICompatibleClient,
)
from analysis.semantic.prompts import PROMPT_VERSION
from experiments import metrics, pipeline
from experiments.mock_llm import mock_model

ALL_METHODS = ["static", "llm_only", "full_hybrid", "generic_selective", "evidence_guided", "no_history", "no_intent", "deterministic_adr", "extract_compute"]


class BudgetExceeded(RuntimeError):
    pass


class BudgetedClient(LLMClient):
    """Refuses to make more than `max_calls` REAL calls (cache hits are free
    because this wraps the real client, inside the cache)."""

    def __init__(self, inner: LLMClient, max_calls: int | None):
        self.inner, self.model, self.max_calls, self.calls = inner, inner.model, max_calls, 0

    def complete(self, system, prompt, *, temperature=0.0, max_tokens=600) -> LLMResponse:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExceeded(f"reached --max-calls={self.max_calls}")
        self.calls += 1
        return self.inner.complete(system, prompt, temperature=temperature, max_tokens=max_tokens)


def build_client(args) -> tuple[LLMClient, dict]:
    if args.provider in ("mock", "dry"):
        if args.provider == "dry":
            stub = lambda s, p: json.dumps({"verdict": "violation", "confidence": 0.5, "explanation": "dry run", "evidence_used": []})
            return FunctionClient(stub, "dry-run"), {"provider": "dry-run"}
        return FunctionClient(mock_model, "mock-keyword-rules"), {"provider": "mock"}
    base, model = os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_MODEL")
    if not base or not model:
        sys.exit("Set LLM_BASE_URL and LLM_MODEL (and LLM_API_KEY if needed), or use --provider mock / --dry-run.")
    real = OpenAICompatibleClient(base, model, os.environ.get("LLM_API_KEY"))
    budgeted = BudgetedClient(real, args.max_calls)
    # One cache shared by every phase (pilot, dev, full) so finished calls are never repeated.
    # It sits next to the output folders; entries are keyed by model + prompt, so models cannot collide.
    cache = args.cache or os.path.join(os.path.dirname(os.path.abspath(args.out)), "llm_cache.sqlite")
    return CachingClient(budgeted, cache), {"provider": "openai-compatible", "base_url": base, "model": model, "cache": cache}


def select_cases(entries: list[dict], limit: int | None) -> list[dict]:
    """Pick `limit` cases round-robin across scenarios, so a small pilot covers
    every kind of case instead of being all scenario A (manifest order)."""
    if not limit or limit >= len(entries):
        return entries
    by: dict[str, list[dict]] = {}
    for e in entries:
        by.setdefault(e["scenario"], []).append(e)
    picked: list[dict] = []
    while len(picked) < limit and any(by.values()):
        for scenario in list(by):
            if by[scenario] and len(picked) < limit:
                picked.append(by[scenario].pop(0))
    return picked


def build_paired_comparisons(preds: pd.DataFrame, splits: list[str], n_boot: int) -> pd.DataFrame:
    """M5 versus every other method present, per split, with paired bootstrap intervals."""
    methods = set(preds["method"].unique())
    m5 = "M5_evidence_guided"
    if m5 not in methods:
        return pd.DataFrame()
    others = [[m] for m in ("M1_static", "M2_llm_only", "M3_full_hybrid", "M6_deterministic_adr", "A1_no_history", "A2_no_intent") if m in methods]
    m4 = sorted(m for m in methods if m.startswith("M4_generic_selective_s"))
    if m4:
        others.append(m4)
    frames = [metrics.paired_bootstrap(preds, sp, [m5], b, n_boot) for sp in splits for b in others]
    m7 = "M7_extract_compute"
    if m7 in methods:  # M7 minus M5 is the clean test of extract-then-compute (same escalation policy)
        frames += [metrics.paired_bootstrap(preds, sp, [m7], [b], n_boot) for sp in splits
                   for b in (m5, "M3_full_hybrid", "M6_deterministic_adr", "M1_static") if b in methods]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fmt_table(df: pd.DataFrame, cols: list[str], floats: int = 3) -> str:
    def cell(v):
        if isinstance(v, float):
            return "-" if v != v else f"{v:.{floats}f}"
        return str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(cell(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", default="../datasets/benchmark/generated")
    ap.add_argument("--out", default="../results/run")
    ap.add_argument("--provider", choices=["env", "mock", "dry"], default="env")
    ap.add_argument("--dry-run", action="store_true", help="count LLM calls and estimated tokens; make no real calls")
    ap.add_argument("--splits", default="dev,test")
    ap.add_argument("--methods", default=",".join(ALL_METHODS))
    ap.add_argument("--seeds", type=int, default=5, help="random seeds for the generic-selective baseline")
    ap.add_argument("--max-calls", type=int, default=None, help="abort before exceeding this many REAL (uncached) calls")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--limit-cases", type=int, default=None)
    ap.add_argument("--price-in", type=float, default=None, help="USD per 1M input tokens")
    ap.add_argument("--price-out", type=float, default=None, help="USD per 1M output tokens")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--prompt-variant", choices=["full", "minimal"], default="full",
                    help="'minimal' drops all scenario-specific guidance from the system prompts (sensitivity analysis)")
    args = ap.parse_args(argv)
    if args.dry_run:
        args.provider = "dry"

    wanted = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = set(wanted) - set(ALL_METHODS)
    if unknown:
        sys.exit(f"unknown methods: {sorted(unknown)}; choose from {ALL_METHODS}")
    os.makedirs(args.out, exist_ok=True)

    with open(os.path.join(args.benchmark, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    splits = set(args.splits.split(","))
    entries = [c for c in manifest["cases"] if c["split"] in splits]
    entries = select_cases(entries, args.limit_cases)
    evo = GitEvolutionAnalyzer()
    t0 = time.perf_counter()
    contexts = [pipeline.CaseContext(args.benchmark, e, evo) for e in entries]
    print(f"Loaded {len(contexts)} cases ({sum(len(c.findings) for c in contexts)} governed edges) in {time.perf_counter() - t0:.1f}s")

    base_client, client_info = build_client(args)
    client = pipeline.TimedClient(base_client)
    rows: list[dict] = []

    try:
        if "static" in wanted:
            for c in contexts: rows += pipeline.run_static(c)
        if "llm_only" in wanted:
            for c in contexts: rows += pipeline.run_llm_only(c, client, variant=args.prompt_variant)
        if "deterministic_adr" in wanted:
            for c in contexts: rows += pipeline.run_deterministic_adr(c)
        if "full_hybrid" in wanted:
            for c in contexts: rows += pipeline.run_full_hybrid(c, client, variant=args.prompt_variant)
        m5_rows: list[dict] = []
        if "evidence_guided" in wanted or "generic_selective" in wanted:
            for c in contexts: m5_rows += pipeline.run_evidence_guided(c, client, variant=args.prompt_variant)
            if "evidence_guided" in wanted:
                rows += m5_rows
        if "extract_compute" in wanted:
            for c in contexts: rows += pipeline.run_extract_compute(c, client, variant=args.prompt_variant)
        if "no_history" in wanted:
            for c in contexts: rows += pipeline.run_evidence_guided(c, client, method="A1_no_history", use_history=False, variant=args.prompt_variant)
        if "no_intent" in wanted:
            for c in contexts: rows += pipeline.run_evidence_guided(c, client, method="A2_no_intent", use_intent=False, variant=args.prompt_variant)
        if "generic_selective" in wanted:
            k_by_split = pd.DataFrame(m5_rows).groupby("split")["escalated"].sum().astype(int).to_dict()
            for split, k in k_by_split.items():
                ctxs = [c for c in contexts if c.split == split]
                for seed in range(args.seeds):
                    rows += pipeline.run_generic_selective(ctxs, client, k, seed, f"M4_generic_selective_s{seed}", variant=args.prompt_variant)
    except BudgetExceeded as exc:
        pd.DataFrame(rows).to_csv(os.path.join(args.out, "predictions_partial.csv"), index=False)
        print(f"\nStopped: {exc}. Finished LLM responses are cached; re-run the same command to continue.", file=sys.stderr)
        return 2

    preds = pd.DataFrame(rows)
    if args.dry_run:
        calls = preds[preds["llm_called"].astype(bool)].groupby("method").agg(
            calls=("llm_called", "sum"), est_input_tokens=("input_tokens", "sum"), est_output_tokens=("output_tokens", "sum"))
        calls = calls.reset_index()
        m4 = calls[calls["method"].str.startswith("M4")]
        print("\nDRY RUN — LLM calls an actual run would make (before caching; M4 seeds overlap, so fewer real calls):\n")
        print(calls.to_string(index=False))
        print(f"\nTotal calls listed: {int(calls['calls'].sum())}  (M4 seeds = {len(m4)} runs)")
        longest = preds[preds["llm_called"].astype(bool)].sort_values("input_tokens").iloc[-1]
        print(f"Longest prompt: ~{int(longest['input_tokens'])} tokens ({longest['method']}, case {longest['case_id']}).")
        print("Your model's CONTEXT WINDOW must exceed this (with room for the reply). Ollama truncates silently otherwise;"
              " set a larger num_ctx (see docs/EXPERIMENTS.md).")
        print("Tokens are rough estimates (~4 chars/token), not a measurement.")
        return 0

    preds.to_csv(os.path.join(args.out, "predictions.csv"), index=False)
    summary = metrics.summarize(preds, args.price_in, args.price_out, args.bootstrap)
    m4 = metrics.average_over_seeds(summary, "M4_generic_selective_s", "M4_generic_selective_mean")
    summary.to_csv(os.path.join(args.out, "metrics_per_run.csv"), index=False)
    headline = pd.concat([summary[~summary["method"].str.startswith("M4_generic_selective_s")], m4], ignore_index=True)
    headline.to_csv(os.path.join(args.out, "metrics.csv"), index=False)
    scen = metrics.by_scenario(preds[~preds["method"].str.contains("M4_generic_selective_s[1-9]", regex=True)])
    scen.to_csv(os.path.join(args.out, "metrics_by_scenario.csv"), index=False)

    paired = build_paired_comparisons(preds, sorted(splits), args.bootstrap)
    paired.to_csv(os.path.join(args.out, "paired_comparisons.csv"), index=False)
    capture = metrics.escalation_capture(preds)
    capture.to_csv(os.path.join(args.out, "escalation_capture.csv"), index=False)
    density = pd.concat([metrics.density_sweep(preds, sp) for sp in sorted(splits)], ignore_index=True)
    density.to_csv(os.path.join(args.out, "density_sweep.csv"), index=False)

    config = {
        "created": datetime.now(timezone.utc).isoformat(), "benchmark": os.path.abspath(args.benchmark),
        "benchmark_seed": manifest.get("seed"), "benchmark_wording": manifest.get("wording", "primary"),
        "prompt_version": PROMPT_VERSION, "prompt_variant": args.prompt_variant, "m4_seeds": args.seeds,
        "splits": sorted(splits), "methods": wanted, **client_info,
    }
    with open(os.path.join(args.out, "run_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    banner = ""
    if args.provider == "mock":
        banner = ("> **SMOKE TEST WITH A KEYWORD STAND-IN, NOT A LANGUAGE MODEL.** These numbers only show that the "
                  "pipeline runs end to end. They are not results and must not be reported.\n\n")
    cols = ["method", "split", "precision", "recall", "f1", "f1_ci_low", "f1_ci_high", "false_positive_rate", "llm_calls", "input_tokens", "output_tokens", "llm_latency_s"]
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# Experiment summary\n\n{banner}Model: `{client_info.get('model', client_info['provider'])}`; prompt {PROMPT_VERSION} "
                f"(variant: {args.prompt_variant}); benchmark wording: {manifest.get('wording', 'primary')}\n\n")
        for split in sorted(splits):
            f.write(f"## Split: {split}\n\n{fmt_table(headline[headline['split'] == split], cols)}\n\n")
        if not paired.empty:
            keep = paired[paired["metric"].isin(["f1", "false_positive_rate", "llm_calls"])]
            f.write("## Paired comparison: a minus b (95% case-level bootstrap)\n\n"
                    "M5 against every other method; M7 against M5, M3, M6 and M1 (M7 minus M5 is the clean test of extract-then-compute).\n\n")
            f.write(fmt_table(keep, ["split", "a", "b", "metric", "a_value", "b_value", "delta", "ci_low", "ci_high"]) + "\n\n")
        if not capture.empty:
            f.write("## Escalation quality: which findings were sent to the LLM\n\n"
                    "A static false positive is a structural violation the benchmark labels justified. `capture_rate` is the share of "
                    "them escalated; `random_expected_capture` is what random choice at the same escalation rate would capture; "
                    "`calls_over_oracle` is how many more calls were made than an all-knowing policy needs.\n\n")
            f.write(fmt_table(capture, ["method", "split", "static_false_positives", "escalated", "captured_fp", "capture_rate",
                                         "random_expected_capture", "capture_lift", "escalation_yield", "calls_over_oracle"]) + "\n\n")
        shown = density[density["method"].isin(["M3_full_hybrid", "M5_evidence_guided"])] if not density.empty else density
        if not shown.empty:
            f.write("## If fewer dependencies had a decision record (re-weighted, not new data)\n\n")
            f.write(fmt_table(shown, ["split", "method", "adr_density", "f1", "llm_calls_per_case", "calls_saved_vs_m3"]) + "\n\n")
        f.write("## Decision accuracy on the targeted dependency, by scenario\n\n")
        f.write(fmt_table(scen.pivot(index="scenario", columns="method", values="accuracy").reset_index(), ["scenario", *[c for c in scen['method'].unique()]]) + "\n")
    try:
        make_frontier_plot(headline, os.path.join(args.out, "frontier.png"), banner != "")
    except Exception as exc:  # plotting must never lose the numeric results
        print(f"(plot skipped: {exc})")
    print(f"\nWrote results to {os.path.abspath(args.out)}")
    print(fmt_table(headline[headline["split"] == sorted(splits)[-1]], cols[:10]))
    return 0


def make_frontier_plot(headline: pd.DataFrame, path: str, mock: bool) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    split = "test" if "test" in set(headline["split"]) else headline["split"].iloc[0]
    d = headline[headline["split"] == split]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for _, r in d.iterrows():
        ax.scatter(r["llm_calls"], r["f1"], s=60)
        ax.annotate(r["method"].replace("_mean", "").split("_", 1)[0] + " " + r["method"].split("_", 1)[-1].replace("_mean", "")[:14], (r["llm_calls"], r["f1"]), textcoords="offset points", xytext=(5, 5), fontsize=8)
    ax.set_xlabel("LLM calls"); ax.set_ylabel("F1 (violation class)"); ax.set_ylim(0, 1.05)
    ax.set_title(f"Accuracy vs LLM cost ({split} split)" + ("  [SMOKE TEST - NOT RESULTS]" if mock else ""))
    ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
