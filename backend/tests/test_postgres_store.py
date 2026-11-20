"""PostgreSQL storage (synopsis tech stack), tested against a REAL PostgreSQL server, not a mock.

The server is an embedded PostgreSQL started by the `pgserver` package, or the one named by POSTGRES_TEST_URL. If neither is available the
tests are skipped (the rest of the suite needs no database). The key test runs the same API flow on the memory store and on PostgreSQL and
requires identical answers.
"""
import json
import os
import re
import tempfile

import pytest

from analysis.semantic.llm_client import FunctionClient
from api.routes import analyze as routes
from experiments.mock_llm import mock_model
from models.finding import Finding
from storage import store as lazy_store

psycopg = pytest.importorskip("psycopg", reason="psycopg is not installed")
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from storage.postgres_store import PostgresStore  # noqa: E402


@pytest.fixture(scope="module")
def pg_dsn():
    url = os.environ.get("POSTGRES_TEST_URL")
    if url:
        yield url
        return
    try:
        import pgserver
        srv = pgserver.get_server(tempfile.mkdtemp(prefix="pgtest_"))
    except Exception as e:  # not installed, or cannot start here
        pytest.skip(f"no PostgreSQL available for tests ({type(e).__name__}); set POSTGRES_TEST_URL or pip install pgserver")
    yield srv.get_uri()
    srv.cleanup()


@pytest.fixture
def pg(pg_dsn):
    with psycopg.connect(pg_dsn, autocommit=True) as c:  # a clean database for every test
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    return PostgresStore(pg_dsn)


@pytest.fixture
def api_on(pg):
    """Run the API on PostgreSQL; always put the default (memory) store back afterwards."""
    lazy_store.reset(pg)
    yield TestClient(app)
    lazy_store.reset()


def post_analyze(client, bench_root, letter):
    r = client.post("/repositories/analyze", json={"repository_path": f"{bench_root}/{letter}01/repo",
                                                    "architecture_file": f"{bench_root}/{letter}01/repo/architecture/rules.yaml"})
    assert r.status_code == 200
    return r.json()


def violation(body):
    return next(f["id"] for f in body["findings"] if f["status"] == "violation")


def normalise(obj):
    """Run ids differ between stores (and between tests); everything else must be identical."""
    return json.loads(re.sub(r"A\d{4}", "A####", json.dumps(obj, sort_keys=True)))


# ---------------------------------------------------------------- storage behaviour

def test_a_saved_run_round_trips_exactly(pg, api_on, bench_root):
    body = post_analyze(api_on, bench_root, "C")
    run = pg.get(body["analysis_id"])
    assert run is not None and len(run.components) and len(run.dependencies) and len(run.findings) == len(body["findings"])
    assert run.graph.number_of_nodes() == len(run.components) and run.graph.number_of_edges()  # rebuilt from components + dependencies
    again = PostgresStore(pg.dsn).get(body["analysis_id"])  # a "restarted" process reading the same database
    assert [f.to_dict() for f in again.findings] == [f.to_dict() for f in run.findings]
    assert again.architecture.to_dict() == run.architecture.to_dict()


def test_evidence_and_decisions_attached_later_survive_a_restart(pg, api_on, bench_root, monkeypatch):
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(mock_model, "stub"))
    body = post_analyze(api_on, bench_root, "C")
    aid, fid = body["analysis_id"], violation(body)
    assert api_on.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid}).status_code == 200
    f = PostgresStore(pg.dsn).get_finding(fid, aid)  # a new store instance, i.e. a fresh process
    assert f.decision["resolution"] == "extract_compute" and f.semantic_analysis["mode"] == "extract_compute"
    assert f.evolution_evidence and f.architectural_intent["adrs"]  # evidence gathered on the way was persisted too


def test_ids_are_unique_and_increasing_and_survive_restarts(pg):
    ids = [pg.next_id() for _ in range(3)] + [PostgresStore(pg.dsn).next_id()]
    assert ids == sorted(ids) and len(set(ids)) == 4 and all(re.fullmatch(r"A\d{4}", i) for i in ids)


def test_finding_ids_repeat_across_runs_and_the_legacy_lookup_returns_the_latest(pg, api_on, bench_root):
    a = post_analyze(api_on, bench_root, "A")
    b = post_analyze(api_on, bench_root, "B")
    fa, fb = violation(a), violation(b)
    assert pg.get_finding(fa, a["analysis_id"]).analysis_id == a["analysis_id"]
    latest = pg.get_finding(fb)  # no analysis_id: most recent run that has this per-run id
    assert latest.analysis_id == b["analysis_id"]
    assert pg.get_finding("F999") is None and pg.get("A9999") is None


def test_saving_the_same_run_twice_replaces_it(pg, api_on, bench_root):
    body = post_analyze(api_on, bench_root, "A")
    run = pg.get(body["analysis_id"])
    pg.save(run)
    pg.save(run)
    with psycopg.connect(pg.dsn) as c:
        assert c.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM findings").fetchone()[0] == len(run.findings)


def test_a_failed_save_leaves_nothing_behind(pg, api_on, bench_root):
    """One transaction: a run that cannot be serialised is not stored at all (no orphan components or findings)."""
    body = post_analyze(api_on, bench_root, "A")
    run = pg.get(body["analysis_id"])
    run.id = "A7777"
    run.findings[0].semantic_analysis = {"bad": object()}
    with pytest.raises(TypeError):
        pg.save(run)
    assert pg.get("A7777") is None
    with psycopg.connect(pg.dsn) as c:
        assert c.execute("SELECT count(*) FROM components WHERE analysis_id = 'A7777'").fetchone()[0] == 0


def test_summaries_are_computed_in_sql_and_match_the_run(pg, api_on, bench_root):
    body = post_analyze(api_on, bench_root, "C")
    summary = pg.list_summaries()[0]
    run = pg.get(body["analysis_id"])
    assert summary == run.summary()


def test_health_reports_the_backend(api_on):
    assert api_on.get("/health").json() == {"status": "ok", "storage": {"backend": "postgresql", "ok": True}}


def test_health_reports_a_dead_database_instead_of_crashing():
    lazy_store.reset(PostgresStore("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1"))
    try:
        body = TestClient(app).get("/health").json()
        assert body["status"] == "ok" and body["storage"]["backend"] == "postgresql" and body["storage"]["ok"] is False
    finally:
        lazy_store.reset()


# ---------------------------------------------------------------- the key test

def flow(client, bench_root, letter, monkeypatch):
    """One complete user journey through the API; returns everything an API client could observe."""
    monkeypatch.setattr(routes, "get_llm_client", lambda: FunctionClient(mock_model, "stub"))
    body = post_analyze(client, bench_root, letter)
    aid, fid = body["analysis_id"], violation(body)
    out = {"analysis": body, "list": client.get("/analysis").json(), "one": client.get(f"/analysis/{aid}").json(),
           "finding_before": client.get(f"/analysis/{aid}/findings/{fid}").json(),
           "evidence": client.get(f"/findings/{fid}/evidence", params={"analysis_id": aid}).json(),
           "evolution": client.get(f"/findings/{fid}/evolution", params={"analysis_id": aid}).json(),
           "semantic": client.post(f"/findings/{fid}/semantic-analysis", params={"analysis_id": aid}).json()}
    out["finding_after"] = client.get(f"/analysis/{aid}/findings/{fid}").json()
    return out


@pytest.mark.parametrize("letter", ["A", "C", "D", "F"])
def test_the_same_journey_gives_identical_answers_on_memory_and_postgresql(pg, bench_root, monkeypatch, letter):
    lazy_store.reset()
    memory = normalise(flow(TestClient(app), bench_root, letter, monkeypatch))
    lazy_store.reset(pg)
    try:
        postgres = normalise(flow(TestClient(app), bench_root, letter, monkeypatch))
    finally:
        lazy_store.reset()
    for key in memory:
        # timestamps and per-call timings legitimately differ; compare the substance
        strip = lambda o: json.loads(re.sub(r'"(created_at|latency_s)": [^,}]+', '"\\1": 0', json.dumps(o)))
        assert strip(postgres[key]) == strip(memory[key]), key
