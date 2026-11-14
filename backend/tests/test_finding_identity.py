"""Finding identity: stable keys, contiguous per-run ids, run-scoped lookup.

These guard the bugs found when reviewing the mid-viva code:
  * ids were derived from dependency list position, so they skipped numbers
    and changed whenever code changed;
  * the store kept one global dict keyed by id, so a second analysis run
    silently overwrote the first run's findings.
Milestone 2 (evolution tracing) needs `Finding.key` to follow one logical
finding across commits, so the key must survive unrelated edits.
"""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from analysis.conformance.engine import analyze_conformance
from analysis.dependency.repository_scanner import scan_repository
from main import app
from rules.loader import load_architecture_file
from tests.conftest import ARCH_FILE, REPO_ROOT


def _findings(repo_root):
    architecture, mapping = load_architecture_file(ARCH_FILE)
    scan = scan_repository(repo_root, mapping)
    return analyze_conformance(scan.components, scan.dependencies, architecture)


def test_ids_are_contiguous_from_one():
    findings = _findings(REPO_ROOT)
    assert [f.id for f in findings] == [f"F{i:03d}" for i in range(1, len(findings) + 1)]


def test_keys_are_unique_and_nonempty():
    findings = _findings(REPO_ROOT)
    keys = [f.key for f in findings]
    assert all(keys)
    assert len(keys) == len(set(keys))


def test_key_encodes_rule_source_and_target():
    violation = next(f for f in _findings(REPO_ROOT) if f.status.value == "violation")
    rule_id, source, target = violation.key.split("|")
    assert rule_id == violation.rule_id
    assert source == violation.source["id"]
    assert target == violation.target["id"]


def test_keys_survive_unrelated_edits_that_move_line_numbers(tmp_path):
    """Prepending lines moves every line number but must not change any key."""
    copy = tmp_path / "repo"
    shutil.copytree(REPO_ROOT, copy)
    before = {f.key: f.location for f in _findings(str(copy))}

    victim = copy / "backend" / "services" / "payment_service.py"
    victim.write_text("# unrelated header\n# another comment\n\n" + victim.read_text())
    after = {f.key: f.location for f in _findings(str(copy))}

    assert set(before) == set(after)
    moved = [k for k in before if before[k] != after[k]]
    assert moved, "test is vacuous unless at least one location actually moved"


@pytest.fixture
def client():
    return TestClient(app)


def _analyze(client):
    resp = client.post(
        "/repositories/analyze",
        json={"repository_path": REPO_ROOT, "architecture_file": ARCH_FILE},
    )
    assert resp.status_code == 200
    return resp.json()["analysis_id"]


def test_second_run_does_not_overwrite_first_runs_findings(client):
    first, second = _analyze(client), _analyze(client)
    assert first != second
    a = client.get(f"/analysis/{first}/findings/F001").json()
    b = client.get(f"/analysis/{second}/findings/F001").json()
    assert a["analysis_id"] == first
    assert b["analysis_id"] == second


def test_scoped_endpoint_404s_for_wrong_run(client):
    run = _analyze(client)
    assert client.get(f"/analysis/{run}/findings/F999").status_code == 404
    assert client.get("/analysis/A9999/findings/F001").status_code == 404


def test_legacy_endpoint_resolves_to_latest_run(client):
    _analyze(client)
    latest = _analyze(client)
    assert client.get("/findings/F001").json()["analysis_id"] == latest
