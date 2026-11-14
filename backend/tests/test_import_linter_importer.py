"""import-linter contracts -> this project's architecture file.

The real-repository case study stands or falls on this translation being faithful, so each
contract type is pinned to import-linter's documented semantics:
  forbidden    source_modules must not import forbidden_modules
  independence the listed modules must not import each other (both directions)
  layers       a LOWER layer must not import a HIGHER one; layers joined with `|` are siblings
               that must not import each other
"""
import json
import os

import pytest

from analysis.conformance.engine import analyze_conformance
from analysis.dependency.repository_scanner import scan_repository
from experiments.real_repos.import_linter_importer import (
    Contract, build_architecture, contract_pairs, layer_levels, parse_config, prune_contracts,
    to_ini, tolerated_list, write_outputs,
)
from models.finding import FindingStatus
from rules.loader import load_architecture_file

INI = """
[importlinter]
root_package = pkg

[importlinter:contract:layers]
name = Layered
type = layers
layers =
    pkg.api
    pkg.core | pkg.plugins
    pkg.util
ignore_imports =
    # the formatter needs the linter for historical reasons
    pkg.util.fmt -> pkg.core.linter
    # shared by two entries
    pkg.util.a -> pkg.api.x
    pkg.util.b -> pkg.api.y

[importlinter:contract:forbid]
name = No CLI in core
type = forbidden
source_modules = pkg.core
forbidden_modules = pkg.cli

[importlinter:contract:indep]
name = Independent plugins
type = independence
modules =
    pkg.plugins.a
    pkg.plugins.b

[importlinter:contract:other]
name = Something else
type = acyclic_siblings
"""

TOML = """
[tool.importlinter]
root_package = "pkg"

[[tool.importlinter.contracts]]
name = "Layered"
type = "layers"
layers = ["pkg.api", "pkg.core"]
ignore_imports = [
    # historical
    "pkg.core.a -> pkg.api.b",
]

[[tool.importlinter.contracts]]
name = "No CLI"
type = "forbidden"
source_modules = ["pkg.core"]
forbidden_modules = ["pkg.cli"]
"""


def by_name(contracts):
    return {c.name: c for c in contracts}


# ------------------------------------------------------------------- parsing

def test_parse_ini_finds_all_contracts_and_options():
    opts, contracts = parse_config(".importlinter", INI)
    assert opts["root_package"] == "pkg"
    assert [(c.name, c.type) for c in contracts] == [
        ("Layered", "layers"), ("No CLI in core", "forbidden"), ("Independent plugins", "independence"), ("Something else", "acyclic_siblings")]


def test_ini_tolerated_imports_keep_the_maintainers_comment_as_the_reason():
    _, contracts = parse_config("setup.cfg", INI)
    tol = {(t["importer"], t["imported"]): t["reason"] for t in by_name(contracts)["Layered"].tolerated}
    assert tol[("pkg.util.fmt", "pkg.core.linter")] == "the formatter needs the linter for historical reasons"
    # consecutive entries under one comment share its reason
    assert tol[("pkg.util.a", "pkg.api.x")] == tol[("pkg.util.b", "pkg.api.y")] == "shared by two entries"


def test_parse_pyproject_toml():
    opts, contracts = parse_config("pyproject.toml", TOML)
    assert opts["root_package"] == "pkg" and [c.type for c in contracts] == ["layers", "forbidden"]
    assert by_name(contracts)["Layered"].tolerated[0]["reason"] == "historical"


def test_parse_config_without_importlinter_section_is_empty():
    assert parse_config("tox.ini", "[tox]\nenvlist = py3\n") == ({}, [])


# ------------------------------------------------------------ contract semantics

def pairs(contract):
    return set(contract_pairs(contract)[0])


def test_forbidden_pairs_are_source_times_forbidden():
    c = Contract("f", "forbidden", {"source_modules": "pkg.a\npkg.b", "forbidden_modules": "pkg.x"})
    assert pairs(c) == {("pkg.a", "pkg.x"), ("pkg.b", "pkg.x")}


def test_independence_forbids_both_directions():
    c = Contract("i", "independence", {"modules": "pkg.a\npkg.b\npkg.c"})
    assert pairs(c) == {(a, b) for a in ("pkg.a", "pkg.b", "pkg.c") for b in ("pkg.a", "pkg.b", "pkg.c") if a != b}


def test_layers_forbid_lower_importing_higher_and_siblings_importing_each_other():
    c = Contract("l", "layers", {"layers": "pkg.api\npkg.core | pkg.plugins\npkg.util"})
    got = pairs(c)
    assert ("pkg.util", "pkg.api") in got and ("pkg.util", "pkg.core") in got and ("pkg.core", "pkg.api") in got
    assert ("pkg.api", "pkg.core") not in got and ("pkg.api", "pkg.util") not in got  # downward is allowed
    assert ("pkg.core", "pkg.plugins") in got and ("pkg.plugins", "pkg.core") in got   # siblings independent


def test_layers_with_containers_are_qualified_and_optional_markers_stripped():
    c = Contract("l", "layers", {"containers": "pkg.app", "layers": "web | (cli)\nservices"})
    assert layer_levels(c) == [["pkg.app.web", "pkg.app.cli"], ["pkg.app.services"]]
    assert ("pkg.app.services", "pkg.app.web") in pairs(c)


# ------------------------------------------------------------- build_architecture

def test_build_architecture_maps_modules_to_path_prefixes_and_requests_anchored_imports():
    _, contracts = parse_config(".importlinter", INI)
    arch, report = build_architecture(contracts, "pkg", "demo")
    assert arch["import_resolution"] == "anchored"
    assert arch["component_mapping"]["pkg/core"] == {"type": "pkg.core"}
    assert all("." not in k for k in arch["component_mapping"])
    assert all(r["relation"] == "forbidden" for r in arch["rules"])
    assert report["skipped_types"] == ["acyclic_siblings"] and report["contracts_used"] == 3


def test_rule_ids_are_sequential_and_descriptions_name_the_contracts():
    _, contracts = parse_config(".importlinter", INI)
    arch, _ = build_architecture(contracts, "pkg", "demo")
    assert [r["id"] for r in arch["rules"]] == [f"R{i:03d}" for i in range(1, len(arch["rules"]) + 1)]
    assert all(r["description"].startswith("import-linter: ") for r in arch["rules"])


def test_rule_on_a_package_is_expanded_to_mapped_subpackages():
    """The engine matches exact component types; import-linter matches a package and everything
    below it. `pkg.core` must not import `pkg.cli` therefore has to cover `pkg.core.linter`."""
    contracts = [
        Contract("forbid", "forbidden", {"source_modules": "pkg.core", "forbidden_modules": "pkg.cli"}),
        Contract("layers", "layers", {"layers": "pkg.core.linter\npkg.core.rules"}),
    ]
    arch, _ = build_architecture(contracts, "pkg", "demo")
    edges = {(r["source"], r["target"]) for r in arch["rules"]}
    assert ("pkg.core", "pkg.cli") in edges
    assert ("pkg.core.linter", "pkg.cli") in edges and ("pkg.core.rules", "pkg.cli") in edges


def test_same_pair_from_two_contracts_yields_one_rule_naming_both():
    contracts = [Contract("one", "forbidden", {"source_modules": "pkg.a", "forbidden_modules": "pkg.b"}),
                 Contract("two", "forbidden", {"source_modules": "pkg.a", "forbidden_modules": "pkg.b"})]
    arch, _ = build_architecture(contracts, "pkg", "demo")
    assert len(arch["rules"]) == 1 and "one" in arch["rules"][0]["description"] and "two" in arch["rules"][0]["description"]


def test_unsupported_contract_types_create_no_rules_but_are_reported():
    arch, report = build_architecture([Contract("x", "acyclic_siblings", {})], "pkg", "demo")
    assert arch["rules"] == [] and report["skipped_types"] == ["acyclic_siblings"]


def test_tolerated_list_carries_the_contract_name():
    _, contracts = parse_config(".importlinter", INI)
    assert {t["contract"] for t in tolerated_list(contracts)} == {"Layered"}


# --------------------------------- end to end: contracts -> rules.yaml -> scanner -> findings

def _write(root, rel, text=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)


def test_round_trip_flags_exactly_the_imports_the_contract_forbids(tmp_path):
    contracts = [Contract("Layered", "layers", {"layers": "pkg.api\npkg.core"})]
    arch, _ = build_architecture(contracts, "pkg", "demo")
    rules_path, _ = write_outputs(arch, [], str(tmp_path / "out"))

    repo = str(tmp_path / "repo")
    for p in ("pkg", "pkg/api", "pkg/core"):
        _write(repo, f"{p}/__init__.py")
    _write(repo, "pkg/api/handlers.py", "from pkg.core import engine\n")        # high -> low: allowed
    _write(repo, "pkg/core/engine.py", "import logging\n")                      # stdlib, must stay external
    _write(repo, "pkg/core/bad.py", "from pkg.api import handlers\n")           # low -> high: forbidden
    architecture, mapping = load_architecture_file(rules_path)
    scan = scan_repository(repo, mapping)
    findings = analyze_conformance(scan.components, scan.dependencies, architecture)
    violations = {(f.structural_evidence.dependency.source, f.structural_evidence.dependency.target)
                  for f in findings if f.status == FindingStatus.VIOLATION}
    assert violations == {("pkg/core/bad.py", "pkg/api/handlers.py")}


def test_write_outputs_round_trips_through_files(tmp_path):
    _, contracts = parse_config(".importlinter", INI)
    arch, _ = build_architecture(contracts, "pkg", "demo")
    rules_path, tol_path = write_outputs(arch, tolerated_list(contracts), str(tmp_path / "o"))
    architecture, mapping = load_architecture_file(rules_path)
    assert len(architecture.rules) == len(arch["rules"]) and mapping.anchored_imports
    assert json.load(open(tol_path))[0]["reason"]


# ---------------------------------------------------------- retrospective pruning

def present_in(*mods):
    """A module "exists" if it is listed, or is a package containing a listed module."""
    have = set(mods)
    return lambda m: m in have or any(h.startswith(m + ".") for h in have)


def test_prune_drops_modules_that_did_not_exist_yet():
    c = Contract("f", "forbidden", {"source_modules": "pkg.core\npkg.new", "forbidden_modules": "pkg.cli"})
    out = prune_contracts([c], present_in("pkg.core", "pkg.cli"))
    assert out[0].fields["source_modules"] == ["pkg.core"]


def test_prune_drops_contracts_left_with_nothing_to_say():
    c = Contract("f", "forbidden", {"source_modules": "pkg.new", "forbidden_modules": "pkg.cli"})
    assert prune_contracts([c], present_in("pkg.cli")) == []
    layers = Contract("l", "layers", {"layers": "pkg.a\npkg.b"})
    assert prune_contracts([layers], present_in("pkg.a")) == []  # one layer left: nothing to enforce


def test_prune_keeps_only_tolerated_imports_between_existing_modules():
    c = Contract("f", "forbidden", {"source_modules": "pkg.a", "forbidden_modules": "pkg.b"},
                 tolerated=[{"importer": "pkg.a.x", "imported": "pkg.b.y", "reason": "r"},
                            {"importer": "pkg.a.x", "imported": "pkg.gone.z", "reason": "r"}])
    out = prune_contracts([c], present_in("pkg.a", "pkg.a.x", "pkg.b", "pkg.b.y"))
    assert [(t["importer"], t["imported"]) for t in out[0].tolerated] == [("pkg.a.x", "pkg.b.y")]


def test_prune_keeps_contracts_that_use_containers():
    """With `containers`, layer names are relative (`web`), so presence must be tested on the
    qualified name (`pkg.app.web`). Testing the bare name would silently drop every such
    contract at old commits."""
    c = Contract("l", "layers", {"containers": "pkg.app", "layers": "web\nservices"})
    out = prune_contracts([c], present_in("pkg.app.web", "pkg.app.services"))
    assert len(out) == 1, "a containers-based layers contract must survive pruning when its modules exist"


def test_to_ini_produces_a_file_the_parser_reads_back():
    _, contracts = parse_config(".importlinter", INI)
    text = to_ini({"root_package": "pkg"}, [c for c in contracts if c.type != "acyclic_siblings"])
    opts, back = parse_config(".importlinter", text)
    assert opts["root_package"] == "pkg"
    assert {c.type for c in back} == {"layers", "forbidden", "independence"}
    layers = next(c for c in back if c.type == "layers")
    assert pairs(layers) == pairs(next(c for c in contracts if c.type == "layers"))


def test_prune_marks_a_layer_optional_when_only_some_containers_have_it():
    c = Contract("l", "layers", {"containers": "pkg.one\npkg.two", "layers": "web\ncli | admin\nservices"})
    have = present_in("pkg.one.web", "pkg.two.web", "pkg.one.cli", "pkg.one.services", "pkg.two.services")
    out = prune_contracts([c], have)
    assert out[0].fields["layers"] == ["web", "(cli)", "services"], out[0].fields["layers"]
    # and the optional marker survives the round trip through the reference tool's file format
    _, back = parse_config(".importlinter", to_ini({"root_package": "pkg"}, out))
    # an optional layer expands over every container; the one that does not exist is tolerated
    assert layer_levels(back[0]) == [["pkg.one.web", "pkg.two.web"], ["pkg.one.cli", "pkg.two.cli"], ["pkg.one.services", "pkg.two.services"]]
