"""End-to-end test of the real-repository pipeline on a tiny repository with a KNOWN history.

The tools in experiments/real_repos orchestrate `git` and the reference `lint-imports`, so they cannot be
unit-tested in isolation. This builds a small repo whose story is known by construction:

    2024-01-05  scaffold
    2024-02-05  core reaches UP into api          <- a layering violation appears
    2024-03-05  import-linter contracts adopted   <- the violation exists at adoption
    2024-04-05  the upward import is removed
    2024-05-05  unrelated change

and checks that evaluation (engine vs reference tool) and the lifecycle trace report exactly that story.
Skipped when import-linter is not installed.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import date

import pytest

pytest.importorskip("importlinter")
pytestmark = pytest.mark.skipif(shutil.which("lint-imports") is None, reason="lint-imports executable not found")

from experiments.benchmark.gitbuilder import GitBuilder

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*args):
    return subprocess.run([sys.executable, "-m", *args], cwd=BACKEND, capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def story(tmp_path_factory):
    root = tmp_path_factory.mktemp("real")
    g = GitBuilder(str(root / "repo"))
    for p in ("src/pkg", "src/pkg/api", "src/pkg/core"):
        g.write(f"{p}/__init__.py", "")
    g.write("src/pkg/api/handlers.py", "VALUE = 1\n")
    g.write("src/pkg/core/engine.py", "VALUE = 2\n")
    g.commit("scaffold", date(2024, 1, 5))
    g.write("src/pkg/core/engine.py", "from pkg.api import handlers\nVALUE = 2\n")
    g.commit("core reaches up into api", date(2024, 2, 5))
    g.write(".importlinter", "[importlinter]\nroot_package = pkg\n\n[importlinter:contract:layers]\nname = Layers\ntype = layers\nlayers =\n    pkg.api\n    pkg.core\n")
    g.commit("adopt import-linter contracts", date(2024, 3, 5))
    g.write("src/pkg/core/engine.py", "VALUE = 2\n")
    g.commit("remove the upward import", date(2024, 4, 5))
    g.append("src/pkg/api/handlers.py", "# touch\n")
    g.commit("later change", date(2024, 5, 5))
    out = str(root / "out")
    proc = run("experiments.real_repos.evaluate_repo", "--repo", g.path, "--config-file", ".importlinter", "--out", out,
               "--samples", "1", "--pre-samples", "1")
    assert proc.returncode == 0, proc.stderr[-800:]
    return g, out, {r["label"]: r for r in json.load(open(os.path.join(out, "evaluation.json")))["refs"]}


def test_the_translated_rules_are_the_contracts_and_nothing_else(story):
    _, out, _ = story
    text = open(os.path.join(out, "rules.yaml")).read()
    assert "import_resolution: anchored" in text and "forbidden" in text


def test_engine_finds_the_violation_exactly_while_it_exists(story):
    _, _, refs = story
    assert refs["early_1"]["untolerated"] == 1          # 2024-02-05: just introduced
    assert refs["adoption"]["untolerated"] == 1         # 2024-03-05: present when the contracts were adopted
    assert refs["sample_1"]["untolerated"] == 0 and refs["HEAD"]["untolerated"] == 0   # fixed later


def test_the_reference_tool_agrees_at_every_commit_with_nothing_missed_or_invented(story):
    _, _, refs = story
    for label, r in refs.items():
        a = r["agreement"]
        assert a["engine_only"] == [], label            # nothing we report that the reference does not
        assert a["also_reported_by_reference"] == a["engine_direct_untolerated_pairs"], label
        assert (r["reference"]["broken"] or 0) == (1 if r["untolerated"] else 0), label


def test_retrospective_mode_is_used_before_adoption_and_the_teams_own_contracts_after(story):
    _, _, refs = story
    assert "retrospective" in refs["pre_adoption"]["intent_source"]
    assert refs["adoption"]["intent_source"].startswith(".importlinter")


def test_lifecycle_trace_reports_the_scripted_introduction_and_removal(story):
    g, out, _ = story
    proc = run("experiments.real_repos.trace_violations", "--repo-src", os.path.join(g.path, "src"),
               "--evaluation", os.path.join(out, "evaluation.json"), "--refs", "early_1")
    assert proc.returncode == 0, proc.stderr[-800:]
    text = proc.stdout
    assert "pkg/core/engine.py -> pkg/api/handlers.py" in text
    assert "introduced 2024-02-05" in text and "core reaches up into api" in text
    assert "removed 2024-04-05" in text and "remove the upward import" in text
