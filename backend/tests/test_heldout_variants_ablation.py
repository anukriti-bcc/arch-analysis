"""Held-out ADR wordings, minimal-prompt sensitivity variant, and the no-intent ablation (A2)."""
import glob
import json
import re

import pytest

from analysis.policy.escalation import EvidenceGuidedPolicy
from analysis.semantic.llm_analyzer import LLMEdgeAnalyzer, LLMSemanticAnalyzer
from analysis.semantic.llm_client import FunctionClient
from analysis.semantic.prompts import PROMPT_VARIANTS, SYSTEM_REVIEW, SYSTEM_REVIEW_MINIMAL
from experiments import pipeline
from experiments.benchmark.generate import build_case
from experiments.mock_llm import mock_model

LETTERS = "ABCDEFGHJK"
PRIMARY_PHRASES = re.compile(r"grandfather|permanent exception|on or before|reaffirm|reviewed and rejected|may query", re.I)


def label(path):
    d = json.load(open(path))
    d.pop("wording", None)
    return d


# ------------------------------------------------------------------ held-out wording

@pytest.mark.parametrize("letter", LETTERS)
def test_heldout_keeps_labels_dates_and_source_identical(bench_root, bench_root_heldout, bench_cases, bench_cases_heldout, letter):
    assert label(f"{bench_root}/{letter}01/labels.json") == label(f"{bench_root_heldout}/{letter}01/labels.json")
    a, b = bench_cases[letter], bench_cases_heldout[letter]
    assert [a.edge(f) for f in a.findings] == [b.edge(f) for f in b.findings]
    ea, eb = a.bundle(a.violations[0]).evolution, b.bundle(b.violations[0]).evolution
    assert ea["introduced_at"] == eb["introduced_at"] and ea["introducing_commit"]["subject"] == eb["introducing_commit"]["subject"]


def test_heldout_adrs_avoid_every_primary_phrase(bench_root_heldout, bench_root):
    held = [open(p).read() for p in glob.glob(f"{bench_root_heldout}/*/repo/architecture/adr/*.md")]
    prim = [open(p).read() for p in glob.glob(f"{bench_root}/*/repo/architecture/adr/*.md")]
    assert held and not [t for t in held if PRIMARY_PHRASES.search(t)]
    assert [t for t in prim if PRIMARY_PHRASES.search(t)], "control: the primary wording does contain them"


@pytest.mark.parametrize("letter", LETTERS)
def test_heldout_retrieves_the_same_records_and_makes_the_same_policy_decisions(bench_cases, bench_cases_heldout, letter):
    """Only the decision LANGUAGE changed, so retrieval and the cheap policy must not."""
    pol = EvidenceGuidedPolicy()
    a, b = bench_cases[letter], bench_cases_heldout[letter]
    ba, bb = a.bundle(a.violations[0]), b.bundle(b.violations[0])
    assert [m.adr.id for m in ba.adrs] == [m.adr.id for m in bb.adrs]
    assert [m.adr.status for m in ba.adrs] == [m.adr.status for m in bb.adrs]
    assert pol.decide(ba).escalate == pol.decide(bb).escalate


def test_heldout_adr_text_actually_differs(bench_cases, bench_cases_heldout):
    for letter in "BCDEGJK":
        ta = bench_cases[letter].adrs[-1].text if bench_cases[letter].adrs else ""
        tb = bench_cases_heldout[letter].adrs[-1].text if bench_cases_heldout[letter].adrs else ""
        assert ta != tb, letter


def test_unknown_wording_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_case(str(tmp_path), "A01", "A_plain_violation", 7, wording="bogus")


def _targeted(rows):
    return [r for r in rows if r["truth"] != "conformant"][0]


def test_keyword_matching_breaks_on_held_out_wording_but_not_on_primary(bench_cases, bench_cases_heldout):
    """Why held-out wording matters: the keyword stand-in was written against the primary
    phrasing, so it reads B, C and J correctly there and fails on the same decisions
    expressed differently. A real model has to generalise where this cannot."""
    def correct(ctxs, letter):
        client = pipeline.TimedClient(FunctionClient(mock_model))
        t = _targeted(pipeline.run_evidence_guided(ctxs[letter], client))
        return t["predicted_violation"] == (t["truth"] == "violation")
    for letter in "BCJ":
        assert correct(bench_cases, letter), f"{letter}: primary"
        assert not correct(bench_cases_heldout, letter), f"{letter}: held-out should defeat keyword matching"
    for letter in "ADEFGHK":  # decided by default / by the cheap policy, so wording cannot hurt
        assert correct(bench_cases_heldout, letter), letter


# ------------------------------------------------------------------ prompt variants

FORBIDDEN_GUIDANCE = re.compile(r"grandfather|temporary|merely mentions|deadline|scope limit|superseded", re.I)


def test_minimal_prompts_contain_no_scenario_specific_guidance():
    for system in PROMPT_VARIANTS["minimal"]:
        assert not FORBIDDEN_GUIDANCE.search(system), system
        assert "JSON" in system  # still asks for the parseable format
    assert FORBIDDEN_GUIDANCE.search(PROMPT_VARIANTS["full"][0]), "control: the full prompt does contain it"


def test_variant_selects_the_system_prompt_actually_sent(bench_cases):
    ctx = bench_cases["C"]
    f = ctx.violations[0]
    seen = []
    client = FunctionClient(lambda s, p: (seen.append(s), '{"verdict":"violation"}')[1])
    for variant, expected in (("full", SYSTEM_REVIEW), ("minimal", SYSTEM_REVIEW_MINIMAL)):
        res = LLMSemanticAnalyzer(client, variant=variant).analyze(f, ctx.bundle(f))
        assert seen[-1] == expected and res["prompt_variant"] == variant


def test_edge_analyzer_also_supports_variants(bench_cases):
    ctx = bench_cases["B"]
    dep = ctx.findings[0].structural_evidence.dependency
    seen = []
    client = FunctionClient(lambda s, p: (seen.append(s), '{"verdict":"conformant"}')[1])
    res = LLMEdgeAnalyzer(client, variant="minimal").analyze_edge(
        snapshot_date=None, mapping_text="", rules_text="", adrs=[], source_path=dep.source,
        target_path=dep.target, import_reference=dep.raw_reference, code_snippet="")
    assert seen[0] == PROMPT_VARIANTS["minimal"][1] and res["prompt_variant"] == "minimal"


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError):
        LLMSemanticAnalyzer(FunctionClient(lambda s, p: ""), variant="nope")
    with pytest.raises(ValueError):
        LLMEdgeAnalyzer(FunctionClient(lambda s, p: ""), variant="nope")


def test_variant_changes_the_cache_key_so_runs_never_share_answers(tmp_path, bench_cases):
    from analysis.semantic.llm_client import CachingClient
    stub = FunctionClient(lambda s, p: '{"verdict":"violation"}')
    cc = CachingClient(stub, str(tmp_path / "c.sqlite"))
    ctx = bench_cases["C"]
    pipeline.run_full_hybrid(ctx, pipeline.TimedClient(cc), variant="full")
    pipeline.run_full_hybrid(ctx, pipeline.TimedClient(cc), variant="minimal")
    assert stub.calls == 2 and cc.hits == 0


def test_pipeline_threads_the_variant_through_every_llm_method(bench_cases):
    seen = set()
    client = pipeline.TimedClient(FunctionClient(lambda s, p: (seen.add(s), '{"verdict":"violation"}')[1]))
    ctx = bench_cases["C"]
    pipeline.run_full_hybrid(ctx, client, variant="minimal")
    pipeline.run_evidence_guided(ctx, client, variant="minimal")
    pipeline.run_generic_selective([ctx], client, 1, 0, "M4", variant="minimal")
    pipeline.run_llm_only(ctx, client, variant="minimal")
    assert seen == set(PROMPT_VARIANTS["minimal"])


# ------------------------------------------------------------------ A2: no intent

def test_no_intent_ablation_ignores_adrs_entirely(bench_cases):
    seen = []
    client = pipeline.TimedClient(FunctionClient(lambda s, p: (seen.append(p), '{"verdict":"violation"}')[1]))
    for letter, escalated in (("A", False), ("B", False), ("C", False), ("J", False), ("H", True)):
        rows = pipeline.run_evidence_guided(bench_cases[letter], client, method="A2", use_intent=False)
        assert _targeted(rows)["escalated"] is escalated, letter
    assert seen and all("<adr" not in p for p in seen), "ADR text must not reach the model in A2"


def test_no_intent_misses_the_justified_cases_that_need_a_record(bench_cases):
    client = pipeline.TimedClient(FunctionClient(mock_model))
    t = _targeted(pipeline.run_evidence_guided(bench_cases["B"], client, method="A2", use_intent=False))
    assert t["truth"] == "justified" and t["predicted_violation"] is True
