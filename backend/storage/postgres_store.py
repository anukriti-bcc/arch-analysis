"""PostgreSQL storage for analysis runs (optional; the default store is in-memory).

Same interface as `memory_store._MemoryStore`, selected by the DATABASE_URL environment variable (see storage/__init__.py).

Schema (created on first use, idempotent): one row per run, and one row per component, dependency and finding, each with a typed key
and a JSONB payload. JSONB for the payloads keeps the evidence slots (structural, intent, evolution, semantic, decision) free to grow
without migrations, which is what the Finding object was designed for; the typed keys make runs and findings queryable and indexed.

    analysis_runs(id, seq, repository_path, architecture_name, created_at, external_imports, architecture)
    components(analysis_id, ord, data)           dependencies(analysis_id, ord, data)
    findings(analysis_id, id, ord, data)         -- primary key (analysis_id, id); per-run ids such as F001 repeat across runs

The dependency graph is NOT stored: it is derived from components and dependencies and rebuilt on load.

Design notes: a connection is opened per operation (simple and thread-safe; fine at this scale; a pool is the obvious next step);
`save` is one transaction, so a run is stored completely or not at all; `update_finding` persists evidence attached after the run
was saved (the in-memory store gets this for free because it shares the object).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum

import psycopg
from psycopg.types.json import Jsonb

from analysis.dependency.graph import build_dependency_graph
from models.component import Component, Dependency
from models.finding import Finding
from models.rule import Architecture
from storage.memory_store import AnalysisRun

SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS analysis_seq;
CREATE TABLE IF NOT EXISTS analysis_runs (
    id                TEXT PRIMARY KEY,
    seq               BIGINT NOT NULL,
    repository_path   TEXT NOT NULL,
    architecture_name TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    external_imports  JSONB NOT NULL,
    architecture      JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS components (
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    ord         INT  NOT NULL,
    data        JSONB NOT NULL,
    PRIMARY KEY (analysis_id, ord)
);
CREATE TABLE IF NOT EXISTS dependencies (
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    ord         INT  NOT NULL,
    data        JSONB NOT NULL,
    PRIMARY KEY (analysis_id, ord)
);
CREATE TABLE IF NOT EXISTS findings (
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    id          TEXT NOT NULL,
    ord         INT  NOT NULL,
    status      TEXT NOT NULL,
    data        JSONB NOT NULL,
    PRIMARY KEY (analysis_id, id)
);
CREATE INDEX IF NOT EXISTS findings_status_idx ON findings (analysis_id, status);
"""


def _default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    raise TypeError(f"{type(o).__name__} is not JSON serialisable")


def _jsonb(obj) -> Jsonb:
    """JSONB payload; dates become ISO strings (the API already exposes them that way). Anything else unserialisable fails loudly."""
    return Jsonb(obj, dumps=lambda x: json.dumps(x, default=_default))


class PostgresStore:
    backend = "postgresql"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._ready = False

    # ---------------------------------------------------------------- plumbing
    def _connect(self):
        conn = psycopg.connect(self.dsn)
        if not self._ready:
            with conn.transaction():
                conn.execute(SCHEMA)
            self._ready = True
        return conn

    def next_id(self) -> str:
        with self._connect() as conn:
            n = conn.execute("SELECT nextval('analysis_seq')").fetchone()[0]
        return f"A{n:04d}"

    # ---------------------------------------------------------------- write
    def save(self, run: AnalysisRun) -> None:
        for f in run.findings:
            f.analysis_id = run.id
        with self._connect() as conn, conn.transaction():
            conn.execute("DELETE FROM analysis_runs WHERE id = %s", [run.id])  # cascades: saving the same id again replaces it
            seq = int(run.id[1:]) if run.id[1:].isdigit() else conn.execute("SELECT nextval('analysis_seq')").fetchone()[0]
            conn.execute("INSERT INTO analysis_runs (id, seq, repository_path, architecture_name, created_at, external_imports, architecture) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                         [run.id, seq, run.repository_path, run.architecture_name, run.created_at, _jsonb(run.external_imports),
                          _jsonb(run.architecture.to_dict())])
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO components (analysis_id, ord, data) VALUES (%s, %s, %s)",
                                [(run.id, i, _jsonb(c.to_dict())) for i, c in enumerate(run.components)])
                cur.executemany("INSERT INTO dependencies (analysis_id, ord, data) VALUES (%s, %s, %s)",
                                [(run.id, i, _jsonb(d.to_dict())) for i, d in enumerate(run.dependencies)])
                cur.executemany("INSERT INTO findings (analysis_id, id, ord, status, data) VALUES (%s, %s, %s, %s, %s)",
                                [(run.id, f.id, i, f.status.value, _jsonb(f.to_dict())) for i, f in enumerate(run.findings)])

    def update_finding(self, finding: Finding) -> None:
        """Persist evidence, semantic analysis or a decision attached to a finding after its run was saved."""
        if finding.analysis_id is None:
            return
        with self._connect() as conn:
            conn.execute("UPDATE findings SET status = %s, data = %s WHERE analysis_id = %s AND id = %s",
                         [finding.status.value, _jsonb(finding.to_dict()), finding.analysis_id, finding.id])

    # ---------------------------------------------------------------- read
    def get(self, analysis_id: str) -> AnalysisRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id, repository_path, architecture_name, created_at, external_imports, architecture "
                               "FROM analysis_runs WHERE id = %s", [analysis_id]).fetchone()
            if row is None:
                return None
            comps = [Component.from_dict(r[0]) for r in conn.execute("SELECT data FROM components WHERE analysis_id = %s ORDER BY ord", [analysis_id])]
            deps = [Dependency.from_dict(r[0]) for r in conn.execute("SELECT data FROM dependencies WHERE analysis_id = %s ORDER BY ord", [analysis_id])]
            findings = [Finding.from_dict(r[0]) for r in conn.execute("SELECT data FROM findings WHERE analysis_id = %s ORDER BY ord", [analysis_id])]
        return AnalysisRun(id=row[0], repository_path=row[1], architecture_name=row[2], created_at=row[3], components=comps, dependencies=deps,
                           architecture=Architecture.from_dict(row[5]), findings=findings, graph=build_dependency_graph(comps, deps),
                           external_imports=row[4])

    def list_summaries(self) -> list[dict]:
        """Run summaries computed in SQL, without loading every run."""
        q = """SELECT r.id, r.repository_path, r.architecture_name, r.created_at,
                      (SELECT count(*) FROM components c WHERE c.analysis_id = r.id),
                      (SELECT count(*) FROM dependencies d WHERE d.analysis_id = r.id),
                      jsonb_array_length(r.architecture -> 'rules'),
                      (SELECT count(*) FROM findings f WHERE f.analysis_id = r.id),
                      (SELECT count(*) FROM findings f WHERE f.analysis_id = r.id AND f.status = 'violation')
               FROM analysis_runs r ORDER BY r.seq"""
        with self._connect() as conn:
            rows = conn.execute(q).fetchall()
        return [{"analysis_id": a, "repository": b, "architecture": c, "created_at": d, "components": e, "dependencies": f, "rules": g,
                 "findings": h, "violations": i} for a, b, c, d, e, f, g, h, i in rows]

    def get_finding(self, finding_id: str, analysis_id: str | None = None) -> Finding | None:
        with self._connect() as conn:
            if analysis_id is not None:
                row = conn.execute("SELECT data FROM findings WHERE analysis_id = %s AND id = %s", [analysis_id, finding_id]).fetchone()
            else:  # legacy lookup: finding ids repeat across runs, so take the most recent run that has it
                row = conn.execute("SELECT f.data FROM findings f JOIN analysis_runs r ON r.id = f.analysis_id WHERE f.id = %s "
                                   "ORDER BY r.seq DESC LIMIT 1", [finding_id]).fetchone()
        return Finding.from_dict(row[0]) if row else None

    def ping(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1").fetchone()[0] == 1
