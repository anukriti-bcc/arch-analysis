"""M8 + stance-attribution check (`gated_attr`): the readability-gated routing of M8 with the code-side attribution
check (`analysis.semantic.attribution`) applied to every extraction before the verdict is computed.

Identical to M8 in routing and in the model call (same prompt, same cache); the only difference is that a "permits"
reading of a decision that names other modules must be backed by a sentence about THIS module. No extra calls.
"""
from __future__ import annotations

import time

from analysis.intent.reader import introduction_date
from analysis.policy.gated import GatedDecision
from analysis.semantic.attribution import check_attribution
from analysis.semantic.extract import LLMExtractAnalyzer
from experiments import pipeline
from models.finding import FindingStatus


def run_gated_attr(
    ctx: pipeline.CaseContext, client: pipeline.TimedClient, decisions: dict[tuple[str, str], GatedDecision], *,
    method: str = "M8_gated_attr", variant: str = "full",
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
                if any(m.adr.is_active for m in bundle.adrs):
                    r["escalated"] = True
                    result = extractor.extract(bundle)
                    if result["parsed"] is not None:
                        result["parsed"] = check_attribution(result["parsed"], bundle.adrs, bundle.source_path, bundle.target_path)
                        r["attribution"] = result["parsed"]["attribution"]
                    pipeline._apply_extraction(r, result, introduction_date(bundle.evolution))
                else:
                    pipeline._review(ctx, client, r, f, use_adrs=True, use_evolution=True, variant=variant)
        r["compute_s"] = max((time.perf_counter() - start) - (client.wall - w0), 0.0)
        rows.append(r)
    return rows
