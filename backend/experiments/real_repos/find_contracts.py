"""From the import-linter dependents list, find repos that really define architecture
contracts AND have enough Git history around them to be useful for evaluation.

Per repo (blobless clones: commit graph + only the few config files, no source blobs):
  A  ls-tree HEAD: Python size, locate .importlinter / setup.cfg / pyproject.toml / tox.ini
  B  read those config files, extract contract types, ignore_imports count
  C  history: when the contracts first appeared, commits before/after, config churn

Usage:  python find_contracts.py --deps dependents.csv --work work --min-stars 10 --workers 8
Resumable (work/cache.json). Output: contracts.csv, contracts.md
"""
from __future__ import annotations
import argparse, csv, json, os, re, subprocess, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
CFG_NAMES = {".importlinter", "setup.cfg", "pyproject.toml", "tox.ini"}
MAX_PY_FILES = 3000     # skip monsters; the analyzer is not built for them


def sh(args, cwd=None, timeout=180):
    try:
        r = subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


def slug(repo): return repo.replace("/", "__")


def parse_contracts(path: str, text: str) -> dict | None:
    """Return {'types': Counter, 'ignores': int, 'root': str} if this file defines import-linter config."""
    base = os.path.basename(path)
    if base == ".importlinter":
        body = text
    elif base == "pyproject.toml":
        if "tool.importlinter" not in text:
            return None
        body = text
    else:
        if "importlinter" not in text:
            return None
        body = text
    types = Counter()
    if base == "pyproject.toml":
        for chunk in re.split(r"\[\[tool\.importlinter\.contracts\]\]", body)[1:]:
            chunk = re.split(r"\n\[", chunk)[0]
            m = re.search(r'^\s*type\s*=\s*["\']([\w.:-]+)["\']', chunk, re.M)
            if m:
                types[m.group(1)] += 1
    else:
        for sec in re.split(r"\n(?=\[)", body):
            if sec.lstrip().startswith("[importlinter:contract"):
                m = re.search(r"^\s*type\s*[=:]\s*([\w.:-]+)", sec, re.M)
                if m:
                    types[m.group(1)] += 1
    if not types:
        return None
    ignores = len(re.findall(r"->", body))
    root = re.search(r"root_packages?\s*[=:]\s*\[?\s*([\w.\"',\s\n-]+?)(?:\]|\n\[|\n\S)", body)
    return {"types": dict(types), "ignores": ignores, "root": (root.group(1).strip().replace("\n", ",")[:80] if root else "")}


def analyse(repo: str, stars: int, work: str) -> dict:
    res = {"repo": repo, "stars": stars, "status": "ok"}
    dest = os.path.join(work, "clones", slug(repo))
    if not os.path.isdir(os.path.join(dest, ".git")) and not os.path.isfile(os.path.join(dest, "HEAD")):
        if sh(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout",
               f"https://github.com/{repo}.git", dest], timeout=240) is None or not os.path.isdir(dest):
            res["status"] = "clone_failed"
            return res
    tree = sh(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=dest)
    if tree is None:
        res["status"] = "no_tree"
        return res
    paths = tree.split("\n")
    pyfiles = [p for p in paths if p.endswith(".py")]
    res["py_files"] = len(pyfiles)
    if len(pyfiles) < 10:
        res["status"] = "too_small"
        return res
    if len(pyfiles) > MAX_PY_FILES:
        res["status"] = "too_big"
        return res
    cfgs = [p for p in paths if os.path.basename(p) in CFG_NAMES and p.count("/") <= 3][:25]
    if not cfgs:
        res["status"] = "no_config_files"
        return res
    sh(["git", "checkout", "-q", "HEAD", "--", *cfgs], cwd=dest, timeout=240)
    found = []
    for p in cfgs:
        try:
            text = open(os.path.join(dest, p), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        c = parse_contracts(p, text)
        if c:
            found.append({"file": p, **c})
    if not found:
        res["status"] = "no_contracts"
        return res
    types = Counter()
    for f in found:
        types.update(f["types"])
    main = max(found, key=lambda f: sum(f["types"].values()))
    res.update(
        contract_files=[f["file"] for f in found],
        contracts=sum(types.values()), types=dict(types),
        ignore_imports=sum(f["ignores"] for f in found), root=main["root"], main_file=main["file"],
    )
    # ---- history (commit graph only; blobs of the config file are fetched on demand)
    sh(["git", "fetch", "-q", "--unshallow", "--filter=blob:none"], cwd=dest, timeout=420)
    total = int((sh(["git", "rev-list", "--count", "HEAD"], cwd=dest) or "0").strip() or 0)
    res["commits"] = total
    f = main["file"]
    if os.path.basename(f) == ".importlinter":
        first = (sh(["git", "log", "--diff-filter=A", "--reverse", "--format=%H %as", "--", f], cwd=dest) or "").split("\n")[0]
        churn = len((sh(["git", "log", "--format=%h", "--", f], cwd=dest) or "").split())
    else:
        # repo-wide (NOT limited to file f): the config may have been moved between files
        # (setup.cfg -> pyproject.toml), and the move is not the adoption of the contracts
        first = (sh(["git", "log", "-Simportlinter", "--reverse", "--format=%H %as"], cwd=dest, timeout=300) or "").split("\n")[0]
        churn = len((sh(["git", "log", "-G(ignore_imports|source_modules|forbidden_modules|layers|containers|->)", "--format=%h", "--", f],
                        cwd=dest, timeout=240) or "").split())
    if not first.strip():
        res["status"] = "history_unresolved"
        return res
    sha, date = first.split()[:2]
    before = int((sh(["git", "rev-list", "--count", sha + "^"], cwd=dest) or "0").strip() or 0)
    res.update(first_contract_commit=sha[:8], first_contract_date=date, commits_before=before,
               commits_after=total - before, config_churn_commits=churn)
    res["py_commits_after"] = len((sh(["git", "log", sha + "..HEAD", "--format=%h", "--", "*.py"], cwd=dest) or "").split())
    return res


def good(r: dict, min_after: int, min_before: int) -> bool:
    t = r.get("types", {})
    return (r.get("status") == "ok" and (t.get("layers") or t.get("forbidden"))
            and r.get("commits_after", 0) >= min_after and r.get("commits_before", 0) >= min_before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deps", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--min-stars", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-after", type=int, default=50)
    ap.add_argument("--min-before", type=int, default=30)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    cp = os.path.join(a.work, "cache.json")
    cache = json.load(open(cp)) if os.path.exists(cp) else {}
    rows = [(r["repo"], int(r["stars"])) for r in csv.DictReader(open(a.deps)) if int(r["stars"]) >= a.min_stars]
    rows.sort(key=lambda x: -x[1])
    if a.limit:
        rows = rows[: a.limit]
    todo = [r for r in rows if r[0] not in cache]
    print(f"{len(rows)} repos with >= {a.min_stars} stars; {len(todo)} still to analyse")
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(analyse, repo, st, a.work): repo for repo, st in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                cache[futs[f]] = f.result()
            except Exception as e:  # keep going; record the failure
                cache[futs[f]] = {"repo": futs[f], "status": f"error: {e}"}
            if i % 10 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
                json.dump(cache, open(cp, "w"))
    json.dump(cache, open(cp, "w"))
    allr = [cache[r[0]] for r in rows if r[0] in cache]
    print("status counts:", dict(Counter(r.get("status", "?").split(":")[0] for r in allr)))
    keep = [r for r in allr if good(r, a.min_after, a.min_before)]
    keep.sort(key=lambda r: (-(r.get("ignore_imports", 0) > 0), -r["commits_after"]))
    cols = ["repo", "stars", "py_files", "commits", "contracts", "types", "ignore_imports", "root", "main_file",
            "first_contract_date", "commits_before", "commits_after", "py_commits_after", "config_churn_commits"]
    with open(os.path.join(a.work, "contracts.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(keep)
    with open(os.path.join(a.work, "contracts.md"), "w") as fh:
        fh.write("# Repos with layers/forbidden contracts and usable history\n\n")
        fh.write("| repo | stars | .py files | contracts | types | ignore_imports | contract added | commits before | after | config churn |\n|---|---|---|---|---|---|---|---|---|---|\n")
        for r in keep:
            fh.write(f"| {r['repo']} | {r['stars']} | {r['py_files']} | {r['contracts']} | {r['types']} | {r['ignore_imports']} | {r['first_contract_date']} | {r['commits_before']} | {r['commits_after']} | {r['config_churn_commits']} |\n")
    print(f"{len(keep)} usable candidates -> {a.work}/contracts.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
