"""The hard wording tier: same labels and repositories, harder-to-read ADRs, two extra scenarios.

Guards: the PRIMARY benchmark must be unchanged by the tier's existence (existing results stay reproducible),
and every hard-tier case must keep exactly one targeted structural violation with the intended label."""
import hashlib
import json
import os

import pytest

from experiments.benchmark.generate import SCENARIOS, build_case, generate_benchmark
from experiments.benchmark.hard_wording import HARD_ONLY_SCENARIOS
from experiments.pipeline import CaseContext

ALL = {**SCENARIOS, **HARD_ONLY_SCENARIOS}


def digest(root):
    h = hashlib.sha256()
    for d, _, files in sorted(os.walk(root)):
        if ".git" in d.split(os.sep):
            continue
        for name in sorted(files):
            if name.endswith((".md", ".py", ".yaml", ".json")):
                h.update(os.path.join(d, name).replace(root, "").encode())
                h.update(open(os.path.join(d, name), "rb").read())
    return h.hexdigest()


@pytest.fixture(scope="module")
def hard_root(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("hard"))
    for scenario in ALL:
        build_case(root, f"{scenario.split('_')[0]}01", scenario, 7, wording="hard")
    return root


def test_unknown_wording_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_case(str(tmp_path), "A01", "A_plain_violation", 7, wording="nope")


def test_hard_only_scenarios_exist_only_in_the_hard_tier(tmp_path):
    primary = generate_benchmark(str(tmp_path / "p"), seed=7)
    assert not {c["scenario"] for c in primary["cases"]} & set(HARD_ONLY_SCENARIOS)
    assert len(primary["cases"]) == sum(n for _, n in SCENARIOS.values())


def test_building_hard_cases_does_not_change_primary_cases(tmp_path, hard_root):
    a = str(tmp_path / "a")
    build_case(a, "B01", "B_adr_permanent_exception", 7)
    first = digest(a)
    build_case(str(tmp_path / "x"), "B01", "B_adr_permanent_exception", 7, wording="hard")
    b = str(tmp_path / "b")
    build_case(b, "B01", "B_adr_permanent_exception", 7)
    assert digest(b) == first  # deterministic and unaffected


@pytest.mark.parametrize("scenario", sorted(ALL))
def test_each_hard_case_has_one_targeted_structural_violation_with_the_intended_label(hard_root, scenario):
    cid = f"{scenario.split('_')[0]}01"
    meta = json.load(open(f"{hard_root}/{cid}/labels.json"))
    assert meta["wording"] == "hard" and meta["label"] == ALL[scenario][0]
    ctx = CaseContext(hard_root, {"case_id": cid, "scenario": scenario, "split": "test", "path": cid})
    targeted = [f for f in ctx.findings if ctx.truth[ctx.edge(f)] != "conformant"]
    assert len(targeted) == 1 and targeted[0].status.value == "violation"


def test_hard_wording_actually_differs_from_primary_where_intended(tmp_path, hard_root):
    def adr_text(root, cid):
        d = f"{root}/{cid}/repo/architecture/adr"
        return "\n".join(open(f"{d}/{n}").read() for n in sorted(os.listdir(d)) if "Recorded for consistency" not in open(f"{d}/{n}").read())
    build_case(str(tmp_path), "E01", "E_adr_reaffirms_prohibition", 7)
    build_case(str(tmp_path), "K01", "K_adr_scope_mismatch", 7)
    assert "was not approved" in adr_text(hard_root, "E01") and "was not approved" not in adr_text(str(tmp_path), "E01")
    build_case(str(tmp_path / "k"), "K01", "K_adr_scope_mismatch", 7, wording="hard")
    assert adr_text(str(tmp_path / "k"), "K01") == adr_text(str(tmp_path), "K01")  # K is the unchanged control


def test_mixed_scenarios_name_both_modules_and_flip_which_one_is_permitted(hard_root):
    def decision(cid):
        d = f"{hard_root}/{cid}/repo/architecture/adr"
        return next(t for t in (open(f"{d}/{n}").read() for n in os.listdir(d)) if "must keep going" in t)
    for cid, target_permitted in (("L01", True), ("M01", False)):
        text = decision(cid)
        meta = json.load(open(f"{hard_root}/{cid}/labels.json"))
        stem = os.path.basename(meta["target_edge"]["source"]).rsplit(".", 1)[0]
        sentence_with_target = next(s for s in text.replace("\n", " ").split(". ") if f"`{stem}`" in s)
        assert ("may use" in sentence_with_target) is target_permitted
