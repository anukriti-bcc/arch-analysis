"""The real-ADR case study kit: pinned and verified ADR text, the real extraction path, M6 run two ways."""
import hashlib
import json

import pandas as pd
import pytest

from analysis.semantic.llm_client import FunctionClient
from experiments.real_adrs import case_study as cs

ADR = ("# ADR-9: Telemetry gateway\n\n## Status\n\nAccepted\n\n## Decision\n\nAll OpenTelemetry access goes through `src/app/telemetry.py`. "
       "The rest of the codebase must not import opentelemetry directly.")


def row(**kw):
    base = {"case_id": "T1", "repo": "o/r", "commit": "abc", "adr_path": "docs/adr/0009-telemetry.md",
            "adr_sha256": hashlib.sha256(ADR.encode()).hexdigest(), "source_path": "src/app/core.py", "source_type": "core",
            "target_path": "opentelemetry", "target_type": "observability", "import_reference": "opentelemetry",
            "code_snippet": "import opentelemetry", "rule_description": "No direct opentelemetry imports.", "expected": "violation", "debatable": "no"}
    return {**base, **kw}


def client(decision="prohibits", limit="none", date=None):
    return FunctionClient(lambda s, p: json.dumps({"adr_id": "ADR-9", "decision": decision, "covers_this_dependency": "yes", "limit": limit,
                                                   "limit_date": date, "explanation": "read it"}), "fake")


@pytest.fixture(autouse=True)
def local_adr(monkeypatch):
    monkeypatch.setattr(cs, "urlopen_text", lambda url: ADR.encode(), raising=False)
    monkeypatch.setattr(cs.urllib.request, "urlopen", lambda *a, **k: type("R", (), {"read": lambda self: ADR.encode(), "__enter__": lambda self: self,
                                                                                      "__exit__": lambda self, *x: None})())


def test_the_adr_text_is_verified_against_its_recorded_hash():
    assert cs.load_adr_text(row()) == ADR
    with pytest.raises(ValueError, match="SHA-256"):
        cs.load_adr_text(row(adr_sha256="0" * 64))


def test_raw_url_points_at_the_pinned_commit():
    assert cs.raw_url("o/r", "abc123", "docs/adr/1.md") == "https://raw.githubusercontent.com/o/r/abc123/docs/adr/1.md"


def test_violation_case_is_decided_by_the_extraction_and_code():
    out = cs.run_case(row(), client("prohibits"))
    assert out["m7"] == "violation" and out["m7_correct"] and out["m7_parsed_ok"] and out["m7_decision"] == "prohibits"
    assert out["m6_reading_only"] in ("violation", "unclear", "justified") and out["m6_pipeline"] in ("violation", "justified")


def test_justified_case_and_an_unparseable_reply_is_a_labelled_fallback():
    ok = cs.run_case(row(expected="justified"), client("permits"))
    assert ok["m7"] == "justified" and ok["m7_correct"]
    bad = cs.run_case(row(), FunctionClient(lambda s, p: "no idea", "garbled"))
    assert bad["m7"] == "fallback" and not bad["m7_parsed_ok"] and not bad["m7_correct"]


def test_m6_is_reported_both_as_the_pipeline_runs_it_and_reading_only():
    out = cs.run_case(row(source_path="src/app/telemetry.py"), client())
    # the relevance matcher selects this ADR only when it names BOTH ends (here the gateway file and opentelemetry); reading-only forces the scope in
    assert out["matcher_selected"] is True and "file_names" in out["matcher_reasons"]
    unrelated = cs.run_case(row(source_path="src/x/y.py", source_type="zzz", target_path="sqlalchemy", target_type="db"), client())
    assert unrelated["matcher_selected"] is False and unrelated["m6_pipeline"] == "violation"


def test_the_committed_cases_file_is_well_formed():
    cases = pd.read_csv("../datasets/real_adrs_case_study/cases.csv", dtype=str).fillna("")
    assert all(c in cases.columns for c in cs.REQUIRED) and cases.case_id.is_unique
    assert set(cases.expected) <= {"violation", "justified"} and set(cases.debatable) <= {"yes", "no"}
    assert cases.adr_sha256.str.fullmatch(r"[0-9a-f]{64}").all() and cases.commit.str.fullmatch(r"[0-9a-f]{40}").all()
    assert (cases.reviewed_by_team == "").all()  # the draft has not been reviewed yet; the team fills this column
