import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules.loader import load_architecture_file
from analysis.dependency.repository_scanner import scan_repository

REPO_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "datasets",
    "sample-ecommerce",
)
ARCH_FILE = os.path.join(REPO_ROOT, "architecture", "rules.yaml")


@pytest.fixture(scope="session")
def architecture():
    arch, _mapping = load_architecture_file(ARCH_FILE)
    return arch


@pytest.fixture(scope="session")
def component_mapping():
    _arch, mapping = load_architecture_file(ARCH_FILE)
    return mapping


@pytest.fixture(scope="session")
def scan_result(component_mapping):
    return scan_repository(REPO_ROOT, component_mapping)


# ---- shared benchmark fixtures (one generated case per scenario) -------------
import json as _json

import pytest as _pytest


@_pytest.fixture(scope="session")
def bench_root(tmp_path_factory):
    """One case per scenario, generated once per test session (seed 7)."""
    from experiments.benchmark.generate import SCENARIOS, build_case

    root = tmp_path_factory.mktemp("bench")
    for scenario in SCENARIOS:
        build_case(str(root), f"{scenario.split('_')[0]}01", scenario, 7)
    return str(root)


@_pytest.fixture(scope="session")
def bench_cases(bench_root):
    """{scenario_letter: CaseContext} for the one-per-scenario benchmark."""
    from experiments.pipeline import CaseContext

    out = {}
    for letter in "ABCDEFGHJK":
        meta = _json.load(open(f"{bench_root}/{letter}01/labels.json"))
        entry = {"case_id": f"{letter}01", "scenario": meta["scenario"], "split": "test", "path": f"{letter}01"}
        out[letter] = CaseContext(bench_root, entry)
    return out


@_pytest.fixture(scope="session")
def bench_root_heldout(tmp_path_factory):
    """The same ten cases, generated with the held-out ADR wordings."""
    from experiments.benchmark.generate import SCENARIOS, build_case

    root = tmp_path_factory.mktemp("bench_heldout")
    for scenario in SCENARIOS:
        build_case(str(root), f"{scenario.split('_')[0]}01", scenario, 7, wording="heldout")
    return str(root)


@_pytest.fixture(scope="session")
def bench_cases_heldout(bench_root_heldout):
    from experiments.pipeline import CaseContext

    out = {}
    for letter in "ABCDEFGHJK":
        meta = _json.load(open(f"{bench_root_heldout}/{letter}01/labels.json"))
        entry = {"case_id": f"{letter}01", "scenario": meta["scenario"], "split": "test", "path": f"{letter}01"}
        out[letter] = CaseContext(bench_root_heldout, entry)
    return out
