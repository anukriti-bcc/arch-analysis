from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from analysis.conformance.engine import analyze_conformance
from analysis.dependency.graph import build_dependency_graph, graph_to_dict
from analysis.dependency.repository_scanner import scan_repository
from analysis.evidence.aggregator import EvidenceAggregator
from analysis.evolution.git_evolution import GitEvolutionAnalyzer
from analysis.intent.adr import load_adrs
from analysis.intent.reader import introduction_date
from analysis.policy.escalation import EvidenceGuidedPolicy
from analysis.semantic.extract import LLMExtractAnalyzer, resolve_extraction
from analysis.semantic.llm_analyzer import LLMSemanticAnalyzer
from analysis.semantic.llm_client import LLMClient, client_from_env
from api.schemas.analyze import (
    AnalysisSummary,
    AnalyzeRequest,
    AnalyzeResponse,
    FindingDetail,
    FindingSummary,
    GraphResponse,
)
from models.rule import RelationType
from rules.loader import ArchitectureFileError, load_architecture_file
from storage import store
from storage.memory_store import AnalysisRun, now_iso

router = APIRouter()

_evolution_analyzer = GitEvolutionAnalyzer()
_policy = EvidenceGuidedPolicy()


def get_llm_client() -> LLMClient | None:
    """Configured from LLM_BASE_URL / LLM_MODEL / LLM_API_KEY (see
    analysis/semantic/llm_client.py). A function, not a constant, so tests can
    substitute a stub and so a missing configuration is reported per request."""
    return client_from_env()


def _extract_and_compute(client: LLMClient, bundle) -> tuple[dict, str, str]:
    """Method M7 in the product: the model EXTRACTS facts from the ADR (it is never shown any date to compare), and code
    COMPUTES the verdict by comparing the extracted date limit with the Git introduction date.
    Returns (semantic result for the UI, final verdict, outcome source)."""
    result = LLMExtractAnalyzer(client).extract(bundle)
    base = {"mode": "extract_compute", "extract_version": result["extract_version"], "parsed_ok": result["parsed_ok"],
            "error": result["error"], "model": result["model"], "tokens_used": result["tokens_used"],
            "tokens_estimated": result["tokens_estimated"], "latency_s": result["latency_s"], "cached": result["cached"],
            "confidence": None, "evidence_used": []}
    x = result["parsed"]
    if x is None:  # unparseable reply: keep the structural verdict and say so
        return {**base, "verdict": None, "explanation": "", "extraction": None, "computed": None}, "violation", "fallback"
    res = resolve_extraction(x, introduction_date(bundle.evolution))
    extraction = {**x, "limit_date": x["limit_date"].isoformat() if x["limit_date"] else None}
    semantic = {**base, "verdict": None if res.outcome == "unresolved" else res.outcome, "explanation": x["explanation"],
                "extraction": extraction, "computed": res.note}
    return semantic, ("justified" if res.outcome == "justified" else "violation"), ("fallback" if res.outcome == "unresolved" else "llm_extract")


def _find(finding_id: str, analysis_id: str | None):
    finding = store.get_finding(finding_id, analysis_id=analysis_id)
    if finding is None:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found.")
    run = store.get(finding.analysis_id) if finding.analysis_id else None
    if run is None:
        raise HTTPException(status_code=404, detail="The analysis run for this finding is no longer available.")
    return finding, run


@router.post("/repositories/analyze", response_model=AnalyzeResponse)
def analyze_repository(request: AnalyzeRequest) -> AnalyzeResponse:
    if not os.path.isdir(request.repository_path):
        raise HTTPException(
            status_code=400, detail=f"repository_path '{request.repository_path}' does not exist."
        )
    if not os.path.isfile(request.architecture_file):
        raise HTTPException(
            status_code=400,
            detail=f"architecture_file '{request.architecture_file}' does not exist.",
        )

    try:
        architecture, mapping = load_architecture_file(request.architecture_file)
    except ArchitectureFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan_result = scan_repository(request.repository_path, mapping)
    graph = build_dependency_graph(scan_result.components, scan_result.dependencies)
    findings = analyze_conformance(scan_result.components, scan_result.dependencies, architecture)

    run = AnalysisRun(
        id=store.next_id(),
        repository_path=request.repository_path,
        architecture_name=architecture.name,
        created_at=now_iso(),
        components=scan_result.components,
        dependencies=scan_result.dependencies,
        architecture=architecture,
        findings=findings,
        graph=graph,
        external_imports=scan_result.external_imports,
    )
    store.save(run)

    return AnalyzeResponse(
        analysis_id=run.id,
        repository=run.repository_path,
        architecture=run.architecture_name,
        created_at=run.created_at,
        components=len(run.components),
        dependencies=len(run.dependencies),
        rules=len(run.architecture.rules),
        findings=[
            FindingSummary(
                id=f.id,
                status=f.status.value,
                source=f.source,
                target=f.target,
                rule_id=f.rule_id,
                severity=f.severity.value,
            )
            for f in run.findings
        ],
        external_imports=run.external_imports,
    )


@router.get("/analysis", response_model=list[AnalysisSummary])
def list_analyses() -> list[AnalysisSummary]:
    return [AnalysisSummary(**summary) for summary in store.list_summaries()]


@router.get("/analysis/{analysis_id}", response_model=AnalysisSummary)
def get_analysis(analysis_id: str) -> AnalysisSummary:
    run = store.get(analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found.")
    return AnalysisSummary(**run.summary())


@router.get("/analysis/{analysis_id}/graph", response_model=GraphResponse)
def get_analysis_graph(analysis_id: str) -> GraphResponse:
    run = store.get(analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found.")

    violation_edges = {
        (f.structural_evidence.dependency.source, f.structural_evidence.dependency.target)
        for f in run.findings
        if f.status.value == "violation" and f.structural_evidence
    }
    return GraphResponse(**graph_to_dict(run.graph, violation_edges))


@router.get("/analysis/{analysis_id}/findings", response_model=list[FindingSummary])
def get_analysis_findings(analysis_id: str) -> list[FindingSummary]:
    run = store.get(analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found.")
    return [
        FindingSummary(
            id=f.id,
            status=f.status.value,
            source=f.source,
            target=f.target,
            rule_id=f.rule_id,
            severity=f.severity.value,
        )
        for f in run.findings
    ]


@router.get("/analysis/{analysis_id}/findings/{finding_id}", response_model=FindingDetail)
def get_analysis_finding(analysis_id: str, finding_id: str) -> FindingDetail:
    finding = store.get_finding(finding_id, analysis_id=analysis_id)
    if finding is None:
        raise HTTPException(
            status_code=404, detail=f"Finding '{finding_id}' not found in analysis '{analysis_id}'."
        )
    return FindingDetail(**finding.to_dict())


@router.get("/findings/{finding_id}", response_model=FindingDetail)
def get_finding(finding_id: str) -> FindingDetail:
    """Legacy lookup. Finding ids repeat across runs, so this resolves to the
    most recent run. Prefer /analysis/{analysis_id}/findings/{finding_id}."""
    finding = store.get_finding(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found.")
    return FindingDetail(**finding.to_dict())


def _aggregator(run) -> EvidenceAggregator:
    return EvidenceAggregator(run.repository_path, run.architecture, load_adrs(run.repository_path), _evolution_analyzer)


def _gather(finding, aggregator):
    """Evidence bundle + policy decision for one finding. No LLM involved."""
    bundle = aggregator.build(finding)
    finding.evolution_evidence = bundle.evolution
    finding.architectural_intent = {"rule": bundle.to_dict()["rule"], "adrs": [m.to_dict() for m in bundle.adrs]}
    store.update_finding(finding)  # a database store must persist evidence attached after the run was saved
    return bundle, _policy.decide(bundle)


@router.get("/findings/{finding_id}/evolution")
def get_finding_evolution(finding_id: str, analysis_id: str | None = None) -> dict:
    """Evolution evidence (Milestone 2): when the dependency behind this finding
    was introduced, how long it has persisted, and what the history says."""
    finding, run = _find(finding_id, analysis_id)
    if finding.evolution_evidence is None:
        finding.evolution_evidence = _evolution_analyzer.analyze(run.repository_path, finding)
        store.update_finding(finding)
    return {"finding_id": finding_id, "analysis_id": run.id, "evolution_evidence": finding.evolution_evidence}


@router.get("/findings/{finding_id}/evidence")
def get_finding_evidence(finding_id: str, analysis_id: str | None = None) -> dict:
    """Everything known about a violation *before* any LLM is involved: the
    three evidence sources, and what the escalation policy would do with them.
    Cheap and deterministic, so the UI can show it the moment a finding opens."""
    finding, run = _find(finding_id, analysis_id)
    if finding.status.value != "violation":
        raise HTTPException(status_code=409, detail="Only structural violations have an evidence bundle.")
    bundle, decision = _gather(finding, _aggregator(run))
    return {"finding_id": finding_id, "analysis_id": run.id, "evidence": bundle.to_dict(), "policy": decision.to_dict()}


@router.get("/analysis/{analysis_id}/triage")
def get_analysis_triage(analysis_id: str) -> dict:
    """For every violation: would the evidence be sufficient on its own, or does
    it need semantic (LLM) review? Computed without calling any model, so it
    shows how much LLM work the evidence-guided approach avoids."""
    run = store.get(analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found.")
    aggregator = _aggregator(run)
    items = []
    for finding in run.findings:
        if finding.status.value != "violation":
            continue
        bundle, decision = _gather(finding, aggregator)
        ev = bundle.evolution or {}
        items.append({
            "finding_id": finding.id, "key": finding.key,
            "source": finding.source, "target": finding.target, "rule_id": finding.rule_id,
            "escalate": decision.escalate, "direct_verdict": decision.direct_verdict, "reasons": decision.reasons,
            "introduced_at": ev.get("introduced_at"), "age_days": ev.get("age_days"),
            "adr_count": len(bundle.adrs), "active_adr_count": sum(1 for m in bundle.adrs if m.adr.is_active),
        })
    needs = sum(1 for i in items if i["escalate"])
    return {"analysis_id": run.id,
            "summary": {"violations": len(items), "resolved_directly": len(items) - needs, "needs_semantic_review": needs},
            "items": items}


@router.post("/findings/{finding_id}/semantic-analysis")
def request_semantic_analysis(finding_id: str, analysis_id: str | None = None, force: bool = False) -> dict:
    """The evidence-guided workflow for one finding (Milestones 3-5):

    1. aggregate intent (rules, ADRs), structural and evolution evidence;
    2. ask the escalation policy whether that evidence is sufficient;
    3. only if not (or if `force=true`), call the configured LLM. When an active relevant ADR exists the model only
       EXTRACTS facts from it (decision, date limit) and code computes the verdict (method M7); otherwise the
       ordinary review prompt is used.

    The structured decision, including *why* the LLM was or was not used, is
    stored on the finding and returned.
    """
    finding, run = _find(finding_id, analysis_id)
    if finding.status.value != "violation":
        raise HTTPException(status_code=409, detail="Only structural violations are subject to semantic review.")

    bundle, decision = _gather(finding, _aggregator(run))

    if decision.escalate or force:
        client = get_llm_client()
        if client is None:
            raise HTTPException(
                status_code=503,
                detail=("This finding needs semantic analysis but no LLM is configured. Set LLM_BASE_URL and "
                        "LLM_MODEL (and LLM_API_KEY if needed), e.g. for Ollama: "
                        "LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:7b-instruct."),
            )
        if any(m.adr.is_active for m in bundle.adrs):
            # an active relevant ADR exists: extract its facts, let code compute the verdict (method M7)
            result, final, outcome = _extract_and_compute(client, bundle)
            resolution = "extract_compute"
        else:
            # history-only escalation: nothing to extract, so the ordinary review prompt (as in M5/M7)
            result = LLMSemanticAnalyzer(client).analyze(finding, bundle)
            verdict = result["verdict"] if result["parsed_ok"] else "violation"
            outcome = "llm" if result["parsed_ok"] and verdict in ("violation", "justified") else "fallback"
            final = "justified" if verdict == "justified" else "violation"
            resolution = "review"
        finding.semantic_analysis = result
        finding.decision = {**decision.to_dict(), "forced": force and not decision.escalate, "llm_called": True,
                            "final_verdict": final, "outcome_source": outcome, "resolution": resolution}
    else:
        finding.semantic_analysis = None
        finding.decision = {**decision.to_dict(), "forced": False, "llm_called": False,
                            "final_verdict": decision.direct_verdict, "outcome_source": "direct", "resolution": "direct"}
    store.update_finding(finding)
    return {"finding_id": finding_id, "analysis_id": run.id, "decision": finding.decision,
            "semantic_analysis": finding.semantic_analysis, "evolution_evidence": finding.evolution_evidence,
            "evidence": bundle.to_dict()}
