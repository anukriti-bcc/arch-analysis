"""Shortlist real repositories for the case study, starting from the
ADR-Study-Dataset (Buchgeher et al. 2023, 921 GitHub repositories).

The dataset holds only crawl metadata (ADR paths, template, status, dates), not
code, ADR text, language or labels. So this script:

  Stage 1  metadata filter   ADR count, Nygard/MADR share        (no network)
  Stage 2  language filter   blobless shallow clone + `git ls-tree`: count .py
                             files without downloading file contents
  Stage 3  ADR content scan  fetch ONLY the ADR files, parse them with the
                             project's own parser, score how much they talk
                             about structure/layering/dependencies
  Output   candidates.csv + candidates.md, ranked

It only RANKS. Choosing repos, writing rules.yaml and labelling edges stay manual.

Usage (from backend/):
    git clone https://github.com/software-competence-center-hagenberg/ADR-Study-Dataset ../datasets/adr-study
    python -m experiments.real_repos.select_candidates \
        --dataset ../datasets/adr-study/repositories --work ../datasets/real_candidates \
        --min-adrs 10 --min-py-files 30 --workers 8
Re-running resumes: stage-2/3 results are cached in <work>/cache.json.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from analysis.intent.adr import parse_adr

ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs", ".cs", ".php", ".kt", ".scala", ".c", ".cc", ".cpp", ".swift"}

# Language that constrains structure (what the conformance engine can actually check).
STRUCT_PATTERNS = {
    "prohibition": r"\b(must not|should not|shall not|may not|never|forbid|forbidden|prohibit|not allowed|do not (?:import|depend|call|access))\b",
    "dependency": r"\b(depend(?:s|ency|encies)? on|import(?:s|ed)?|couple[sd]?|coupling|call(?:s|ed)? (?:the|into)|access(?:es)? (?:the|directly))\b",
    "layering": r"\b(layer(?:s|ed|ing)?|tier|hexagonal|clean architecture|onion|ports? and adapters|boundar(?:y|ies)|bounded context)\b",
    "modules": r"\b(module|package|component|subsystem|namespace|domain|infrastructure|adapter|repository|controller|service layer)\b",
}


def sh(args: list[str], cwd: str | None = None, timeout: int = 180) -> str | None:
    try:
        r = subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


# ----------------------------------------------------------------------------- stage 1
def load_metadata(dataset_dir: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(os.path.join(dataset_dir, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            rows.append(json.load(fh))
    return rows


def stage1(rows: list[dict], min_adrs: int, min_formal_share: float) -> list[dict]:
    keep = []
    for r in rows:
        files = r.get("adrFiles", [])
        if len(files) < min_adrs:
            continue
        tm = Counter(a.get("template") for a in files)
        formal = (tm.get("Nygard", 0) + tm.get("Madr", 0)) / len(files)
        if formal < min_formal_share:
            continue
        r["_formal_share"] = round(formal, 2)
        keep.append(r)
    return keep


# ----------------------------------------------------------------------------- stage 2
def slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", url.removeprefix("https://github.com/").removesuffix(".git"))


def blobless_clone(url: str, dest: str) -> bool:
    if os.path.isdir(os.path.join(dest, ".git")) or os.path.isfile(os.path.join(dest, "HEAD")):
        return True
    out = sh(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", url, dest], timeout=240)
    return out is not None and os.path.isdir(os.path.join(dest, ".git"))


def stage2(meta: dict, work: str) -> dict:
    url = meta["repositoryUrl"]
    dest = os.path.join(work, "clones", slug(url))
    res = {"url": url, "slug": slug(url), "cloned": False}
    if not blobless_clone(url, dest):
        res["note"] = "clone failed (deleted/private/moved since 2022 crawl?)"
        return res
    tree = sh(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=dest)
    if tree is None:
        res["note"] = "ls-tree failed"
        return res
    paths = tree.split("\n")
    ext = Counter(os.path.splitext(p)[1].lower() for p in paths if os.path.splitext(p)[1].lower() in CODE_EXT)
    code_total = sum(ext.values()) or 1
    pyfiles = [p for p in paths if p.endswith(".py")]
    tests = sum(1 for p in pyfiles if re.search(r"(^|/)(tests?|test_[^/]*|[^/]*_test)\b", p))
    pkg_dirs = {os.path.dirname(p) for p in pyfiles if not re.search(r"(^|/)(tests?|docs?|examples?|scripts?)(/|$)", p)}
    # ADRs still present at HEAD? (dataset is from Jan-Feb 2022)
    present = set(paths)
    still_paths = []
    for a in meta["adrFiles"]:
        cand = "/".join(x for x in (a.get("adrDirectory"), a["path"]) if x)
        if cand in present:
            still_paths.append(cand)
    still = len(still_paths)
    res.update(
        cloned=True,
        py_files=len(pyfiles),
        py_share=round(len(pyfiles) / code_total, 2),
        py_non_test_files=len(pyfiles) - tests,
        py_dirs=len(pkg_dirs),
        top_ext=dict(ext.most_common(3)),
        adrs_at_head=still,
        adr_paths_head=still_paths,
    )
    return res


# ----------------------------------------------------------------------------- stage 3
def stage3(meta: dict, s2: dict, work: str) -> dict:
    dest = os.path.join(work, "clones", s2["slug"])
    # full commit graph (still blobless, so cheap): history depth decides whether evolution evidence is usable
    sh(["git", "fetch", "-q", "--unshallow", "--filter=blob:none"], cwd=dest, timeout=300)
    commits = int((sh(["git", "rev-list", "--count", "HEAD"], cwd=dest) or "0").strip() or 0)
    span = (sh(["git", "log", "--reverse", "--format=%as"], cwd=dest) or "").split("\n")[0].strip()
    last = (sh(["git", "log", "-1", "--format=%as"], cwd=dest) or "").strip()
    py_commits = len((sh(["git", "log", "--format=%h", "--", "*.py"], cwd=dest) or "").split())
    # only paths that still exist at HEAD: one missing pathspec makes git abort the whole checkout
    wanted = s2.get("adr_paths_head", [])[:400]
    if wanted:
        sh(["git", "checkout", "-q", "HEAD", "--", *wanted], cwd=dest, timeout=240)
    texts, statuses = [], Counter()
    for rel in wanted:
        fp = os.path.join(dest, rel)
        if not os.path.isfile(fp):
            continue
        try:
            text = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        adr = parse_adr(rel, text)
        statuses[adr.status] += 1
        hits = {k: len(re.findall(p, text, re.I)) for k, p in STRUCT_PATTERNS.items()}
        families = sum(1 for v in hits.values() if v)
        # an ADR is "structural" if it combines a prohibition/dependency statement with layering/module talk
        structural = (hits["prohibition"] or hits["dependency"]) and (hits["layering"] or hits["modules"]) and families >= 3
        texts.append({"path": rel, "status": adr.status, "chars": len(text), "structural": bool(structural), "hits": hits, "title": adr.title})
    n = len(texts)
    sc = [t for t in texts if t["structural"]]
    return {
        "commits": commits, "py_commits": py_commits, "first_commit_date": span, "last_commit_date": last,
        "adrs_read": n,
        "structural_adrs": len(sc),
        "structural_share": round(len(sc) / n, 2) if n else 0.0,
        "active_structural": sum(1 for t in sc if t["status"] not in ("superseded", "deprecated", "rejected")),
        "status_counts": dict(statuses),
        "structural_examples": [{"path": t["path"], "title": t["title"]} for t in sc[:6]],
    }


# ----------------------------------------------------------------------------- driver
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="path to ADR-Study-Dataset/repositories")
    ap.add_argument("--work", required=True)
    ap.add_argument("--min-adrs", type=int, default=10)
    ap.add_argument("--min-formal-share", type=float, default=0.5, help="share of ADRs using Nygard/MADR")
    ap.add_argument("--min-py-files", type=int, default=30)
    ap.add_argument("--min-py-share", type=float, default=0.4)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="debug: only first N stage-1 survivors")
    a = ap.parse_args()

    os.makedirs(a.work, exist_ok=True)
    cache_path = os.path.join(a.work, "cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    rows = load_metadata(a.dataset)
    s1 = stage1(rows, a.min_adrs, a.min_formal_share)
    if a.limit:
        s1 = s1[: a.limit]
    print(f"stage 1: {len(rows)} -> {len(s1)} repos (>= {a.min_adrs} ADRs, >= {a.min_formal_share:.0%} Nygard/MADR)")

    todo = [m for m in s1 if slug(m["repositoryUrl"]) not in cache]
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(stage2, m, a.work): m for m in todo}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            cache[r["slug"]] = {"s2": r}
            if i % 20 == 0:
                print(f"  stage 2: {i}/{len(todo)}")
                json.dump(cache, open(cache_path, "w"))
    json.dump(cache, open(cache_path, "w"))

    s2ok = []
    for m in s1:
        r = cache[slug(m["repositoryUrl"])]["s2"]
        if r.get("cloned") and r.get("py_files", 0) >= a.min_py_files and r.get("py_share", 0) >= a.min_py_share:
            s2ok.append((m, r))
    cloned = sum(1 for m in s1 if cache[slug(m["repositoryUrl"])]["s2"].get("cloned"))
    print(f"stage 2: {cloned}/{len(s1)} cloned; {len(s2ok)} are Python-heavy (>= {a.min_py_files} .py files, >= {a.min_py_share:.0%} of code files)")

    todo3 = [(m, r) for m, r in s2ok if "s3" not in cache[r["slug"]]]
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(stage3, m, r, a.work): r["slug"] for m, r in todo3}
        for f in as_completed(futs):
            cache[futs[f]]["s3"] = f.result()
    json.dump(cache, open(cache_path, "w"))

    out = []
    for m, r in s2ok:
        s3 = cache[r["slug"]]["s3"]
        out.append({
            "repo": r["url"].removeprefix("https://github.com/").removesuffix(".git"),
            "adrs_in_dataset": m["numAdrFiles"], "adrs_at_head": r["adrs_at_head"], "adrs_read": s3["adrs_read"],
            "formal_share": m["_formal_share"], "py_files": r["py_files"], "py_share": r["py_share"], "py_dirs": r["py_dirs"],
            "structural_adrs": s3["structural_adrs"], "active_structural": s3["active_structural"], "structural_share": s3["structural_share"],
            "commits": s3["commits"], "py_commits": s3["py_commits"],
            "first_commit": s3["first_commit_date"], "last_commit": s3["last_commit_date"],
            "examples": " | ".join(e["path"] for e in s3["structural_examples"][:3]),
        })
    out.sort(key=lambda r: (r["active_structural"], r["structural_adrs"], r["adrs_read"]), reverse=True)

    csv_path = os.path.join(a.work, "candidates.csv")
    if out:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
    with open(os.path.join(a.work, "candidates.md"), "w", encoding="utf-8") as fh:
        fh.write("# Real-repo candidates (ranked by active structural ADRs)\n\n")
        fh.write("`structural` = ADR text combines prohibition/dependency wording with layering/module wording. "
                 "A keyword screen, NOT a judgement: read the top ADRs yourself.\n\n")
        fh.write("| repo | ADRs | structural | active structural | .py files | .py commits | last commit |\n|---|---|---|---|---|---|---|\n")
        for r in out[:40]:
            fh.write(f"| {r['repo']} | {r['adrs_read']} | {r['structural_adrs']} | {r['active_structural']} | {r['py_files']} | {r['py_commits']} | {r['last_commit']} |\n")
    print(f"stage 3: wrote {len(out)} ranked candidates -> {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
