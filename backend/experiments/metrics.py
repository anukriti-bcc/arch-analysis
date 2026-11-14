"""Metrics for the evaluation (Brief section 12).

Positive class = a *genuine* violation. A structural violation that the
benchmark labels 'justified' counts as a false positive when reported as a
violation. All metrics are computed per (method, split); intervals come from a
cluster bootstrap over cases (a case, not a single edge, is the unit that was
sampled, so edges of one case are resampled together).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd


def confusion(df: pd.DataFrame) -> dict:
    actual = df["truth"] == "violation"
    pred = df["predicted_violation"].astype(bool)
    tp = int((actual & pred).sum()); fp = int((~actual & pred).sum())
    fn = int((actual & ~pred).sum()); tn = int((~actual & ~pred).sum())
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def prf(c: dict) -> dict:
    p = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else float("nan")
    r = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else float("nan")
    f1 = 2 * p * r / (p + r) if (p == p and r == r and (p + r) > 0) else float("nan")
    fpr = c["fp"] / (c["fp"] + c["tn"]) if (c["fp"] + c["tn"]) else float("nan")
    n = sum(c.values())
    return {"precision": p, "recall": r, "f1": f1, "false_positive_rate": fpr,
            "accuracy": (c["tp"] + c["tn"]) / n if n else float("nan")}


def bootstrap_f1(df: pd.DataFrame, n_boot: int = 1000, seed: int = 0) -> tuple[float, float]:
    cases = df["case_id"].unique()
    if len(cases) < 2:
        return float("nan"), float("nan")
    groups = {c: g for c, g in df.groupby("case_id")}
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(cases, size=len(cases), replace=True)
        f1 = prf(confusion(pd.concat([groups[c] for c in pick])))["f1"]
        if f1 == f1:
            vals.append(f1)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))) if vals else (float("nan"), float("nan"))


def efficiency(df: pd.DataFrame, price_in: float | None, price_out: float | None) -> dict:
    called = df["llm_called"].astype(bool)
    n_viol = int((df["structural_status"] == "violation").sum())
    esc = int(df["escalated"].astype(bool).sum())
    tin, tout = int(df["input_tokens"].sum()), int(df["output_tokens"].sum())
    llm_lat = float(df["latency_s"].sum())
    out = {
        "llm_calls": int(called.sum()),
        "escalation_rate_of_violations": (esc / n_viol) if (n_viol and df["method"].iloc[0] not in ("M2_llm_only",)) else float("nan"),
        "input_tokens": tin, "output_tokens": tout,
        "llm_latency_s": round(llm_lat, 3),
        "compute_s": round(float(df["compute_s"].sum()), 3),
        "total_modeled_s": round(llm_lat + float(df["compute_s"].sum()), 3),
        "fallbacks": int((df["outcome_source"] == "fallback").sum()),
        "llm_failures": int((df["outcome_source"] == "llm_failed").sum() + (called & df["error"].notna()).sum()),
        "uncertain_verdicts": int((df["verdict"] == "uncertain").sum()),
        "tokens_estimated_calls": int((df["tokens_estimated"] == True).sum()),  # noqa: E712
    }
    out["cost_usd"] = (
        round(tin / 1e6 * price_in + tout / 1e6 * price_out, 4) if price_in is not None and price_out is not None else float("nan")
    )
    return out


def summarize(preds: pd.DataFrame, price_in=None, price_out=None, n_boot=1000) -> pd.DataFrame:
    rows = []
    for (method, split), g in preds.groupby(["method", "split"]):
        c = confusion(g)
        lo, hi = bootstrap_f1(g, n_boot)
        rows.append({"method": method, "split": split, "n_edges": len(g), "n_cases": g["case_id"].nunique(),
                     **c, **prf(c), "f1_ci_low": lo, "f1_ci_high": hi, **efficiency(g, price_in, price_out)})
    return pd.DataFrame(rows)


def by_scenario(preds: pd.DataFrame) -> pd.DataFrame:
    """Accuracy of the decision on the *targeted* edge of each case, per
    scenario — shows where each evidence source matters."""
    target = preds[preds["truth"] != "conformant"].copy()
    target["correct"] = (target["predicted_violation"].astype(bool)) == (target["truth"] == "violation")
    return (target.groupby(["method", "scenario"])
            .agg(cases=("correct", "size"), correct=("correct", "sum"), llm_calls=("llm_called", "sum"))
            .reset_index().assign(accuracy=lambda d: d["correct"] / d["cases"]))


def average_over_seeds(summary: pd.DataFrame, prefix: str, new_name: str) -> pd.DataFrame:
    """Collapse repeated runs of a randomised method (M4 seeds) into mean and sd."""
    sub = summary[summary["method"].str.startswith(prefix)]
    if sub.empty:
        return sub
    num = sub.select_dtypes("number").columns
    rows = []
    for split, g in sub.groupby("split"):
        mean, sd = g[num].mean(), g[num].std(ddof=1) if len(g) > 1 else g[num].std(ddof=0) * 0
        row = {"method": new_name, "split": split, "seeds": len(g), **mean.to_dict()}
        for col in ("precision", "recall", "f1", "false_positive_rate", "llm_calls"):
            row[f"{col}_sd"] = float(sd[col])
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Paired comparison and ADR-density analysis
# --------------------------------------------------------------------------------------

_COUNT_COLS = ["tp", "fp", "fn", "tn", "calls"]
PAIRED_METRICS = ["f1", "precision", "recall", "false_positive_rate", "llm_calls"]


def _case_counts(sub: pd.DataFrame, method: str, cases: list[str]) -> np.ndarray:
    """(n_cases, 5) array of tp, fp, fn, tn, llm_calls for one method, aligned to `cases`."""
    g = sub[sub["method"] == method]
    actual = (g["truth"] == "violation").to_numpy()
    pred = g["predicted_violation"].astype(bool).to_numpy()
    frame = pd.DataFrame({
        "case_id": g["case_id"].to_numpy(),
        "tp": actual & pred, "fp": ~actual & pred, "fn": actual & ~pred, "tn": ~actual & ~pred,
        "calls": g["llm_called"].astype(bool).to_numpy(),
    })
    return frame.groupby("case_id")[_COUNT_COLS].sum().reindex(cases, fill_value=0).to_numpy(dtype=float)


def _metrics_from_sums(sums: np.ndarray) -> dict[str, np.ndarray]:
    """Vectorised metrics from summed counts (last axis = tp, fp, fn, tn, calls)."""
    tp, fp, fn, tn, calls = (sums[..., i] for i in range(5))
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            "f1": np.where(2 * tp + fp + fn > 0, 2 * tp / (2 * tp + fp + fn), np.nan),
            "precision": np.where(tp + fp > 0, tp / (tp + fp), np.nan),
            "recall": np.where(tp + fn > 0, tp / (tp + fn), np.nan),
            "false_positive_rate": np.where(fp + tn > 0, fp / (fp + tn), np.nan),
            "llm_calls": calls,
        }


def paired_bootstrap(
    preds: pd.DataFrame, split: str, a_methods: list[str], b_methods: list[str],
    n_boot: int = 2000, seed: int = 0,
) -> pd.DataFrame:
    """Difference (A - B) in each metric with a case-level paired bootstrap interval.

    Both methods are scored on the SAME resampled cases, so the interval reflects how the
    methods differ on the same data rather than how each varies on its own. A group of
    methods (e.g. the seeds of the randomised M4 baseline) is averaged metric-by-metric.
    """
    sub = preds[preds["split"] == split]
    cases = sorted(sub["case_id"].unique())
    if not cases:
        return pd.DataFrame()
    arrays = {m: _case_counts(sub, m, cases) for m in [*a_methods, *b_methods]}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(cases), size=(n_boot, len(cases)))

    def group_metrics(methods: list[str], resample: bool) -> dict[str, np.ndarray]:
        per = []
        for m in methods:
            sums = arrays[m][idx].sum(axis=1) if resample else arrays[m].sum(axis=0)
            per.append(_metrics_from_sums(sums))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices are legitimately undefined
            return {k: np.nanmean([p[k] for p in per], axis=0) if len(per) > 1 else per[0][k] for k in PAIRED_METRICS}

    a_pt, b_pt = group_metrics(a_methods, False), group_metrics(b_methods, False)
    a_bs, b_bs = group_metrics(a_methods, True), group_metrics(b_methods, True)
    rows = []
    for metric in PAIRED_METRICS:
        delta = a_bs[metric] - b_bs[metric]
        delta = delta[~np.isnan(delta)]
        lo, hi = (float(np.percentile(delta, 2.5)), float(np.percentile(delta, 97.5))) if len(delta) else (np.nan, np.nan)
        rows.append({
            "a": "+".join(a_methods) if len(a_methods) < 3 else f"{a_methods[0]}..(x{len(a_methods)})",
            "b": "+".join(b_methods) if len(b_methods) < 3 else f"{b_methods[0]}..(x{len(b_methods)})",
            "split": split, "metric": metric,
            "a_value": float(a_pt[metric]), "b_value": float(b_pt[metric]),
            "delta": float(a_pt[metric] - b_pt[metric]), "ci_low": lo, "ci_high": hi,
            "n_cases": len(cases),
        })
    return pd.DataFrame(rows)


# Scenarios whose targeted dependency has NO relevant decision record: A (plain) and H ("temporary" commit).
NO_ADR_SCENARIOS = frozenset({"A", "H"})


def density_sweep(
    preds: pd.DataFrame, split: str, densities=(0.1, 0.25, 0.5, 0.75, 1.0), seed_prefix="M4_generic_selective_s",
) -> pd.DataFrame:
    """How would the results look if only a fraction `d` of targeted dependencies had a
    decision record? Reweights the cases of the benchmark so that the ADR-bearing scenarios
    make up share d of the cases, then recomputes each method's metrics and LLM calls.

    This is a re-weighting of existing results, NOT new data: it can only reshuffle the
    scenario mix that exists, and it also shifts the violation/justified mix as a side
    effect. It exists to show how sensitive the call savings are to an assumption (ADR-dense
    benchmark) that real repositories probably do not satisfy.
    """
    sub = preds[preds["split"] == split]
    cases = sorted(sub["case_id"].unique())
    letter = sub.drop_duplicates("case_id").set_index("case_id")["scenario"].str[0]
    has_adr = np.array([letter[c] not in NO_ADR_SCENARIOS for c in cases])
    n, n_adr = len(cases), int(has_adr.sum())
    if n_adr in (0, n):
        return pd.DataFrame()  # need both kinds of case to reweight between them
    d0 = n_adr / n

    groups: dict[str, list[str]] = {}
    for m in sorted(sub["method"].unique()):
        key = "M4_generic_selective_mean" if m.startswith(seed_prefix) else m
        groups.setdefault(key, []).append(m)
    counts = {m: _case_counts(sub, m, cases) for ms in groups.values() for m in ms}

    rows = []
    for d in densities:
        w = np.where(has_adr, d / d0, (1 - d) / (1 - d0))
        for label, methods in groups.items():
            per = [_metrics_from_sums((counts[m] * w[:, None]).sum(axis=0)) for m in methods]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                agg = {k: float(np.nanmean([p[k] for p in per])) for k in PAIRED_METRICS}
            rows.append({"method": label, "split": split, "adr_density": d,
                         **{k: v for k, v in agg.items() if k != "llm_calls"},
                         "llm_calls_per_case": agg["llm_calls"] / n})
    out = pd.DataFrame(rows)
    out["calls_saved_vs_m3"] = np.nan  # stays NaN when the full hybrid (M3) was not part of the run
    hybrid = out[out["method"] == "M3_full_hybrid"].set_index("adr_density")["llm_calls_per_case"]
    if not hybrid.empty:
        out["calls_saved_vs_m3"] = 1 - out["llm_calls_per_case"] / out["adr_density"].map(hybrid)
    return out


# --------------------------------------------------------------------------------------
# Escalation quality: capture rate and the oracle gap
# --------------------------------------------------------------------------------------

# Methods that make no escalation decision over structural violations: M1 never escalates, M2 judges
# every raw import itself, M6 reads evidence with code only.
_NO_ESCALATION = ("M1_static", "M2_llm_only", "M6_deterministic_adr")

CAPTURE_COLS = [
    "structural_violations", "static_false_positives", "escalated", "captured_fp", "capture_rate", "escalation_rate",
    "random_expected_capture", "capture_lift", "escalation_yield", "wasted_escalations", "oracle_calls", "calls_over_oracle",
]


def escalation_capture(preds: pd.DataFrame) -> pd.DataFrame:
    """How well does each method choose WHICH structural violations to send to the LLM?

    A 'static false positive' is a structural violation the benchmark labels justified: the only
    kind of finding where a semantic review can change the answer in the right direction.

      capture_rate            share of static false positives that were escalated (higher is better)
      escalation_rate         share of structural violations escalated (the cost)
      random_expected_capture what picking at random at that same rate captures in expectation
                              (= escalation_rate), the line a real policy has to beat
      capture_lift            capture_rate - random_expected_capture
      escalation_yield        share of escalations that were static false positives
      oracle_calls            calls an all-knowing policy would make (= number of static false positives)
      calls_over_oracle       escalations beyond that minimum: the 'thinness' of the policy in calls

    M4's seeds are averaged into one row. Methods with no escalation decision are omitted.
    """
    rows = []
    for (method, split), g in preds.groupby(["method", "split"]):
        if method in _NO_ESCALATION:
            continue
        v = g[g["structural_status"] == "violation"]
        if v.empty:
            continue
        fp = (v["truth"] != "violation").to_numpy()
        esc = v["escalated"].astype(bool).to_numpy()
        n_fp, n_esc, n_v = int(fp.sum()), int(esc.sum()), len(v)
        cap = int((fp & esc).sum())
        key = "M4_generic_selective_mean" if method.startswith("M4_generic_selective_s") else method
        rows.append({
            "method": key, "split": split, "structural_violations": n_v, "static_false_positives": n_fp,
            "escalated": n_esc, "captured_fp": cap,
            "capture_rate": cap / n_fp if n_fp else np.nan,
            "escalation_rate": n_esc / n_v,
            "random_expected_capture": n_esc / n_v,
            "escalation_yield": cap / n_esc if n_esc else np.nan,
            "wasted_escalations": n_esc - cap, "oracle_calls": n_fp, "calls_over_oracle": n_esc - n_fp,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.groupby(["method", "split"], as_index=False).mean(numeric_only=True)
    out["capture_lift"] = out["capture_rate"] - out["random_expected_capture"]
    return out[["method", "split", *CAPTURE_COLS]]


def capture_curve(scores, is_static_fp) -> pd.DataFrame:
    """Capture curve of a SCORED escalation policy: escalate the top-k findings by score, for every k.

    `scores` rank findings (higher = escalate first); `is_static_fp` marks the findings whose structural
    verdict is wrong. Ties are broken by input order, which is arbitrary, so callers should say when a
    score has many ties. Returns k, escalation_rate, capture_rate plus the random and oracle references;
    `capture_auc` (same on every row) is the area under the capture curve: 0.5 for random selection, and
    `oracle_auc` for a perfect ranking. The oracle area is below 1.0 whenever positives are a fraction p of the
    findings (it is 1 - p/2), so compare a method's AUC with `oracle_auc`, not with 1.0.
    """
    scores = np.asarray(scores, dtype=float)
    fp = np.asarray(is_static_fp, dtype=bool)
    n, n_fp = len(scores), int(fp.sum())
    order = np.argsort(-scores, kind="stable")
    captured = np.concatenate([[0], np.cumsum(fp[order])])
    k = np.arange(n + 1)
    capture = captured / n_fp if n_fp else np.full(n + 1, np.nan)
    rate = k / n if n else np.zeros(1)
    _trap = getattr(np, "trapezoid", None) or np.trapz  # numpy 2 renamed trapz
    auc = float(_trap(capture, rate)) if n_fp and n else float("nan")
    oracle_auc = 1 - (n_fp / n) / 2 if n_fp and n else float("nan")
    return pd.DataFrame({
        "k": k, "escalation_rate": rate, "capture_rate": capture,
        "random_capture": rate, "oracle_capture": np.minimum(k / n_fp, 1.0) if n_fp else np.nan, "capture_auc": auc, "oracle_auc": oracle_auc,
    })
