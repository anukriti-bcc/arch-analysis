import pytest

from analysis.intent.adr import (
    ADR, extract_adr_references, find_relevant_adrs, load_adrs, normalize_adr_id,
    normalize_status, parse_adr,
)

NYGARD = "# 7. Allow direct reads\n\nDate: 2026-02-03\n\n## Status\n\nAccepted\n\n## Context\nx"
MADR = "# Use X\n\n* Status: superseded by [ADR-0012](0012.md)\n* Date: 2026-03-01\n"
FRONT = "---\nid: ADR-009\nstatus: Accepted\ndate: 2026-04-10\n---\n# Payments may read ledger\ntext"


def test_nygard_format():
    a = parse_adr("docs/adr/0007-allow.md", NYGARD)
    assert (a.id, a.title, a.status, a.date.isoformat()) == ("ADR-007", "Allow direct reads", "accepted", "2026-02-03")


def test_madr_status_with_link_is_superseded_and_inactive():
    a = parse_adr("adr/0003-use-x.md", MADR)
    assert a.status == "superseded" and a.is_active is False and a.id == "ADR-003"


def test_front_matter_beats_filename():
    a = parse_adr("adr/payments.md", FRONT)
    assert (a.id, a.status, a.date.isoformat()) == ("ADR-009", "accepted", "2026-04-10")


@pytest.mark.parametrize("raw,expected", [
    ("Accepted", "accepted"), ("approved", "accepted"), ("Proposed", "proposed"),
    ("Superseded by ADR-4", "superseded"), ("Deprecated", "deprecated"), ("Rejected", "rejected"),
    ("", "unknown"), (None, "unknown"), ("banana", "unknown"),
])
def test_normalize_status(raw, expected):
    assert normalize_status(raw) == expected


def test_unknown_status_is_treated_as_possibly_active():
    assert parse_adr("a/0001-x.md", "# X\nno status here").is_active is True


def test_missing_date_is_none():
    assert parse_adr("a/0001-x.md", "# X\n").date is None


def test_malformed_front_matter_does_not_crash():
    a = parse_adr("a/0001-x.md", "---\n: : bad: [\n---\n# Title\n")
    assert a.id == "ADR-001"


def test_id_normalisation_and_reference_extraction():
    assert normalize_adr_id(7) == "ADR-007" and normalize_adr_id("0012") == "ADR-012"
    assert extract_adr_references("per adr_7 and ADR-0012, also ADR-7; nothing else") == ["ADR-007", "ADR-012"]
    assert extract_adr_references("") == [] and extract_adr_references(None) == []


def test_load_adrs_skips_readme_and_non_markdown(tmp_path):
    d = tmp_path / "docs" / "adr"
    d.mkdir(parents=True)
    (d / "0001-a.md").write_text("# A\n\n## Status\n\nAccepted\n")
    (d / "README.md").write_text("# index")
    (d / "notes.png").write_bytes(b"\x89PNG")
    adrs = load_adrs(str(tmp_path))
    assert [a.id for a in adrs] == ["ADR-001"]


def test_load_adrs_without_directory_is_empty(tmp_path):
    assert load_adrs(str(tmp_path)) == []


def _adr(text, status="accepted"):
    return ADR("ADR-001", "t", status, status, None, "adr/0001.md", text)


def kw(**over):
    base = dict(rule_id="R004", source_path="app/services/pay_service.py", target_path="app/database/connection.py",
                source_type="service", target_type="database")
    return {**base, **over}


def test_relevance_by_rule_id():
    assert [m.reasons for m in find_relevant_adrs([_adr("exception to R004")], **kw())] == [("rule_id",)]


def test_relevance_by_both_file_names():
    m = find_relevant_adrs([_adr("pay_service may use connection")], **kw())
    assert m and "file_names" in m[0].reasons


def test_one_file_name_alone_is_not_enough():
    assert find_relevant_adrs([_adr("pay_service is great")], **kw()) == []


def test_relevance_by_component_types_requires_both_as_whole_words():
    assert find_relevant_adrs([_adr("the service tier caches database lookups")], **kw())
    assert find_relevant_adrs([_adr("many services and databases")], **kw()) == []  # plurals are not matches


def test_rule_id_does_not_match_inside_longer_token():
    assert find_relevant_adrs([_adr("see R0045 for details")], **kw()) == []


def test_generic_stems_are_ignored():
    m = find_relevant_adrs([_adr("main and __init__ are special")], **kw(source_path="a/main.py", target_path="a/__init__.py"))
    assert m == []
