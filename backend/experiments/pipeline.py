"""Per-case context and the evaluated methods (M1-M5 + ablation).

Every method answers the same question for each *governed dependency edge* of a
case repository: "is this a genuine architectural violation?" (positive class).
Ground truth comes from the benchmark's labels.json (violation / justified /
conformant). A dependency labelled 'justified' is flagged by the structural
rules but is legitimate; reporting it as a violation is a false positive.

  M1 static            structural rules only                      (no LLM)
  M2 llm_only          LLM judges every raw import from rules+ADR text,
                       with no structural pre-check               (LLM on ALL edges)
  M3 full_hybrid       structural violations -> LLM on EVERY one, full evidence
  M4 generic_selective structural violations -> LLM on a RANDOM budget-matched
                       subset (same #calls as M5), full evidence. Tests whether
                       merely *calling the LLM less* explains M5's results.
  M5 evidence_guided   structural violations -> LLM only where the escalation
                       policy finds the evidence insufficient
  M7 extract_compute   M5's escalation policy, unchanged; but an escalated finding that has an
                       active relevant ADR is resolved by EXTRACT-THEN-COMPUTE: the LLM extracts
                       facts (decision, scope, date limit) from the ADR without being given any
                       date, and code compares the limit with the Git introduction date
                       (analysis/semantic/extract.py). Same number of calls as M5.
  M6 deterministic_adr structural violations -> a CODE-ONLY reader of the same
                       evidence (ADR status, scope, decision cues, date clauses;
                       analysis/intent/reader.py). No LLM. Answers "why use an
                       LLM at all?": it is the strongest baseline that reads the
                       same evidence without a model.
  A1 no_history        M5 without evolution evidence (policy and prompt)
  A2 no_intent         M5 without architectural-intent evidence (no ADR text in policy or prompt;
                       only history signals can trigger escalation)

Outcome of an escalated finding:
  verdict "justified"                  -> predicted NOT a violation
  verdict "violation"                  -> predicted violation
  "uncertain" / failed call / unparseable -> falls back to the structural
                                           verdict (violation); counted as a
                                           fallback so failures stay visible.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from typing import Callable

from analysis.conformance.engine import analyze_conformance
from analysis.dependency.repository_scanner import scan_repository
from analysis.evidence.aggregator import EvidenceAggregator, EvidenceBundle
from analysis.evolution.git_evolution import GitEvolutionAnalyzer
from analysis.intent.adr import load_adrs
from analysis.intent.reader import decide_deterministic, introduction_date
from analysis.semantic.extract import LLMExtractAnalyzer, resolve_extraction
from analysis.policy.escalation import EvidenceGuidedPolicy
from analysis.semantic.llm_analyzer import LLMEdgeAnalyzer, LLMSemanticAnalyzer
from analysis.semantic.llm_client import LLMClient, LLMResponse
from models.finding import Finding, FindingStatus
from rules.loader import load_architecture_file


class TimedClient(LLMClient):
    """Measures wall time spent inside the client so per-finding *compute* time
    can be separated from LLM time (cached calls report their original latency)."""

    def __init__(self, inner: LLMClient):
        self.inner, self.model, self.wall = inner, inner.model, 0.0

    def complete(self, system, prompt, *, temperature=0.0, max_tokens=600) -> LLMResponse:
        t = time.perf_counter()
        try:
            return self.inner.complete(system, prompt, temperature=temperature, max_tokens=max_tokens)
        finally:
            self.wall += time.perf_counter() - t


class CaseContext:
    def __init__(self, benchmark_root: str, entry: dict, evolution: GitEvolutionAnalyzer | None = None):
        self.case_id, self.scenario, self.split = entry["case_id"], entry["scenario"], entry["split"]
        case_dir = os.path.join(benchmark_root, entry["path"])
        self.repo = os.path.join(case_dir, "repo")
        with open(os.path.join(case_dir, "labels.json"), encoding="utf-8") as f:
            self.meta = json.load(f)
        self.truth = {(e["source"], e["target"]): e["label"] for e in self.meta["edges"]}
        rules_file = os.path.join(self.repo, "architecture", "rules.yaml")
        self.architecture, self.mapping = load_architecture_file(rules_file)
        scan = scan_repository(self.repo, self.mapping)
        self.findings: list[Finding] = analyze_conformance(scan.components, scan.dependencies, self.architecture)
        self.adrs = load_adrs(self.repo)
        self.aggregator = EvidenceAggregator(self.repo, self.architecture, self.adrs, evolution or GitEvolutionAnalyzer())
        self._bundles: dict[tuple, EvidenceBundle] = {}

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.status == FindingStatus.VIOLATION]

    def edge(self, f: Finding) -> tuple[str, str]:
        d = f.structural_evidence.dependency
        return d.source, d.target

    def bundle(self, f: Finding, use_adrs=True, use_evolution=True) -> EvidenceBundle:
        key = (f.key, use_adrs, use_evolution)
        if key not in self._bundles:
            self._bundles[key] = self.aggregator.build(f, use_adrs=use_adrs, use_evolution=use_evolution)
        return self._bundles[key]

    def mapping_text(self) -> str:
        return "\n".join(f"  {d}/ -> {t}" for d, t in sorted(self.mapping.mapping.items()))

    def rules_text(self) -> str:
        return "\n".join(
            f"  {r.id} [{r.relation.value}] {r.source} -> {r.target}: {r.description}" for r in self.architecture.rules
        )


def _row(ctx: CaseContext, method: str, f: Finding) -> dict:
    src, tgt = ctx.edge(f)
    return {
        "method": method, "case_id": ctx.case_id, "scenario": ctx.scenario, "split": ctx.split,
        "source": src, "target": tgt, "rule_id": f.rule_id, "truth": ctx.truth[(src, tgt)],
        "structural_status": f.status.value, "predicted_violation": f.status == FindingStatus.VIOLATION,
        "escalated": False, "llm_called": False, "outcome_source": "static", "verdict": None,
        "parsed_ok": None, "error": None, "input_tokens": 0, "output_tokens": 0, "latency_s": 0.0,
        "cached": None, "tokens_estimated": None, "compute_s": 0.0, "policy_reasons": "", "explanation": "",
    }


def _apply_llm(row: dict, result: dict, *, edge_mode: bool = False) -> None:
    row["llm_called"] = True
    row["explanation"] = result.get("explanation") or (result.get("raw_text") or "")[:300]
    row["verdict"], row["parsed_ok"], row["error"] = result["verdict"], result["parsed_ok"], result["error"]
    row["input_tokens"], row["output_tokens"] = result["tokens_used"]["input"], result["tokens_used"]["output"]
    row["latency_s"], row["cached"], row["tokens_estimated"] = result["latency_s"], result["cached"], result["tokens_estimated"]
    v = result["verdict"]
    if edge_mode:  # no structural verdict to fall back on
        row["predicted_violation"] = v == "violation"
        row["outcome_source"] = "llm" if result["parsed_ok"] else "llm_failed"
    elif v == "violation":
        row["predicted_violation"], row["outcome_source"] = True, "llm"
    elif v == "justified":
        row["predicted_violation"], row["outcome_source"] = False, "llm"
    else:  # uncertain, failed or unparseable -> keep the structural verdict, but say so
        row["predicted_violation"], row["outcome_source"] = True, "fallback"


def run_static(ctx: CaseContext, method="M1_static") -> list[dict]:
    rows = []
    for f in ctx.findings:
        t = time.perf_counter()
        r = _row(ctx, method, f)
        r["compute_s"] = time.perf_counter() - t
        rows.append(r)
    return rows


def run_llm_only(ctx: CaseContext, client: TimedClient, method="M2_llm_only", variant="full") -> list[dict]:
    analyzer = LLMEdgeAnalyzer(client, variant=variant)
    snapshot = ctx.aggregator.snapshot_date()
    rows = []
    for f in ctx.findings:
        start, w0 = time.perf_counter(), client.wall
        r = _row(ctx, method, f)
        dep = f.structural_evidence.dependency
        from analysis.evidence.aggregator import read_snippet
        res = analyzer.analyze_edge(
            snapshot_date=snapshot, mapping_text=ctx.mapping_text(), rules_text=ctx.rules_text(), adrs=ctx.adrs,
            source_path=dep.source, target_path=dep.target, import_reference=dep.raw_reference,
            code_snippet=read_snippet(ctx.repo, dep.source, dep.location.line),
        )
        r["escalated"] = True
        _apply_llm(r, res, edge_mode=True)
        r["compute_s"] = max((time.perf_counter() - start) - (client.wall - w0), 0.0)
        rows.append(r)
    return rows


def _review(ctx, client, row, f, *, use_adrs, use_evolution, variant="full"):
    analyzer = LLMSemanticAnalyzer(client, include_adrs=use_adrs, include_evolution=use_evolution, variant=variant)
    bundle = ctx.bundle(f, use_adrs=use_adrs, use_evolution=use_evolution)
    row["escalated"] = True
    _apply_llm(row, analyzer.analyze(f, bundle))


def run_full_hybrid(ctx: CaseContext, client: TimedClient, method="M3_full_hybrid", variant="full") -> list[dict]:
    rows = []
    for f in ctx.findings:
        start, w0 = time.perf_counter(), client.wall
        r = _row(ctx, method, f)
        if f.status == FindingStatus.VIOLATION:
            _review(ctx, client, r, f, use_adrs=True, use_evolution=True, variant=variant)
        r["compute_s"] = max((time.perf_counter() - start) - (client.wall - w0), 0.0)
        rows.append(r)
    return rows


def run_evidence_guided(
    ctx: CaseContext, client: TimedClient, *, method="M5_evidence_guided",
    use_intent=True, use_history=True, variant="full",
) -> list[dict]:
    policy = EvidenceGuidedPolicy(use_intent=use_intent, use_history=use_history)
    rows = []
    for f in ctx.findings:
        start, w0 = time.perf_counter(), client.wall
        r = _row(ctx, method, f)
        if f.status == FindingStatus.VIOLATION:
            bundle = ctx.bundle(f, use_adrs=use_intent, use_evolution=use_history)
            decision = policy.decide(bundle)
            r["policy_reasons"] = " | ".join(decision.reasons)
            if decision.escalate:
                _review(ctx, client, r, f, use_adrs=use_intent, use_evolution=use_history, variant=variant)
            else:
                r["outcome_source"] = "direct"
        r["compute_s"] = max((time.perf_counter() - start) - (client.wall - w0), 0.0)
        rows.append(r)
    return rows


def run_generic_selective(
    contexts: list[CaseContext], client: TimedClient, k: int, seed: int, method: str, variant: str = "full",
) -> list[dict]:
    """Escalate exactly k structural violations chosen uniformly at random
    (same budget as M5), with the same full-evidence prompt as M3/M5."""
    pool = [(ctx, f) for ctx in contexts for f in ctx.violations]
    chosen = {(c.case_id, f.key) for c, f in random.Random(seed).sample(pool, min(k, len(pool)))}
    rows = []
    for ctx in contexts:
        for f in ctx.findings:
            start, w0 = time.perf_counter(), client.wall
            r = _row(ctx, method, f)
            if f.status == FindingStatus.VIOLATION:
                if (ctx.case_id, f.key) in chosen:
                    _review(ctx, client, r, f, use_adrs=True, use_evolution=True, variant=variant)
                else:
                    r["outcome_source"] = "direct"
            r["compute_s"] = max((time.perf_counter() - start) - (client.wall - w0), 0.0)
            rows.append(r)
    return rows


def run_deterministic_adr(ctx: CaseContext, method: str = "M6_deterministic_adr") -> list[dict]:
    """M6: the same evidence M5 sees, read by code only (no LLM calls).

    'unclear' readings keep the structural verdict (violation) and are labelled
    outcome_source='fallback' so the cases code could not read stay visible."""
    rows = []
    for f in ctx.findings:
        start = time.perf_counter()
        r = _row(ctx, method, f)
        if f.status == FindingStatus.VIOLATION:
            bundle = ctx.bundle(f, use_adrs=True, use_evolution=True)
            d = decide_deterministic(bundle.adrs, bundle.evolution)
            r["predicted_violation"] = d.predicted_violation
            r["outcome_source"] = "fallback" if d.outcome == "unclear" else "deterministic"
            r["policy_reasons"] = d.reason
        r["compute_s"] = time.perf_counter() - start
        rows.append(r)
    return rows


def _apply_extraction(row: dict, result: dict, introduced) -> None:
    row["llm_called"] = True
    row["parsed_ok"], row["error"] = result["parsed_ok"], result["error"]
    row["input_tokens"], row["output_tokens"] = result["tokens_used"]["input"], result["tokens_used"]["output"]
    row["latency_s"], row["cached"], row["tokens_estimated"] = result["latency_s"], result["cached"], result["tokens_estimated"]
    x = result["parsed"]
    if x is None:  # unparseable: keep the structural verdict, say so
        row["predicted_violation"], row["outcome_source"] = True, "fallback"
        row["explanation"] = (result.get("raw_text") or "")[:300]
        return
    res = resolve_extraction(x, introduced)
    row["predicted_violation"] = res.predicted_violation
    row["outcome_source"] = "fallback" if res.outcome == "unresolved" else "llm_extract"
    row["verdict"] = None if res.outcome == "unresolved" else res.outcome
    row["explanation"] = x["explanation"]
    row["extraction"] = json.dumps({**x, "limit_date": x["limit_date"].isoformat() if x["limit_date"] else None})
    row["computed"] = res.note


def run_extract_compute(ctx: CaseContext, client: TimedClient, *, method="M7_extract_compute", variant="full") -> list[dict]:
    """M7. Escalation is exactly M5's. Resolution of an escalated finding:
      * an active relevant ADR exists  -> LLM extracts facts, code computes the verdict
      * none (history-only escalation) -> the ordinary review prompt, identical to M5 (so cached, no new call)."""
    policy = EvidenceGuidedPolicy()
    extractor = LLMExtractAnalyzer(client)
    rows = []
    for f in ctx.findings:
        start, w0 = time.perf_counter(), client.wall
        r = _row(ctx, method, f)
        if f.status == FindingStatus.VIOLATION:
            bundle = ctx.bundle(f, use_adrs=True, use_evolution=True)
            decision = policy.decide(bundle)
            r["policy_reasons"] = " | ".join(decision.reasons)
            if not decision.escalate:
                r["outcome_source"] = "direct"
            elif any(m.adr.is_active for m in bundle.adrs):
                r["escalated"] = True
                _apply_extraction(r, extractor.extract(bundle), introduction_date(bundle.evolution))
            else:
                _review(ctx, client, r, f, use_adrs=True, use_evolution=True, variant=variant)
        r["compute_s"] = max((time.perf_counter() - start) - (client.wall - w0), 0.0)
        rows.append(r)
    return rows
