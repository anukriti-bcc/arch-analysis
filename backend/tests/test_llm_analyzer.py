import json

import pytest

from analysis.semantic.llm_analyzer import (
    EDGE_VERDICTS, REVIEW_VERDICTS, LLMEdgeAnalyzer, LLMSemanticAnalyzer, parse_verdict_json,
)
from analysis.semantic.llm_client import FunctionClient
from analysis.semantic.prompts import render_review_prompt

GOOD = '{"verdict":"justified","confidence":0.8,"explanation":"ADR permits it.","evidence_used":["ADR-007"]}'


@pytest.mark.parametrize("text,verdict", [
    (GOOD, "justified"),
    ('```json\n' + GOOD + '\n```', "justified"),
    ('Sure, here you go: ' + GOOD + ' hope that helps', "justified"),
    ('{"verdict":"VIOLATION","confidence":"0.9"}', "violation"),
])
def test_parse_accepts_realistic_model_output(text, verdict):
    assert parse_verdict_json(text, REVIEW_VERDICTS)["verdict"] == verdict


@pytest.mark.parametrize("text", ["", "no json at all", '{"verdict":"maybe"}', '{"nope":1}', "[1,2]", '{"verdict": "conformant"}'])
def test_parse_rejects_invalid_output(text):
    assert parse_verdict_json(text, REVIEW_VERDICTS) is None


def test_confidence_is_clamped_and_garbage_confidence_defaults():
    assert parse_verdict_json('{"verdict":"violation","confidence":7}', REVIEW_VERDICTS)["confidence"] == 1.0
    assert parse_verdict_json('{"verdict":"violation","confidence":"high"}', REVIEW_VERDICTS)["confidence"] == 0.0


def test_edge_verdict_set_accepts_conformant():
    assert parse_verdict_json('{"verdict":"conformant"}', EDGE_VERDICTS)["verdict"] == "conformant"


def finding_and_bundle(bench_cases, letter="C"):
    ctx = bench_cases[letter]
    f = ctx.violations[0]
    return ctx, f, ctx.bundle(f)


def test_review_returns_verdict_tokens_and_metadata(bench_cases):
    _, f, bundle = finding_and_bundle(bench_cases)
    res = LLMSemanticAnalyzer(FunctionClient(lambda s, p: GOOD)).analyze(f, bundle)
    assert res["verdict"] == "justified" and res["parsed_ok"] and res["error"] is None
    assert res["tokens_used"]["input"] > 0 and res["model"] == "function-stub" and res["mode"] == "review"


def test_unparseable_output_is_a_recorded_failure_not_a_verdict(bench_cases):
    _, f, bundle = finding_and_bundle(bench_cases)
    res = LLMSemanticAnalyzer(FunctionClient(lambda s, p: "I think it is fine.")).analyze(f, bundle)
    assert res["verdict"] is None and res["parsed_ok"] is False and "unparseable" in res["error"]


def test_provider_failure_is_a_recorded_failure(bench_cases):
    _, f, bundle = finding_and_bundle(bench_cases)
    def boom(s, p):
        raise ConnectionError("down")
    res = LLMSemanticAnalyzer(FunctionClient(boom)).analyze(f, bundle)
    assert res["verdict"] is None and "ConnectionError" in res["error"]


def test_prompt_wraps_adrs_in_tags_and_includes_history(bench_cases):
    ctx, f, bundle = finding_and_bundle(bench_cases)
    prompt = render_review_prompt(bundle, include_adrs=True, include_evolution=True)
    assert '<adr id="ADR-' in prompt and "</adr>" in prompt
    assert "was introduced on" in prompt and "Repository snapshot date" in prompt


def test_prompt_omits_history_and_adrs_when_disabled(bench_cases):
    ctx, f, bundle = finding_and_bundle(bench_cases)
    prompt = render_review_prompt(bundle, include_adrs=False, include_evolution=False)
    assert "<adr" not in prompt and "was introduced on" not in prompt
    assert "Version-control history" not in prompt and "decision records" not in prompt


def test_edge_analyzer_sends_every_adr_and_no_structural_verdict(bench_cases):
    ctx = bench_cases["B"]
    seen = {}
    def model(system, prompt):
        seen["prompt"] = prompt
        return '{"verdict":"conformant"}'
    f = ctx.findings[0]
    dep = f.structural_evidence.dependency
    res = LLMEdgeAnalyzer(FunctionClient(model)).analyze_edge(
        snapshot_date="2025-10-01", mapping_text=ctx.mapping_text(), rules_text=ctx.rules_text(), adrs=ctx.adrs,
        source_path=dep.source, target_path=dep.target, import_reference=dep.raw_reference, code_snippet="x",
    )
    assert res["verdict"] == "conformant" and res["mode"] == "edge"
    assert seen["prompt"].count('<adr id=') == len(ctx.adrs)
    assert "[violation]" not in seen["prompt"] and "Triggered rule" not in seen["prompt"]
