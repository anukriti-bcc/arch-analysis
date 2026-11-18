"""Tooling for the real-ADR check (corpus fetch filters, profiling proxies, matcher probe, annotation sheet)."""
import json
import os

import pandas as pd
import pytest

from experiments.real_adrs import fetch_corpus as fc
from experiments.real_adrs import profile as pr

TECH_CHOICE = "# 1. Use PostgreSQL\n\nDate: 2020-01-02\n\n## Status\n\nAccepted\n\n## Context\n\nWe need a database.\n\n## Decision\n\nWe will use PostgreSQL as our primary data store because the team knows it.\n\n## Consequences\n\nWe operate it ourselves."
LAYER_RULE = "# 2. Layering\n\n## Status\n\nAccepted\n\n## Context\n\nCode was tangled.\n\n## Decision\n\nControllers must not access the database directly. Only the repository layer may call the database."
SOFT_STRUCTURE = "# 3. Services\n\n## Status\n\nAccepted\n\n## Decision\n\nEach service communicates with the others through the message bus."


def test_rule_tier_separates_technology_choices_from_dependency_rules():
    assert pr.rule_tier(LAYER_RULE) == 1
    assert pr.rule_tier(SOFT_STRUCTURE) == 2
    assert pr.rule_tier(TECH_CHOICE) == 3


def test_context_text_is_not_counted_as_the_decision():
    text = "# 4. X\n\n## Context\n\nControllers must not access the database directly.\n\n## Decision\n\nWe adopt Kafka."
    assert pr.rule_tier(text) == 3


def test_format_kinds():
    assert pr.format_kind(TECH_CHOICE) == "nygard_like"
    assert pr.format_kind("## Considered Options\n\n* a\n\n## Decision Outcome\n\nb") == "madr_like"
    assert pr.format_kind("just prose") == "other"


def test_boilerplate_first_adr_is_recognised():
    assert pr.is_boilerplate("# 1. Record architecture decisions\n\nWe will record architecture decisions.")
    assert not pr.is_boilerplate(TECH_CHOICE)


def test_profile_one_reports_m6_stance_and_dates():
    repo = {"repo": "o/r", "kind": "project", "stars": 3, "created": "2020-01-01"}
    row = pr.profile_one(repo, {"file": "o__r/a.md", "path": "docs/adr/0002.md", "url": "u"}, LAYER_RULE + "\n\nUntil 2025-01-01 the legacy module is an exception.")
    assert row["rule_tier"] == 1 and row["exception_language"] and row["decision_section"]
    assert row["dates_in_decision"] == 1 and row["m6_stance"] in ("prohibits", "permits", "unclear")


def corpus(tmp_path, texts):
    root = tmp_path / "c"; (root / "corpus" / "o__r").mkdir(parents=True)
    files = []
    for i, t in enumerate(texts):
        (root / "corpus" / "o__r" / f"{i}.md").write_text(t)
        files.append({"file": f"o__r/{i}.md", "path": f"docs/adr/000{i}.md", "url": f"https://x/{i}"})
    json.dump({"repos": [{"repo": "o/r", "kind": "project", "stars": 1, "created": "2020-01-01", "license": "MIT", "license_ok": True, "files": files}]},
              open(root / "manifest.json", "w"))
    return str(root)


def test_matcher_probe_uses_the_real_matcher_and_shows_the_plural_blind_spot(tmp_path):
    root = corpus(tmp_path, [LAYER_RULE, TECH_CHOICE, "The controller talks to the repository."])
    _, items = pr.load(root, ("project",))
    probe = pr.matcher_probe(items).set_index(["source_type", "target_type"])
    row = probe.loc[("controller", "repository")]
    # LAYER_RULE says "Controllers" (plural): the project's matcher needs the exact word and misses it; the tolerant variant finds it.
    assert row.adrs == 3 and row.matched_by_type_words == 1 and row.matched_plural_tolerant == 2
    assert probe.loc[("view", "model")].matched_by_type_words == 0


def test_cli_writes_profile_summary_and_a_blank_annotation_sheet(tmp_path):
    root = corpus(tmp_path, [LAYER_RULE, TECH_CHOICE, SOFT_STRUCTURE, "# 1. Record architecture decisions\n\nWe will."])
    out = tmp_path / "out"
    assert pr.main(["--corpus", root, "--out", str(out), "--sheet", "3"]) == 0
    s = json.load(open(out / "summary.json"))
    assert s["adrs"] == 3 and s["boilerplate_excluded"] == 1 and s["rule_tier_pct"]["tier1"] == pytest.approx(33.3, abs=0.1)
    sheet = pd.read_csv(out / "annotation_sheet.csv")
    assert len(sheet) == 3 and sheet["Q1_about_dependencies (yes/no/partly)"].isna().all()  # labels are for humans to fill
    assert os.path.exists(out / "profile.csv")


def test_fetch_filters_licence_age_tools_and_size():
    base = {"full_name": "a/proj", "description": "An e-commerce backend", "license": {"spdx_id": "MIT"}, "archived": False, "fork": False,
            "created_at": "2019-05-01T00:00:00Z", "size": 1000}
    assert fc.acceptable(base, "2023-01-01")[0]
    assert fc.acceptable({**base, "license": {"spdx_id": "GPL-3.0"}}, "2023-01-01")[0]  # licence is a flag for excerpts, not a filter for analysis
    assert not fc.acceptable({**base, "created_at": "2025-02-01T00:00:00Z"}, "2023-01-01")[0]   # the AI-agent-era filter
    assert not fc.acceptable({**base, "description": "ADR template collection"}, "2023-01-01")[0]
    assert fc.acceptable({**base, "size": 900_000}, "2023-01-01")[0]  # blobless clones do not download content, so size is irrelevant
    assert fc.acceptable({**base, "created_at": "2025-02-01T00:00:00Z", "description": "template", "curated": True}, "2023-01-01")[0]  # curated bypasses age/name


def test_adr_path_selection_excludes_readmes_templates_and_other_markdown():
    paths = ["docs/adr/0001-a.md", "docs/adr/README.md", "docs/decisions/template.md", "docs/guide.md", "architecture-decisions/adr-002.md", "src/x.py"]
    assert fc.adr_paths(paths) == ["docs/adr/0001-a.md", "architecture-decisions/adr-002.md"]


def test_adr_path_selection_accepts_real_world_directory_names_but_not_other_decision_docs():
    ok = ["docs/architecture-decision-record/0001-use-x.md", "docs/Architecture-Decision-Log/0007-modules.md", "docs/decision_records/api/API-001-grpc.md",
          "docs/decisions/2021-04-01-choose-db.md", "doc/adr/adr-0003-events.md"]
    for p in ok:
        assert fc.adr_paths([p]) == [p], p
    assert fc.adr_paths(["docs/decision-trees/guide.md", "docs/decisions/overview.md"]) == []


MADR = ("# Use X\n\n## Context and Problem Statement\n\nWhich?\n\n## Decision Drivers\n\n* Low maintenance effort\n* No additional dependencies\n\n"
        "## Considered Options\n\n* A\n* B\n\n## Decision Outcome\n\nChosen option: \"A\", because modules must not depend on each other.\n\n### Consequences\n\n* fine")


def test_decision_outcome_wins_over_decision_drivers_unlike_the_frozen_reader():
    """Found on real ADRs: the frozen reader (M6) returns the Decision Drivers list for MADR documents."""
    from analysis.intent.reader import decision_section
    ours, found = pr.decision_text(MADR)
    assert found and ours.startswith('Chosen option: "A"') and "Low maintenance" not in ours and "Consequences" not in ours
    frozen, _ = decision_section(MADR)
    assert "Low maintenance effort" in frozen  # documents the defect so it cannot be forgotten or silently changed


def test_decision_text_keeps_subheadings_and_inline_decisions():
    dapr = "# X\n\n## Status\n\nAccepted\n\n## Decisions\n\n### D1\n\n* We will use gRPC\n\n### D2\n\n* Actors are separate\n\n## Consequences\n\nnone"
    section, found = pr.decision_text(dapr)
    assert found and "D1" in section and "D2" in section and "Consequences" not in section
    inline = "# 25 Domain names\n\n## Status\n\nAccepted\n\n**Decision:** deprecate the wildcard domain."
    assert pr.decision_text(inline) == ("deprecate the wildcard domain.", True)


def test_agreement_tool_kappa_prevalence_and_unlabelled_rows(tmp_path):
    from experiments.real_adrs import agreement as ag
    sheet = pd.DataFrame({"id": ["R1", "R2", "R3", "R4", "R5", "R6"], ag.Q1: ["yes", "no", "no", "partly", "no", ""]})
    other = pd.DataFrame({"id": ["R1", "R2", "R3", "R4", "R5", "R6"], "Q1_about_dependencies": ["yes", "no", "partly", "partly", "no", "no"]})
    r = ag.compare(sheet, other)
    assert r["compared"] == 5 and r["unlabelled_in_sheet"] == ["R6"]
    assert r["raw_agreement_3class"] == pytest.approx(0.8) and r["disagreements"] == [{"id": "R3", "sheet": "no", "other": "partly"}]
    assert r["prevalence_yes"]["k"] == 1 and r["prevalence_yes_or_partly"]["k"] == 2 and r["prevalence_yes_or_partly"]["n"] == 5
    lo, hi = r["prevalence_yes_or_partly"]["wilson95"]
    assert 0 < lo < 0.4 < hi < 1
    assert 0 < r["kappa_3class"] < 1
    s, o = tmp_path / "s.csv", tmp_path / "o.csv"
    sheet.to_csv(s, index=False); other.to_csv(o, index=False)
    assert ag.main(["--sheet", str(s), "--other", str(o), "--out", str(tmp_path / "a.json")]) == 0 and (tmp_path / "a.json").exists()
