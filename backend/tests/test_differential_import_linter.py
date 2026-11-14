"""Differential tests against the REFERENCE implementations.

Instead of checking our scanner against our own expectations, these tests build random
repositories using every import style we claim to support, and compare with
  * grimp, the import-graph builder that import-linter itself is built on, and
  * `lint-imports`, import-linter's command line, run with the same contracts.
Agreement here is evidence that import resolution and contract translation are faithful,
and it is evidence of a different kind from the unit tests (which encode our own reading).

Skipped automatically when import-linter is not installed (`pip install import-linter`).
"""
import importlib
import os
import random
import re
import shutil
import subprocess
import sys

import pytest

grimp = pytest.importorskip("grimp")
pytest.importorskip("importlinter")
LINT = shutil.which("lint-imports")
pytestmark = pytest.mark.skipif(LINT is None, reason="lint-imports executable not found")

from analysis.conformance.engine import analyze_conformance
from analysis.dependency import repository_scanner as scanner
from analysis.dependency.repository_scanner import scan_repository
from experiments.real_repos.import_linter_importer import Contract, build_architecture, to_ini, write_outputs
from models.finding import FindingStatus
from rules.loader import load_architecture_file

PKGS = ["api", "core", "plugins", "util", "cli"]
MODS = ["m1", "m2", "m3"]


def build_repo(root: str, rng: random.Random) -> None:
    """Random package `pkg` using seven import styles."""
    os.makedirs(os.path.join(root, "pkg"))
    open(os.path.join(root, "pkg", "__init__.py"), "w").close()
    for p in PKGS:
        os.makedirs(os.path.join(root, "pkg", p))
        open(os.path.join(root, "pkg", p, "__init__.py"), "w").close()
    for p in PKGS:
        for m in MODS:
            lines = []
            for _ in range(rng.randint(0, 3)):
                tp, tm = rng.choice(PKGS), rng.choice(MODS)
                if (tp, tm) == (p, m):
                    continue
                style = rng.randint(0, 6)
                if style == 0:
                    lines.append(f"import pkg.{tp}.{tm}")
                elif style == 1:
                    lines.append(f"from pkg.{tp} import {tm}")
                elif style == 2:
                    lines.append(f"from pkg.{tp} import {tm}, {rng.choice([x for x in MODS if x != tm])}")
                elif style == 3:
                    lines.append(f"from pkg.{tp} import {tm}, SOME_ATTR")   # module + attribute
                elif style == 4:
                    lines.append(f"from pkg.{tp}.{tm} import name")          # attribute of a module
                elif style == 5 and tp == p:
                    lines.append(f"from . import {tm}")                       # relative
                elif style == 6 and tp == p:
                    lines.append(f"from .{tm} import name")
            with open(os.path.join(root, "pkg", p, f"{m}.py"), "w") as fh:
                fh.write("\n".join(lines) + "\n")


def to_module(path: str) -> str:
    mod = path[:-3].replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


def grimp_edges(root: str) -> set[tuple[str, str]]:
    sys.path.insert(0, root)
    importlib.invalidate_caches()
    try:
        graph = grimp.build_graph("pkg")
        return {(m, i) for m in graph.modules for i in graph.find_modules_directly_imported_by(m) if i != m}
    finally:
        sys.path.remove(root)
        for k in [k for k in sys.modules if k == "pkg" or k.startswith("pkg.")]:
            del sys.modules[k]


def our_edges(root: str, tmp: str) -> set[tuple[str, str]]:
    arch, _ = build_architecture([], "pkg", "d")
    rules, _ = write_outputs(arch, [], os.path.join(tmp, "o_graph"))
    _, mapping = load_architecture_file(rules)
    return {(to_module(d.source), to_module(d.target)) for d in scan_repository(root, mapping).dependencies}


def reference(tmp: str, root: str, contracts):
    cfg = os.path.join(tmp, ".importlinter")
    with open(cfg, "w") as fh:
        fh.write(to_ini({"root_package": "pkg"}, contracts))
    r = subprocess.run([LINT, "--config", cfg], cwd=root, env={**os.environ, "PYTHONPATH": root},
                       capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    pairs = {(m.group(1), m.group(2)) for m in re.finditer(r"^\s*-?\s*([A-Za-z_][\w.]*) -> ([A-Za-z_][\w.]*)", out, re.M)}
    counts = re.search(r"(\d+) kept, (\d+) broken", out)
    assert counts, f"lint-imports produced no summary:\n{out[-500:]}"
    return pairs, int(counts.group(2))


def engine_violations(root: str, tmp: str, contracts) -> set[tuple[str, str]]:
    arch, _ = build_architecture(contracts, "pkg", "d")
    rules, _ = write_outputs(arch, [], os.path.join(tmp, "o_rules"))
    architecture, mapping = load_architecture_file(rules)
    scan = scan_repository(root, mapping)
    found = analyze_conformance(scan.components, scan.dependencies, architecture)
    return {(to_module(f.structural_evidence.dependency.source), to_module(f.structural_evidence.dependency.target))
            for f in found if f.status == FindingStatus.VIOLATION}


@pytest.fixture
def repo(tmp_path):
    def make(seed):
        root = str(tmp_path / f"repo{seed}")
        os.makedirs(root)
        build_repo(root, random.Random(seed))
        return root, str(tmp_path)
    return make


SEEDS = range(12)


@pytest.mark.parametrize("seed", SEEDS)
def test_import_graph_matches_grimp_for_every_import_style(repo, seed):
    root, tmp = repo(seed)
    assert our_edges(root, tmp) == grimp_edges(root)


def test_the_graphs_compared_are_not_trivial(repo):
    sizes = [len(grimp_edges(repo(s)[0])) for s in range(5)]
    assert min(sizes) >= 5


def test_the_comparison_can_detect_the_old_first_name_wins_undercount(repo, monkeypatch):
    """Guards against a vacuous pass: with the previous behaviour (one target per statement)
    the same comparison must FAIL on these repositories."""
    def first_name_wins(rel, raw, index):
        one = scanner.resolve_import(rel, raw, index)
        return [one] if one and one != rel else []
    monkeypatch.setattr(scanner, "resolve_import_all", first_name_wins)
    mismatches = 0
    for seed in range(6):
        root, tmp = repo(seed)  # one repository per seed
        mismatches += our_edges(root, tmp) != grimp_edges(root)
    assert mismatches >= 3


FORBIDDEN = [
    Contract("f1", "forbidden", {"source_modules": "pkg.core", "forbidden_modules": "pkg.cli\npkg.api", "allow_indirect_imports": "True"}),
    Contract("f2", "forbidden", {"source_modules": "pkg.util", "forbidden_modules": "pkg.core", "allow_indirect_imports": "True"}),
]


@pytest.mark.parametrize("seed", range(8))
def test_forbidden_contract_violations_equal_the_reference_exactly(repo, seed):
    """With indirect imports allowed the reference reports only direct violations, so the sets must be identical."""
    root, tmp = repo(100 + seed)
    ref_pairs, _ = reference(tmp, root, FORBIDDEN)
    assert engine_violations(root, tmp, FORBIDDEN) == ref_pairs


LAYERS = [Contract("L", "layers", {"layers": "pkg.api\npkg.core | pkg.plugins\npkg.util"})]
INDEPENDENCE = [Contract("I", "independence", {"modules": "pkg.plugins\npkg.util\npkg.cli"})]


@pytest.mark.parametrize("contracts", [LAYERS, INDEPENDENCE], ids=["layers", "independence"])
@pytest.mark.parametrize("seed", range(6))
def test_layers_and_independence_are_consistent_with_the_reference(repo, seed, contracts):
    """The reference also reports INDIRECT chains, which we deliberately do not check (documented
    limitation), so equality is not expected. What must hold: every direct violation we report is
    one the reference reports, and if we find any the contract is broken in the reference too."""
    root, tmp = repo(200 + seed)
    ref_pairs, broken = reference(tmp, root, contracts)
    ours = engine_violations(root, tmp, contracts)
    assert ours <= ref_pairs, sorted(ours - ref_pairs)
    if ours:
        assert broken >= 1
