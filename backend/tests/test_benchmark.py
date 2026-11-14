"""The benchmark is only evidence if its labels are right. These tests verify
the generated repositories with the project's own analyzers."""
import json

import pytest

from analysis.evolution.git_evolution import GitEvolutionAnalyzer
from experiments.benchmark.generate import SCENARIOS, build_case
from experiments.pipeline import CaseContext

LETTERS = "ABCDEFGHJK"


def meta_of(bench_root, letter):
    return json.load(open(f"{bench_root}/{letter}01/labels.json"))


def test_scenario_counts_and_label_balance():
    assert sum(n for _, n in SCENARIOS.values()) == 60
    labels = [lab for lab, n in SCENARIOS.values() for _ in range(n)]
    assert labels.count("violation") == 42 and labels.count("justified") == 18


@pytest.mark.parametrize("letter", LETTERS)
def test_structural_engine_flags_exactly_the_targeted_edge(bench_cases, bench_root, letter):
    ctx = bench_cases[letter]
    meta = meta_of(bench_root, letter)
    assert [ctx.edge(f) for f in ctx.violations] == [(meta["target_edge"]["source"], meta["target_edge"]["target"])]
    assert ctx.violations[0].rule_id == meta["target_edge"]["rule_id"]


@pytest.mark.parametrize("letter", LETTERS)
def test_labels_cover_every_governed_edge(bench_cases, letter):
    ctx = bench_cases[letter]
    assert {ctx.edge(f) for f in ctx.findings} == set(ctx.truth)
    assert sum(1 for v in ctx.truth.values() if v == "conformant") == 6


@pytest.mark.parametrize("letter", LETTERS)
def test_evolution_analyzer_recovers_the_scripted_introduction_date(bench_cases, bench_root, letter):
    ctx, meta = bench_cases[letter], meta_of(bench_root, letter)
    ev = GitEvolutionAnalyzer().analyze(ctx.repo, ctx.violations[0])
    assert ev["introduced_at"][:10] == meta["intended_intro_date"]
    assert ev["snapshot_date"][:10] == meta["snapshot_date"]
    # an unrelated commit touched the source file afterwards, so 'latest touch' would be wrong
    assert ev["relevant_commits_since_introduction"] >= 1


def test_grandfather_scenarios_are_decided_by_intro_date_relative_to_their_own_cutoff(bench_root):
    c, d = meta_of(bench_root, "C"), meta_of(bench_root, "D")
    assert c["intended_intro_date"] <= c["grandfather_cutoff"] and c["label"] == "justified"
    assert d["intended_intro_date"] > d["grandfather_cutoff"] and d["label"] == "violation"


def test_generation_is_deterministic(tmp_path):
    def head(root):
        import subprocess
        build_case(str(root), "J01", "J_adr_cited_by_commit_only", 7)
        return subprocess.run(["git", "-C", f"{root}/J01/repo", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert head(tmp_path / "a") == head(tmp_path / "b")


def test_different_seed_gives_different_repository(tmp_path):
    import subprocess
    def head(seed, root):
        build_case(str(root), "A01", "A_plain_violation", seed)
        return subprocess.run(["git", "-C", f"{root}/A01/repo", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert head(1, tmp_path / "a") != head(2, tmp_path / "b")


def test_j_adr_shares_no_wording_with_the_dependency(bench_cases):
    """The point of scenario J: text-based relevance must NOT find the ADR."""
    ctx = bench_cases["J"]
    assert ctx.bundle(ctx.violations[0], use_evolution=False).adrs == []


def test_h_has_temporary_language_and_no_adr(bench_cases):
    ctx = bench_cases["H"]
    b = ctx.bundle(ctx.violations[0])
    assert b.adrs == [] and b.evolution["message_signals"]["temporary_language"]


def test_noise_adrs_are_never_relevant(bench_cases):
    for letter in "AH":  # no principal ADR in these scenarios
        ctx = bench_cases[letter]
        assert ctx.bundle(ctx.violations[0]).adrs == []
