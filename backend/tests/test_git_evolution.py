"""GitEvolutionAnalyzer: the introducing commit must be the commit at which
the *dependency* appeared, not merely the latest commit that touched the file."""
from datetime import date

import pytest

from analysis.evolution.git_evolution import GitEvolutionAnalyzer
from experiments.benchmark.gitbuilder import GitBuilder

SRC, TGT = "app/services/pay_service.py", "app/database/connection.py"
CLEAN = "def pay():\n    return 1\n"
VIOLATING = "from app.database.connection import get_conn\n\n" + CLEAN


@pytest.fixture
def repo(tmp_path):
    g = GitBuilder(str(tmp_path / "r"))
    g.write("app/__init__.py", "")
    g.write("app/database/__init__.py", "")
    g.write(TGT, "def get_conn():\n    return object()\n")
    g.write("app/services/__init__.py", "")
    g.write(SRC, CLEAN)
    g.commit("initial scaffold", date(2026, 1, 5), "alice")
    return g


def analyze(g):
    return GitEvolutionAnalyzer().analyze_dependency(g.path, SRC, TGT)


def test_finds_introducing_commit_not_latest_touch(repo):
    """THE counter-example from the review of the teammate's git_miner: a
    violating import added in commit 2, followed by two unrelated edits. The
    answer must be commit 2, not commit 4."""
    repo.write(SRC, VIOLATING)
    intro_sha = repo.commit("Add refund lookup", date(2026, 2, 10), "bob")
    repo.append(SRC, "\n# tweak 1\n")
    repo.commit("unrelated tweak", date(2026, 3, 1), "alice")
    repo.append(SRC, "# tweak 2\n")
    repo.commit("another unrelated tweak", date(2026, 4, 1), "alice")

    ev = analyze(repo)
    assert ev["available"] and ev["present_at_head"]
    assert ev["introducing_commit"]["sha"] == intro_sha
    assert ev["introducing_commit"]["subject"] == "Add refund lookup"
    assert ev["introduced_at"].startswith("2026-02-10")
    assert ev["relevant_commits_since_introduction"] == 2
    assert ev["introduced_with_file_creation"] is False


def test_age_is_measured_to_head_commit_date_not_wall_clock(repo):
    repo.write(SRC, VIOLATING)
    repo.commit("add import", date(2026, 2, 1))
    repo.append(SRC, "# later\n")
    repo.commit("later edit", date(2026, 5, 2))
    ev = analyze(repo)
    assert ev["age_days"] == 90  # Feb 1 -> May 2, deterministic across machines
    assert ev["snapshot_date"].startswith("2026-05-02")


def test_born_violating_file_is_flagged(tmp_path):
    g = GitBuilder(str(tmp_path / "r"))
    g.write("app/__init__.py", "")
    g.write("app/database/__init__.py", "")
    g.write(TGT, "def get_conn():\n    return 1\n")
    g.write("app/services/__init__.py", "")
    g.write(SRC, VIOLATING)
    g.commit("everything at once", date(2026, 1, 5))
    ev = analyze(g)
    assert ev["introduced_with_file_creation"] is True


def test_removed_then_reintroduced_is_reported_with_current_run_start(repo):
    repo.write(SRC, VIOLATING)
    repo.commit("first add", date(2026, 2, 1))
    repo.write(SRC, CLEAN)
    repo.commit("remove it", date(2026, 3, 1))
    repo.write(SRC, VIOLATING)
    second = repo.commit("add it back", date(2026, 4, 1))

    ev = analyze(repo)
    assert ev["reintroduced"] is True
    assert ev["introducing_commit"]["sha"] == second
    assert ev["first_introduced_at"].startswith("2026-02-01")
    assert [e["change"] for e in ev["timeline"]] == ["introduced", "removed", "reintroduced"]


def test_dependency_absent_at_head_has_no_introducing_commit(repo):
    repo.write(SRC, VIOLATING)
    repo.commit("add", date(2026, 2, 1))
    repo.write(SRC, CLEAN)
    repo.commit("remove", date(2026, 3, 1))
    ev = analyze(repo)
    assert ev["present_at_head"] is False
    assert ev["introducing_commit"] is None


def test_message_signals_extracted(repo):
    repo.write(SRC, VIOLATING)
    repo.commit("TEMP workaround: read db directly for now (see ADR-9, #142)", date(2026, 2, 1))
    sig = analyze(repo)["message_signals"]
    assert "temp" in sig["temporary_language"] and "workaround" in sig["temporary_language"]
    assert "for now" in sig["temporary_language"]
    assert sig["adr_references"] == ["ADR-009"]
    assert sig["issue_references"] == ["#142"]


def test_ordinary_message_has_no_signals(repo):
    repo.write(SRC, VIOLATING)
    repo.commit("Add refund lookup", date(2026, 2, 1))
    sig = analyze(repo)["message_signals"]
    assert sig == {
        "temporary_language": [], "migration_language": [],
        "issue_references": [], "adr_references": [],
    }


def test_target_created_after_import_means_dependency_starts_when_target_exists(tmp_path):
    """If S imports a module that doesn't exist yet, the dependency can't be
    'present' until T exists. Resolution must use that commit's own file list."""
    g = GitBuilder(str(tmp_path / "r"))
    g.write("app/__init__.py", "")
    g.write("app/services/__init__.py", "")
    g.write(SRC, VIOLATING)  # imports app.database.connection, which doesn't exist yet
    g.commit("service first", date(2026, 1, 5))
    g.write("app/database/__init__.py", "")
    g.write(TGT, "def get_conn():\n    return 1\n")
    created = g.commit("database module lands", date(2026, 2, 5))
    ev = analyze(g)
    assert ev["introducing_commit"]["sha"] == created


def test_non_git_directory_is_reported_unavailable(tmp_path):
    ev = GitEvolutionAnalyzer().analyze_dependency(str(tmp_path), SRC, TGT)
    assert ev == {"available": False, "reason": "not a git repository"}


def test_empty_git_repo_is_reported_unavailable(tmp_path):
    GitBuilder(str(tmp_path / "r"))
    ev = GitEvolutionAnalyzer().analyze_dependency(str(tmp_path / "r"), SRC, TGT)
    assert ev["available"] is False


def test_analyze_accepts_a_finding(repo):
    from analysis.conformance.engine import analyze_conformance
    from analysis.dependency.repository_scanner import scan_repository
    from rules.loader import load_architecture_file
    import os, textwrap
    repo.write("architecture/rules.yaml", textwrap.dedent("""
        architecture: {name: t}
        component_mapping:
          services: {type: service}
          database: {type: database}
        rules:
          - {id: R004, name: no-svc-db, source: service, target: database, relation: forbidden, description: x}
    """))
    repo.write(SRC, VIOLATING)
    repo.commit("add", date(2026, 2, 1))
    arch, mapping = load_architecture_file(os.path.join(repo.path, "architecture/rules.yaml"))
    scan = scan_repository(repo.path, mapping)
    f = [x for x in analyze_conformance(scan.components, scan.dependencies, arch) if x.status.value == "violation"][0]
    ev = GitEvolutionAnalyzer().analyze(repo.path, f)
    assert ev["introducing_commit"]["subject"] == "add"


def test_works_when_analysis_root_is_a_subdirectory_of_the_repository(tmp_path):
    """Regression: `git show sha:path` resolves from the repository root, so an
    analysis root like <repo>/projects/shop (a monorepo folder, or a dataset
    living inside a larger repo) used to be reported as 'not present at HEAD'."""
    import os
    g = GitBuilder(str(tmp_path / "mono"))
    sub = "projects/shop/"
    g.write(sub + "app/__init__.py", "")
    g.write(sub + "app/database/__init__.py", "")
    g.write(sub + TGT, "def c():\n    return 1\n")
    g.write(sub + "app/services/__init__.py", "")
    g.write(sub + SRC, CLEAN)
    g.write("other/unrelated.py", "x = 1\n")
    g.commit("scaffold", date(2026, 1, 5))
    g.write(sub + SRC, VIOLATING)
    intro = g.commit("add direct db access", date(2026, 2, 5))
    ev = GitEvolutionAnalyzer().analyze_dependency(os.path.join(g.path, "projects/shop"), SRC, TGT)
    assert ev["present_at_head"] is True and ev["introducing_commit"]["sha"] == intro
