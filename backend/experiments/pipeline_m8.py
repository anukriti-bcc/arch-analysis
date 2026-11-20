"""M8 `gated`: the readability-gated escalation policy (policy v2) with M7's resolution of escalated findings.

  M8 = routing by `analysis.policy.gated.ReadabilityGatedPolicy`
       direct_structural -> structural verdict, no model
       direct_code       -> the code reading of the ADR, no model (only when every readability gate passed)
       escalate          -> exactly what M7 does: an active relevant ADR -> the model EXTRACTS, code COMPUTES;
                            history-only -> the ordinary review prompt (M5's)

Because escalated findings are resolved identically to M7, M8's escalations are a subset of M7's and M8's answers
for them are M7's answers (same bundle, same prompt, so cached). `experiments.replay_policy` exploits that to
reproduce M8 offline from recorded M7 rows; a test checks that live and replay agree.

`budget` (a number of model calls over the whole run) keeps only the riskiest escalations; the others fall back to
the structural verdict and are labelled `direct_structural` with a "budget" reason, so the cost/quality frontier can
be drawn by sweeping it.
"""
from __future__ import annotations

import time

from analysis.intent.reader import introduction_date
from analysis.policy.gated import GatedDecision, ReadabilityGatedPolicy, apply_budget
from analysis.semantic.extract import LLMExtractAnalyzer
from experiments import pipeline
from models.finding import FindingStatus


def route_all(
    contexts: list[pipeline.CaseContext], policy: ReadabilityGatedPolicy, budget: int | None = None,
) -> dict[tuple[str, str], GatedDecision]:
    """Decide every structural violation of every case first (needed for a global budget)."""
    keys, decisions = [], []
    for ctx in contexts:
        for f in ctx.violations:
            keys.append((ctx.case_id, f.key))
            decisions.append(policy.decide(ctx.bundle(f)))
    if budget is not None:
        decisions = apply_budget(decisions, budget)
    return dict(zip(keys, decisions))


def run_gated(
    ctx: pipeline.CaseContext, client: pipeline.TimedClient, decisions: dict[tuple[str, str], GatedDecision], *,
    method: str = "M8_gated", variant: str = "full",
) -> list[dict]:
    extractor = LLMExtractAnalyzer(client)
    rows = []
    for f in ctx.findings:
        start, w0 = time.perf_counter(), client.wall
        r = pipeline._row(ctx, method, f)
        if f.status == FindingStatus.VIOLATION:
            d = decisions[(ctx.case_id, f.key)]
            r["policy_reasons"] = " | ".join(d.reasons)
            r["failed_gates"] = ",".join(d.failed_gates)
            if not d.escalate:
                r["predicted_violation"] = bool(d.predicted_violation)
                r["outcome_source"] = d.route
            else:
                bundle = ctx.bundle(f, use_adrs=True, use_evolution=True)
                if any(m.adr.is_active for m in bundle.adrs):  # same split as M7
                    r["escalated"] = True
                    pipeline._apply_extraction(r, extractor.extract(bundle), introduction_date(bundle.evolution))
                else:
                    pipeline._review(ctx, client, r, f, use_adrs=True, use_evolution=True, variant=variant)
        r["compute_s"] = max((time.perf_counter() - start) - (client.wall - w0), 0.0)
        rows.append(r)
    return rows
