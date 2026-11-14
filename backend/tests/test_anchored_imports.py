"""Path-prefix component mapping and anchored import resolution.

Regression for a bug found on a real repository (sqlfluff): with the legacy suffix
heuristic, the stdlib `import logging` resolved to a project file that merely ends in
`logging.py`, producing 21 false violations. See docs/REAL_REPOS.md.
"""
import os

from analysis.conformance.engine import analyze_conformance
from analysis.dependency.module_index import ModuleIndex
from analysis.dependency.repository_scanner import scan_repository
from models.finding import FindingStatus
from rules.loader import ComponentMapping, load_architecture_file

RULES = """
architecture: {name: t}
import_resolution: anchored
component_mapping:
  pkg/low: {type: low}
  pkg/high: {type: high}
rules:
  - {id: R1, source: low, target: high, relation: forbidden}
"""


def _write(root, rel, text=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)


def test_path_prefix_longest_match_and_module_files():
    m = ComponentMapping(mapping={}, path_prefixes=(("pkg/core/helpers", "helpers"), ("pkg/core", "core")))
    assert m.type_for_path("pkg/core/helpers/x.py") == "helpers"
    assert m.type_for_path("pkg/core/other.py") == "core"
    assert m.type_for_path("pkg/core.py") == "core"          # module file named like the prefix
    assert m.type_for_path("pkg/corex/a.py") is None         # prefix must end at a path boundary
    assert ComponentMapping(mapping={"a": "b"}).type_for_path("a/x.py") is None  # legacy mappings unaffected


def test_anchored_index_does_not_suffix_match():
    legacy, anchored = ModuleIndex(), ModuleIndex(strict=True)
    for idx in (legacy, anchored):
        idx.add_file("pkg/utils/logging.py")
    assert legacy.resolve_absolute("logging") == "pkg/utils/logging.py"   # documented legacy behaviour
    assert anchored.resolve_absolute("logging") is None                   # stdlib name stays external
    assert anchored.resolve_absolute("pkg.utils.logging") == "pkg/utils/logging.py"


def test_scan_end_to_end_with_anchored_rules(tmp_path):
    root = str(tmp_path)
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/low/__init__.py")
    _write(root, "pkg/high/__init__.py")
    _write(root, "pkg/high/logging.py")                       # collides with stdlib name
    _write(root, "pkg/low/a.py", "import logging\nfrom pkg.high import logging as hl\n")
    _write(root, "pkg/low/b.py", "import logging\n")          # stdlib only: must NOT be a violation
    rules = os.path.join(root, "rules.yaml")
    open(rules, "w").write(RULES)
    arch, mapping = load_architecture_file(rules)
    assert mapping.anchored_imports
    scan = scan_repository(root, mapping)
    viol = [f for f in analyze_conformance(scan.components, scan.dependencies, arch) if f.status == FindingStatus.VIOLATION]
    assert {(f.source["id"], f.target["id"]) for f in viol} == {("pkg/low/a.py", "pkg/high/logging.py")}


# ---- one dependency per imported submodule (anchored mode) ------------------------------

def _scan(tmp_path, files, rules=RULES):
    root = str(tmp_path)
    for rel, text in files.items():
        _write(root, rel, text)
    open(os.path.join(root, "rules.yaml"), "w").write(rules)
    arch, mapping = load_architecture_file(os.path.join(root, "rules.yaml"))
    scan = scan_repository(root, mapping)
    return {(d.source, d.target) for d in scan.dependencies}, scan


PKG = {"pkg/__init__.py": "", "pkg/low/__init__.py": "", "pkg/high/__init__.py": "",
       "pkg/high/a.py": "", "pkg/high/b.py": "", "pkg/high/c.py": ""}


def test_anchored_mode_emits_an_edge_for_every_imported_submodule(tmp_path):
    edges, _ = _scan(tmp_path, {**PKG, "pkg/low/x.py": "from pkg.high import a, b\n"})
    assert edges == {("pkg/low/x.py", "pkg/high/a.py"), ("pkg/low/x.py", "pkg/high/b.py")}


def test_anchored_mode_also_depends_on_the_package_when_an_attribute_is_imported(tmp_path):
    edges, _ = _scan(tmp_path, {**PKG, "pkg/low/x.py": "from pkg.high import a, SOME_CONSTANT\n"})
    assert edges == {("pkg/low/x.py", "pkg/high/a.py"), ("pkg/low/x.py", "pkg/high/__init__.py")}


def test_anchored_relative_from_import_of_several_names(tmp_path):
    files = {**PKG, "pkg/high/m.py": "from . import a, b\n"}
    edges, _ = _scan(tmp_path, files)
    assert {t for s, t in edges if s == "pkg/high/m.py"} == {"pkg/high/a.py", "pkg/high/b.py"}


def test_anchored_mode_does_not_duplicate_targets_or_depend_on_itself(tmp_path):
    edges, _ = _scan(tmp_path, {**PKG, "pkg/low/x.py": "from pkg.high import a, a\nfrom pkg.low import x\n"})
    assert edges == {("pkg/low/x.py", "pkg/high/a.py")}


def test_legacy_mode_still_yields_at_most_one_target_per_statement(tmp_path):
    legacy_rules = "architecture: {name: t}\ncomponent_mapping:\n  low: {type: low}\n  high: {type: high}\nrules:\n  - {id: R1, source: low, target: high, relation: forbidden}\n"
    edges, _ = _scan(tmp_path, {**{f"app/{k[4:]}": v for k, v in PKG.items()}, "app/low/x.py": "from app.high import a, b\n"}, legacy_rules)
    assert len([e for e in edges if e[0] == "app/low/x.py"]) == 1  # documented legacy behaviour, unchanged


def test_history_analyzer_agrees_with_the_scanner_on_multi_name_imports(tmp_path):
    """'When was it introduced' must answer about the SAME dependencies the scanner reports."""
    from analysis.evolution.git_evolution import GitEvolutionAnalyzer
    from experiments.benchmark.gitbuilder import GitBuilder
    from datetime import date
    g = GitBuilder(str(tmp_path / "r"))
    for rel, text in {**PKG, "pkg/low/x.py": "VALUE = 1\n"}.items():
        g.write(rel, text)
    g.commit("scaffold", date(2026, 1, 5))
    g.write("pkg/low/x.py", "from pkg.high import a, b\n")
    intro = g.commit("depend on two submodules", date(2026, 2, 5))
    evo = GitEvolutionAnalyzer(anchored_imports=True)
    for target in ("pkg/high/a.py", "pkg/high/b.py"):
        ev = evo.analyze_dependency(g.path, "pkg/low/x.py", target)
        assert ev["present_at_head"] and ev["introducing_commit"]["sha"] == intro, target
