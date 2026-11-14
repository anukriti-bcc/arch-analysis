"""Run the project's conformance engine over a real repository's history using the
repository's OWN import-linter contracts as architectural intent, and cross-check the
result against the reference tool (`lint-imports`).

For each chosen commit ("ref"):
  1. check out a worktree, locate the root package, scan with the HEAD contracts
     translated by import_linter_importer.py
  2. tag violations the team documented as tolerated (ignore_imports)
  3. run lint-imports with the SAME contracts on the SAME tree
  4. report agreement on direct module-level violating imports

Usage (from backend/):
  python -m experiments.real_repos.evaluate_repo --repo ../datasets/real/sqlfluff \
      --config-file pyproject.toml --out ../results/real/sqlfluff \
      --extra-ref pre_unpick=25edad331^ --extra-ref post_unpick=25edad331
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from analysis.conformance.engine import analyze_conformance
from analysis.dependency.repository_scanner import scan_repository
from experiments.real_repos.import_linter_importer import (
    build_architecture, parse_config, prune_contracts, tolerated_list, to_ini, write_outputs)
from models.finding import FindingStatus
from rules.loader import load_architecture_file


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def module_of(rel: str) -> str:
    rel = rel[:-3] if rel.endswith(".py") else rel
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return rel.replace("/", ".")


def find_scan_root(repo: str, ref: str, root_pkg: str) -> str | None:
    """Directory (relative to repo root, '' for the root itself) that CONTAINS the root package."""
    top = root_pkg.split(".")[0]
    cands = [p for p in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines()
             if p.endswith(f"{top}/__init__.py") and not re.search(r"(^|/)(tests?|docs?|plugins|examples|benchmarks)/", p)]
    if not cands:
        return None
    best = min(cands, key=lambda p: p.count("/"))
    parent = best[: -len(f"{top}/__init__.py")].rstrip("/")
    return parent


def config_slice(text: str) -> str:
    """The [tool.importlinter] part of a pyproject.toml (for running the reference tool at old commits)."""
    out, on = [], False
    for line in text.splitlines():
        if re.match(r"^\[+tool\.importlinter", line):
            on = True
        elif re.match(r"^\[", line):
            on = False
        if on:
            out.append(line)
    return "\n".join(out) + "\n"


def run_reference(tree: str, scan_root_abs: str, cfg_dir: str, cfg_name: str, cfg_text: str) -> dict:
    os.makedirs(cfg_dir, exist_ok=True)
    cfgpath = os.path.join(cfg_dir, os.path.basename(cfg_name))
    with open(cfgpath, "w") as fh:
        fh.write(config_slice(cfg_text) if cfg_name.endswith(".toml") else cfg_text)
    env = {**os.environ, "PYTHONPATH": scan_root_abs}
    r = subprocess.run(["lint-imports", "--config", cfgpath], cwd=tree, env=env, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    pairs = set()
    for m in re.finditer(r"^\s*-?\s*([A-Za-z_][\w.]*) -> ([A-Za-z_][\w.]*)", out, re.M):
        pairs.add((m.group(1), m.group(2)))
    kept = re.search(r"(\d+) kept, (\d+) broken", out)
    return {"returncode": r.returncode, "kept": int(kept.group(1)) if kept else None,
            "broken": int(kept.group(2)) if kept else None, "pairs": sorted(pairs), "tail": out[-400:]}


CFG_CANDIDATES = (".importlinter", "setup.cfg", "pyproject.toml", "tox.ini")


def intent_at(repo: str, ref: str, name: str, tmp: str, label: str):
    """The team's own contracts as they existed at `ref` (None if the commit has none)."""
    files = set(git(repo, "ls-tree", "--name-only", ref).splitlines())
    for cfg in CFG_CANDIDATES:
        if cfg not in files:
            continue
        text = git(repo, "show", f"{ref}:{cfg}", check=False)
        if "importlinter" not in text:
            continue
        try:
            opts, contracts = parse_config(cfg, text)
        except Exception:
            continue
        if not contracts:
            continue
        root_pkg = str(opts.get("root_package") or opts.get("root_packages", "")).split()[0].strip('",[]')
        arch, rep = build_architecture(contracts, root_pkg, name)
        tol = tolerated_list(contracts)
        rp, _ = write_outputs(arch, tol, os.path.join(tmp, f"intent_{label}"))
        return {"rules_path": rp, "tolerated": tol, "modules": [m.replace("/", ".") for m in arch["component_mapping"]],
                "cfg_text": text, "cfg_name": cfg, "root_pkg": root_pkg, "report": rep, "source": f"{cfg} @ {ref[:9]}"}
    return None


def pruned_head_intent(repo, ref, head_opts, head_contracts, root_pkg, name, tmp, label):
    """Today's contracts restricted to the modules that exist at `ref` (retrospective application)."""
    scan_rel = find_scan_root(repo, ref, root_pkg)
    if scan_rel is None:
        return None
    files = set(git(repo, "ls-tree", "-r", "--name-only", ref).splitlines())
    pre = (scan_rel + "/") if scan_rel else ""

    def present(m: str) -> bool:
        base = pre + m.replace(".", "/")
        return base + ".py" in files or any(f.startswith(base + "/") for f in files)

    cons = prune_contracts(head_contracts, present)
    if not cons:
        return None
    arch, rep = build_architecture(cons, root_pkg, name)
    tol = tolerated_list(cons)
    rp, _ = write_outputs(arch, tol, os.path.join(tmp, f"intent_{label}"))
    return {"rules_path": rp, "tolerated": tol, "modules": [m.replace("/", ".") for m in arch["component_mapping"]],
            "cfg_text": to_ini(head_opts, cons), "cfg_name": ".importlinter", "root_pkg": root_pkg, "report": rep,
            "source": f"HEAD contracts pruned to modules present @ {ref[:9]} (retrospective)"}


def coverage(repo: str, ref: str, scan_root: str, modules: list[str]) -> float:
    files = set(git(repo, "ls-tree", "-r", "--name-only", ref).splitlines())
    pre = (scan_root + "/") if scan_root else ""
    ok = 0
    for m in modules:
        base = pre + m.replace(".", "/")
        if base + ".py" in files or any(f.startswith(base + "/") for f in files):
            ok += 1
    return ok / max(len(modules), 1)


def evaluate_ref(repo, label, ref, intent, tmp, do_ref):
    rules_path, tolerated, arch_modules = intent["rules_path"], intent["tolerated"], intent["modules"]
    cfg_text, cfg_name, root_pkg = intent["cfg_text"], intent["cfg_name"], intent["root_pkg"]
    sha = git(repo, "rev-parse", "--short=9", ref).strip()
    date = git(repo, "log", "-1", "--format=%as", ref).strip()
    scan_rel = find_scan_root(repo, ref, root_pkg)
    row = {"label": label, "ref": ref, "sha": sha, "date": date, "intent_source": intent["source"],
           "contracts": intent["report"]["contracts_used"], "tolerated_declared": len(tolerated)}
    if scan_rel is None:
        return {**row, "error": f"root package '{root_pkg}' not found at this commit"}
    tree = os.path.join(tmp, f"wt_{label}")
    git(repo, "worktree", "add", "-f", "--detach", tree, sha)
    try:
        scan_abs = os.path.join(tree, scan_rel) if scan_rel else tree
        architecture, mapping = load_architecture_file(rules_path)
        scan = scan_repository(scan_abs, mapping)
        findings = analyze_conformance(scan.components, scan.dependencies, architecture)
        viol = [f for f in findings if f.status == FindingStatus.VIOLATION]
        tol = {(t["importer"], t["imported"]) for t in tolerated}
        edges, untol = {}, {}
        for f in viol:
            s, t = f.source["id"], f.target["id"]
            pair = (module_of(s), module_of(t))
            edges[(s, t)] = pair
            if pair not in tol:
                untol[(s, t)] = pair
        row.update(
            scan_root=scan_rel, py_files=len(scan.components), dependencies=len(scan.dependencies),
            module_coverage=round(coverage(repo, sha, scan_rel, arch_modules), 2),
            violations=len(edges), tolerated=len(edges) - len(untol), untolerated=len(untol),
            untolerated_edges=[{"source": s, "target": t, "rule": next(f.rule_id for f in viol if f.source["id"] == s and f.target["id"] == t)}
                               for (s, t) in sorted(untol)],
        )
        if do_ref:
            ref_res = run_reference(tree, scan_abs, os.path.join(tmp, f"cfg_{label}"), cfg_name, cfg_text)
            mine = {p for p in untol.values()}
            theirs = set(map(tuple, ref_res["pairs"]))
            row["reference"] = {k: ref_res[k] for k in ("returncode", "kept", "broken")}
            row["reference"]["pairs_reported"] = len(theirs)
            row["agreement"] = {
                "engine_direct_untolerated_pairs": len(mine),
                "also_reported_by_reference": len(mine & theirs),
                "engine_only": sorted(f"{a} -> {b}" for a, b in mine - theirs)[:15],
                "reference_only_sample": sorted(f"{a} -> {b}" for a, b in theirs - mine)[:15],
            }
            if ref_res["broken"] is None:
                row["reference"]["tail"] = ref_res["tail"]
        return row
    finally:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", tree], capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--config-file", default="pyproject.toml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=6, help="evenly spaced commits between adoption and HEAD")
    ap.add_argument("--pre-samples", type=int, default=0, help="evenly spaced commits BEFORE adoption (retrospective)")
    ap.add_argument("--extra-ref", action="append", default=[], help="label=ref")
    ap.add_argument("--no-reference", action="store_true")
    ap.add_argument("--intent", choices=["head", "ref"], default="ref",
                    help="head: apply today's contracts to every commit; ref: use the contracts as they existed at each commit "
                         "(falls back to head's before adoption)")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    text = open(os.path.join(repo, a.config_file), encoding="utf-8").read()
    opts, contracts = parse_config(a.config_file, text)
    root_pkg = str(opts.get("root_package") or opts.get("root_packages", "")).split()[0].strip('",[]')
    arch, rep = build_architecture(contracts, root_pkg, os.path.basename(repo))
    tol = tolerated_list(contracts)
    rules_path, _ = write_outputs(arch, tol, a.out)
    print("importer:", rep, "| tolerated:", len(tol))

    adopt = git(repo, "log", "-S", "importlinter", "--reverse", "--format=%H").split()[0]
    head = git(repo, "rev-parse", "HEAD").strip()
    after = git(repo, "rev-list", "--reverse", f"{adopt}..{head}").split()
    before = git(repo, "rev-list", "--reverse", adopt).split()
    pstep = max(len(before) // (a.pre_samples + 1), 1)
    refs = [(f"early_{i + 1}", before[min(i * pstep + pstep, len(before) - 1)]) for i in range(a.pre_samples)]
    refs += [("pre_adoption", adopt + "^"), ("adoption", adopt)]
    for kv in a.extra_ref:
        k, v = kv.split("=", 1)
        refs.append((k, v))
    step = max(len(after) // (a.samples + 1), 1)
    refs += [(f"sample_{i + 1}", after[min(i * step + step, len(after) - 1)]) for i in range(a.samples)]
    refs.append(("HEAD", head))

    head_intent = {"rules_path": rules_path, "tolerated": tol, "modules": [m.replace("/", ".") for m in arch["component_mapping"]],
                   "cfg_text": text, "cfg_name": a.config_file, "root_pkg": root_pkg, "report": rep, "source": f"{a.config_file} @ HEAD (retrospective)"}
    results = []
    tmp = tempfile.mkdtemp(prefix="evalrepo_")
    try:
        for label, ref in refs:
            intent = intent_at(repo, ref, os.path.basename(repo), tmp, label) if a.intent == "ref" else None
            if intent is None and label != "HEAD":
                intent = pruned_head_intent(repo, ref, opts, contracts, root_pkg, os.path.basename(repo), tmp, label)
            intent = intent or head_intent
            r = evaluate_ref(repo, label, ref, intent, tmp, not a.no_reference)
            results.append(r)
            ag = r.get("agreement", {})
            print(f"  {label:13} {r.get('date')} contracts={r.get('contracts')} declared_tol={r.get('tolerated_declared')} cov={r.get('module_coverage')} "
                  f"viol={r.get('violations')} (tol {r.get('tolerated')}, UNtol {r.get('untolerated')}) "
                  f"| reference: broken={r.get('reference', {}).get('broken')} listed={r.get('reference', {}).get('pairs_reported')} "
                  f"agree={ag.get('also_reported_by_reference')}/{ag.get('engine_direct_untolerated_pairs')} {r.get('error', '')}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(a.out, "evaluation.json"), "w") as fh:
        json.dump({"importer_report": rep, "tolerated": tol, "refs": results}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
