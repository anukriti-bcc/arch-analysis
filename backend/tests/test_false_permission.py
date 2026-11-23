"""The false-permission probe: case construction, classification, routing, scoring, freeze. Offline: fabricated ADR text, stub model."""
import json
import os

import pandas as pd
import pytest

from analysis.semantic.llm_client import FunctionClient
from experiments.real_adrs import false_permission as fp

SHEET, MANIFEST = fp.DEFAULT_SHEET, fp.DEFAULT_MANIFEST
HAVE_REAL = os.path.exists(SHEET) and os.path.exists(MANIFEST)

P1, P2 = fp.PAIRS[0], fp.PAIRS[1]
TEXTS = {
    "unrelated": "# 3. Use Luxon for dates\n\nDate: 2021-01-01\n\n## Status\nAccepted\n\n## Context\nWe need a date library.\n\n## Decision\nWe will use Luxon for all date handling.\n",
    "weak": "# 4. Layers\n\n## Status\nAccepted\n\n## Context\nControllers are thin.\n\n## Decision\nThe controller layer is tested against a repository fake.\n",
    "described": "# 5. Orders\n\n## Status\nAccepted\n\n## Context\nOrders.\n\n## Decision\nThe order controller may use the order repository directly. This is acceptable.\n",
    "conditional": "# 8. Orders\n\n## Status\nAccepted\n\n## Context\nOrders.\n\n## Decision\nThe order controller may use the order repository directly unless a service exists.\n",
    "mixed": "# 6. Jobs\n\n## Status\nAccepted\n\n## Context\nx\n\n## Decision\n`export_job` may use the database directly. Everything else goes through repositories.\n",
    "rejected": "# 7. Old\n\n## Status\nRejected\n\n## Decision\nWe will use Luxon.\n",
}


def row(pair=P1, **kw):
    return {**pair, "case_id": "T1", "stratum": fp.PRIMARY, "repo": "x/y", "commit": "c", "adr_path": "docs/adr/0001-x.md", "adr_sha256": "",
            "sheet_status": "accepted", **kw}


def stub(decision="does_not_address", covers="no", limit="none", raw=None):
    body = raw if raw is not None else json.dumps({"adr_id": None, "decision": decision, "covers_this_dependency": covers, "limit": limit,
                                                   "limit_date": None, "explanation": "stub"})
    return FunctionClient(lambda s, p: body)


def run(text_key, client, **kw):
    return fp.run_case(row(**kw), client, loader=lambda r, c: TEXTS[text_key])


# ---------------------------------------------------------------- statistics
def test_wilson_matches_the_closed_form_for_zero_successes():
    lo, hi = fp.wilson(0, 44)
    assert lo == pytest.approx(0.0, abs=1e-12) and hi == pytest.approx(1.96 ** 2 / (44 + 1.96 ** 2), abs=1e-9)
    assert 0.079 < hi < 0.082  # about 8%: what "0 of 44" can rule out


def test_wilson_is_centred_sensibly_and_handles_edges():
    lo, hi = fp.wilson(5, 44)
    assert 0.04 < lo < 0.06 and 0.23 < hi < 0.25  # 5/44 = 11.4%; interval straddles it
    assert lo < 5 / 44 < hi
    assert fp.wilson(44, 44)[1] == pytest.approx(1.0) and fp.wilson(0, 0) == (0.0, 0.0)


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("decision,covers,expected", [
    ("permits", "yes", "dangerous"),
    ("permits", "unclear", "misleading"),
    ("prohibits", "yes", "misleading"),
    ("prohibits", "unclear", "misleading"),
    ("permits", "no", "correct"),
    ("prohibits", "no", "correct"),
    ("does_not_address", "yes", "correct"),
    ("does_not_address", "no", "correct"),
    ("does_not_address", "unclear", "correct"),
])
def test_classify(decision, covers, expected):
    assert fp.classify({"decision": decision, "covers_this_dependency": covers}) == expected


def test_classify_no_reply_is_failure_not_a_verdict():
    assert fp.classify(None) == "failure"


@pytest.mark.parametrize("n,expected", [(0, "LOW"), (2, "LOW"), (3, "MODERATE"), (4, "MODERATE"), (5, "HIGH"), (20, "HIGH")])
def test_band_thresholds_are_the_preregistered_ones(n, expected):
    assert fp.band(n) == expected


# ---------------------------------------------------------------- one case: model path
def test_permission_on_an_unrelated_adr_is_dangerous_and_flips_the_raw_verdict():
    r = run("unrelated", stub("permits", "yes"))
    assert (r["raw_class"], r["raw_outcome"]) == ("dangerous", "justified")


def test_does_not_address_is_correct_and_keeps_the_violation():
    r = run("unrelated", stub("does_not_address", "no"))
    assert (r["raw_class"], r["raw_outcome"], r["pipeline_verdict"]) == ("correct", "violation", "violation")


def test_unparseable_reply_is_a_failure_that_keeps_the_structural_verdict():
    r = run("unrelated", stub(raw="I think this is fine."))
    assert r["raw_class"] == "failure" and r["parsed_ok"] is False and r["pipeline_verdict"] == "violation"


def test_provider_error_is_a_failure_not_a_permission():
    r = run("unrelated", FunctionClient(lambda s, p: (_ for _ in ()).throw(RuntimeError("boom"))))
    assert r["raw_class"] == "failure" and r["error"]


def test_attribution_check_rejects_a_permission_that_belongs_to_another_module():
    r = run("mixed", stub("permits", "yes"))
    assert r["raw_class"] == "dangerous" and r["attr_class"] == "correct" and r["attr_note"].startswith("rejected")


def test_attribution_check_does_not_apply_when_nothing_names_another_module():
    r = run("unrelated", stub("permits", "yes"))
    assert r["attr_class"] == "dangerous" and not r["attr_note"].startswith("rejected")


# ---------------------------------------------------------------- one case: routing
def test_an_adr_the_matcher_does_not_select_never_reaches_the_policy():
    r = run("unrelated", stub("permits", "yes"))
    assert (r["matcher_selected"], r["route"], r["pipeline_verdict"], r["pipeline_false_justified"]) == (False, "direct_structural", "violation", False)


def test_type_words_alone_do_not_trigger_a_call():
    r = run("weak", stub("permits", "yes"))
    assert r["matcher_selected"] and r["route"] == "direct_structural" and not r["pipeline_false_justified"]


def test_a_code_reader_permission_without_a_model_counts_as_a_pipeline_false_justification():
    r = run("described", stub("does_not_address", "no"))
    assert r["route"] == "direct_code" and r["route_verdict"] == "justified"
    assert r["pipeline_false_justified"] is True and r["raw_class"] == "correct"  # the model was right; the code path was wrong


def test_an_escalated_case_takes_the_model_answer_with_attribution():
    permits = run("conditional", stub("permits", "yes"))
    assert permits["route"] == "escalate" and permits["pipeline_false_justified"] is True
    safe = run("conditional", stub("does_not_address", "no"))
    assert safe["route"] == "escalate" and safe["pipeline_verdict"] == "violation"


def test_inactive_adr_is_flagged_inactive():
    r = run("rejected", stub("does_not_address", "no"), stratum=fp.INACTIVE_CONTROL, sheet_status="rejected")
    assert r["adr_active"] is False and r["adr_status"] == "rejected"


def test_pipeline_verdict_rule():
    assert fp.pipeline_verdict("escalate", "", "justified") == "justified"
    assert fp.pipeline_verdict("escalate", "", "unresolved") == "violation"
    assert fp.pipeline_verdict("direct_code", "justified", "violation") == "justified"
    assert fp.pipeline_verdict("direct_structural", "violation", "justified") == "violation"


# ---------------------------------------------------------------- scoring
def results_frame(spec):
    """spec: list of (stratum, raw_class, attr_class, route, matcher_selected, pair, route_verdict)"""
    rows = []
    for i, (stratum, rc, ac, route, sel, pair, rv) in enumerate(spec):
        oc = lambda c: "justified" if c == "dangerous" else "violation"
        pv = fp.pipeline_verdict(route, rv, oc(ac))
        rows.append(dict(case_id=f"C{i}", stratum=stratum, pair_id=pair, repo="r", adr=f"a{i}.md", sheet_status="accepted", matcher_selected=sel,
                         route=route, route_verdict=rv, raw_class=rc, raw_outcome=oc(rc), attr_class=ac, attr_outcome=oc(ac), attr_note="",
                         decision="permits" if rc == "dangerous" else "does_not_address", covers="yes" if rc == "dangerous" else "no", explanation="e",
                         pipeline_verdict=pv, pipeline_false_justified=pv == "justified"))
    return pd.DataFrame(rows)


def test_score_counts_and_bands():
    spec = ([(fp.PRIMARY, "dangerous", "correct", "direct_structural", False, "P1", "violation")] * 2
            + [(fp.PRIMARY, "misleading", "misleading", "direct_structural", False, "P2", "violation")]
            + [(fp.PRIMARY, "correct", "correct", "escalate", True, "P2", "")] * 5
            + [(fp.PRIMARY, "failure", "failure", "direct_structural", False, "P3", "violation")]
            + [(fp.INACTIVE_CONTROL, "dangerous", "dangerous", "direct_structural", False, "P1", "violation")])
    s = fp.score(results_frame(spec), n_excluded_empty=1)
    assert (s["n_primary"], s["n_inactive_control"], s["n_excluded_empty"]) == (9, 1, 1)
    assert s["model_raw"]["dangerous"]["k"] == 2 and s["model_raw"]["misleading"]["k"] == 1 and s["model_raw"]["failure"] == 1
    assert s["model_raw"]["any_false_attribution"]["k"] == 3
    assert s["model_with_attribution"]["dangerous"]["k"] == 0
    assert s["routing"]["escalate"] == 5 and s["routing"]["direct_structural"] == 4
    assert s["pipeline"]["false_justified"]["k"] == 0 and s["band"] == "LOW"
    assert s["inactive_control"]["dangerous"] == 1  # reported apart, never in the primary rate
    assert s["strata"]["pair"]["P1"] == {"n": 2, "dangerous": 2}


def test_score_counts_a_code_reader_permission_in_the_pipeline_rate_only():
    spec = [(fp.PRIMARY, "correct", "correct", "direct_code", True, "P1", "justified")] + [(fp.PRIMARY, "correct", "correct", "direct_structural", False, "P2", "violation")] * 3
    s = fp.score(results_frame(spec))
    assert s["model_raw"]["dangerous"]["k"] == 0 and s["band"] == "LOW"
    assert s["pipeline"]["false_justified"]["k"] == 1 and s["pipeline"]["via_code_reader"] == 1 and s["pipeline"]["via_model"] == 0


def test_score_band_turns_high_at_five():
    spec = [(fp.PRIMARY, "dangerous", "dangerous", "direct_structural", False, "P1", "violation")] * 5 + [(fp.PRIMARY, "correct", "correct", "direct_structural", False, "P1", "violation")] * 39
    assert fp.score(results_frame(spec))["band"] == "HIGH"


def test_adjudication_is_reported_beside_the_unadjudicated_rate_never_instead_of_it():
    spec = [(fp.PRIMARY, "dangerous", "dangerous", "direct_structural", False, "P1", "violation")] * 4 + [(fp.PRIMARY, "correct", "correct", "direct_structural", False, "P1", "violation")] * 6
    df = results_frame(spec)
    adj = pd.DataFrame({"case_id": ["C0", "C1", "C2"], "team_judgement": ["defensible", "false_permission", "defensible"]})
    s = fp.score(df, adj)
    assert s["band"] == "MODERATE" and s["model_raw"]["dangerous"]["k"] == 4  # the pre-registered figure is untouched
    assert s["adjudicated"] == {"dangerous_before": 4, "judged_defensible": 2, "dangerous_after": fp.rate(2, 10), "unjudged": 1}


def test_adjudication_template_lists_only_flagged_primary_rows():
    spec = [(fp.PRIMARY, "dangerous", "dangerous", "direct_structural", False, "P1", "violation"), (fp.PRIMARY, "misleading", "misleading", "direct_structural", False, "P1", "violation"),
            (fp.PRIMARY, "correct", "correct", "direct_structural", False, "P1", "violation"), (fp.INACTIVE_CONTROL, "dangerous", "dangerous", "direct_structural", False, "P1", "violation")]
    t = fp.adjudication_template(results_frame(spec))
    assert list(t.case_id) == ["C0", "C1"] and (t.team_judgement == "").all()


def test_markdown_report_states_band_and_interval():
    s = fp.score(results_frame([(fp.PRIMARY, "correct", "correct", "direct_structural", False, "P1", "violation")] * 44))
    md = fp.render_markdown(s)
    assert "LOW" in md and "0/44" in md and "8.0%" in md


# ---------------------------------------------------------------- case construction
def mini(tmp_path):
    def entry(i, nbytes=500):
        return {"file": f"f{i}", "path": f"docs/adr/{i:04d}.md", "sha256": f"{i:064x}", "bytes": nbytes, "url": f"https://example/{i}"}
    files = [entry(i) for i in range(1, 15)]
    files[2]["bytes"] = 0
    manifest = {"repos": [{"repo": "a/b", "commit": "abc", "files": files}]}
    status = {i: "accepted" for i in range(1, 15)}
    status[4], status[5] = "rejected", "superseded"
    q1 = {i: "no" for i in range(1, 15)}
    q1[1], q1[2] = "yes", "partly"
    sheet = pd.DataFrame([{"id": f"R{i:03d}", "url": f"https://example/{i}", "status": status[i], Q1: q1[i]} for i in range(1, 15)])
    (tmp_path / "m.json").write_text(json.dumps(manifest))
    sheet.to_csv(tmp_path / "s.csv", index=False)
    return str(tmp_path / "s.csv"), str(tmp_path / "m.json")


Q1 = fp.Q1


def test_build_cases_strata_and_exclusions(tmp_path):
    sheet, manifest = mini(tmp_path)
    df = fp.build_cases(sheet, manifest)
    assert len(df) == 12  # 14 minus the yes and the partly
    assert "FP_R001" not in set(df.case_id) and "FP_R002" not in set(df.case_id)
    by = df.set_index("case_id").stratum
    assert by["FP_R003"] == fp.EXCLUDED_EMPTY
    assert by["FP_R004"] == by["FP_R005"] == fp.INACTIVE_CONTROL
    assert (df.stratum == fp.PRIMARY).sum() == 9  # 12 minus 1 empty minus 2 inactive
    assert df[df.stratum == fp.EXCLUDED_EMPTY].pair_id.eq("").all()
    assert df[df.stratum != fp.EXCLUDED_EMPTY].expected.eq("violation").all()


def test_build_cases_is_deterministic_and_seed_sensitive(tmp_path):
    sheet, manifest = mini(tmp_path)
    a, b = fp.build_cases(sheet, manifest), fp.build_cases(sheet, manifest)
    assert a.equals(b)
    assert not a.pair_id.equals(fp.build_cases(sheet, manifest, seed=1).pair_id)


def test_pairs_are_rotated_evenly_inside_the_primary_stratum(tmp_path):
    sheet, manifest = mini(tmp_path)
    counts = fp.build_cases(sheet, manifest).query("stratum == 'primary'").pair_id.value_counts()
    assert counts.sum() == 9 and counts.max() - counts.min() <= 1


def test_build_cases_refuses_an_adr_that_is_not_pinned_in_the_manifest(tmp_path):
    sheet, manifest = mini(tmp_path)
    s = pd.read_csv(sheet)
    s.loc[0, "url"] = "https://example/unknown"
    s.loc[0, Q1] = "no"
    s.to_csv(sheet, index=False)
    with pytest.raises(ValueError, match="not in the manifest"):
        fp.build_cases(sheet, manifest)


def test_no_pair_is_related_to_any_adr_by_construction():
    assert len({p["pair_id"] for p in fp.PAIRS}) == len(fp.PAIRS) == 6
    for p in fp.PAIRS:
        assert p["rule_description"] and p["code_snippet"] and p["source_type"] != p["target_type"]


@pytest.mark.skipif(not HAVE_REAL, reason="needs the team-verified sheet and the real-ADR manifest")
def test_real_population_is_44_active_5_inactive_1_empty():
    df = fp.build_cases()
    assert df.stratum.value_counts().to_dict() == {fp.PRIMARY: 44, fp.INACTIVE_CONTROL: 5, fp.EXCLUDED_EMPTY: 1}
    counts = df[df.stratum == fp.PRIMARY].pair_id.value_counts()
    assert counts.max() - counts.min() <= 1
    assert df[df.stratum != fp.EXCLUDED_EMPTY].adr_sha256.str.len().eq(64).all()


@pytest.mark.skipif(not os.path.exists(fp.DEFAULT_CASES) or not HAVE_REAL, reason="needs the committed case file and the sheet")
def test_committed_case_file_is_what_the_builder_produces():
    committed = pd.read_csv(fp.DEFAULT_CASES, dtype=str).fillna("")
    built = fp.build_cases().astype(str).fillna("")
    assert committed.equals(built.reset_index(drop=True))


# ---------------------------------------------------------------- freeze
def test_freeze_detects_any_change(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("one")
    b.write_text("two")
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps(fp.freeze_record([str(a), str(b)])))
    assert fp.verify_freeze(str(rec)) == []
    b.write_text("changed")
    assert fp.verify_freeze(str(rec)) == [str(b)]
    a.unlink()
    assert set(fp.verify_freeze(str(rec))) == {str(a), str(b)}


def test_every_frozen_file_exists():
    assert [p for p in fp.FROZEN_FILES if p != fp.DEFAULT_CASES and not os.path.exists(p)] == []


def test_the_experiment_uses_the_frozen_extraction_prompt_version():
    from analysis.semantic import extract
    assert extract.EXTRACT_VERSION == "x4"


# ---------------------------------------------------------------- end to end with a stub
def test_cli_score_round_trip(tmp_path):
    spec = [(fp.PRIMARY, "dangerous", "correct", "direct_structural", False, "P1", "violation")] + [(fp.PRIMARY, "correct", "correct", "direct_structural", False, "P2", "violation")] * 9
    res = tmp_path / "results.csv"
    results_frame(spec).to_csv(res, index=False)
    out = tmp_path / "out"
    assert fp.main(["score", "--results", str(res), "--out", str(out)]) == 0
    s = json.loads((out / "summary.json").read_text())
    assert s["band"] == "LOW" and s["model_raw"]["dangerous"]["k"] == 1
    assert (out / "summary.md").exists() and (out / "adjudication_template.csv").exists()


# ---------------------------------------------------------------- the `run` command end to end (stub model, fabricated ADR text)
def _prepared_run(tmp_path, monkeypatch):
    sheet, manifest = mini(tmp_path)
    cases = tmp_path / "cases.csv"
    fp.build_cases(sheet, manifest).to_csv(cases, index=False)
    frozen = tmp_path / "frozen_input.txt"
    frozen.write_text("v1")
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps(fp.freeze_record([str(frozen), str(cases)])))
    monkeypatch.setattr(fp, "_client", lambda: stub("permits", "yes"))
    monkeypatch.setattr(fp.case_study, "load_adr_text", lambda r, c=None: TEXTS["unrelated"] if r["sheet_status"] == "accepted" else TEXTS["rejected"])
    return cases, rec, frozen, tmp_path / "out"


def test_run_command_makes_one_call_per_runnable_case_and_writes_every_output(tmp_path, monkeypatch, capsys):
    cases, rec, _frozen, out = _prepared_run(tmp_path, monkeypatch)
    assert fp.main(["run", "--cases", str(cases), "--freeze", str(rec), "--out", str(out)]) == 0
    res = pd.read_csv(out / "results.csv", dtype=str)
    assert len(res) == 11  # 12 cases minus the empty file
    assert (res.stratum == fp.PRIMARY).sum() == 9 and (res.stratum == fp.INACTIVE_CONTROL).sum() == 2
    s = json.loads((out / "summary.json").read_text())
    assert s["n_primary"] == 9 and s["n_inactive_control"] == 2 and s["n_excluded_empty"] == 1
    assert s["model_raw"]["dangerous"]["k"] == 9 and s["band"] == "HIGH"  # the stub permits everything
    assert s["pipeline"]["false_justified"]["k"] == 0  # none of the fabricated unrelated ADRs is selected, so none reaches the model path
    assert "freeze check OK" in capsys.readouterr().out


def test_run_command_refuses_when_a_frozen_file_has_changed(tmp_path, monkeypatch):
    cases, rec, frozen, out = _prepared_run(tmp_path, monkeypatch)
    frozen.write_text("v2")
    with pytest.raises(SystemExit, match="Refusing to run"):
        fp.main(["run", "--cases", str(cases), "--freeze", str(rec), "--out", str(out)])
    assert not (out / "results.csv").exists()
