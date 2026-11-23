"""Profile a corpus of REAL ADRs with the project's own code, to answer three questions the synthetic benchmarks cannot:

  Q1  How many real ADRs say anything about which parts of a system may depend on each other?
      (Architecture conformance checking against ADRs only applies to those.)
  Q2  Can the code-only reader (M6) read them? (stance cues, dates, exception language)
  Q3  Does the ADR relevance matcher over-select on real text?

Q1 is measured here with a keyword PROXY (`rule_tier`). A proxy is not a label: docs/REAL_ADRS.md reports its agreement with a
hand-labelled sample, and `annotation_sheet.csv` lets the team label independently.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
from collections import Counter

import pandas as pd

from analysis.intent.adr import find_relevant_adrs, parse_adr
from analysis.intent.reader import decision_section, find_dates, read_adr, sentences
from experiments.real_adrs.fetch_corpus import PERMISSIVE, TOOLISH

STRUCT = re.compile(r"\b(layers?|modules?|packages?|components?|services?|microservices?|controllers?|repositor(?:y|ies)|domains?|adapters?|ports?|"
                    r"boundar(?:y|ies)|subsystems?|librar(?:y|ies)|bounded contexts?|apis?|databases?|data ?stores?|front-?ends?|back-?ends?|"
                    r"clients?|servers?|plugins?|infrastructure|presentation|persistence)\b", re.I)
CORE_DEP = re.compile(r"\b(depend(?:s|ed|ing|ency|encies)?|import(?:s|ed|ing)?|call(?:s|ed|ing)?|access(?:es|ed|ing)?|communicat\w+|"
                      r"reference[sd]?|invok\w+|talk(?:s)? to|couple[sd]?|coupling|decoupl\w+)\b", re.I)
WEAK_DEP = re.compile(r"\b(via|through|directly|isolat\w+|encapsulat\w+|go(?:es)? through)\b", re.I)
RESTRICT = re.compile(r"\b(must not|shall not|should not|may not|cannot|can not|never|only|not allowed|not be allowed|forbid\w*|prohibit\w*|"
                      r"restrict\w*|disallow\w*|allowed to|permitted|not permitted)\b", re.I)
EXCEPTION = re.compile(r"(grandfather|exception|temporar|until|for now|legacy|deprecat|transition|migrat|workaround|hotfix|interim)", re.I)
RELATIVE_LIMIT = re.compile(r"(within \d+ (?:days?|weeks?|months?)|by the end of (?:Q[1-4]|the (?:quarter|year|month|sprint))|"
                            r"next (?:release|sprint|quarter)|until (?:the )?(?:migration|release|v\d|version|we )|before (?:the )?(?:release|launch))", re.I)

# Component-type pairs of the kind architecture rules are written with (used only to probe the matcher).
TYPE_PAIRS = [("controller", "repository"), ("service", "database"), ("controller", "database"), ("ui", "database"),
              ("domain", "infrastructure"), ("api", "database"), ("handler", "repository"), ("view", "model")]


_HEAD = re.compile(r"^(#{1,6})\s*(.*?)\s*#*\s*$")
# in priority order: the MADR 'Decision Outcome' must win over 'Decision Drivers', which merely lists forces
_STOP = re.compile(r"(positive |negative )?consequences|pros and cons.*|more information|links?|confirmation|references?|notes?|status")
_DECISION_TITLES = [r"decision outcome", r"decisions?", r"the decision", r"outcome", r"resolution", r"proposal", r"chosen option"]


def decision_text(text: str) -> tuple[str, bool]:
    """Decision section for real ADRs. The project's reader (analysis/intent/reader.py, frozen with M6) takes the FIRST heading that
    begins with 'Decision', which on MADR documents is 'Decision Drivers' (a list of forces) instead of 'Decision Outcome'. This version
    prefers the outcome, keeps sub-headings (Dapr: '## Decisions' / '### D1'), and stops at the next heading of the same or higher level."""
    body = text
    if body.startswith("---"):
        parts = body.split("\n")
        for i in range(1, len(parts)):
            if parts[i].strip() == "---":
                body = "\n".join(parts[i + 1:]); break
    lines = body.split("\n")
    heads = [(i, len(m.group(1)), re.sub(r"^\d+[.):]\s*", "", m.group(2)).lower()) for i, l in enumerate(lines) if (m := _HEAD.match(l))]
    for pattern in _DECISION_TITLES:
        for i, level, title in heads:
            if re.fullmatch(pattern, title.rstrip(":")):
                end = next((j for j, lv, tt in heads if j > i and (lv <= level or _STOP.fullmatch(tt.rstrip(":")))), len(lines))
                section = "\n".join(lines[i + 1:end]).strip()
                if section:
                    return section, True
    m = re.search(r"\*\*decision:?\*\*:?\s*(.+)", body, re.I)  # inline '**Decision:** ...' (Ministry of Justice style)
    if m:
        return m.group(1).strip(), True
    return body, False


def rule_tier(text: str) -> int:
    """1 = a sentence names system parts, a dependency verb and a restriction/permission cue; 2 = parts and a dependency idea without
    a restriction cue (or a restriction with a weak dependency word); 3 = neither. Computed on the Decision section when there is one."""
    section, _ = decision_text(text)
    best = 3
    for s in sentences(section):
        has_struct, core, weak, restrict = bool(STRUCT.search(s)), bool(CORE_DEP.search(s)), bool(WEAK_DEP.search(s)), bool(RESTRICT.search(s))
        if has_struct and core and restrict:
            return 1
        if has_struct and (core or (restrict and weak)):
            best = 2
    return best


def format_kind(text: str) -> str:
    low = text.lower()
    if re.search(r"considered options|decision outcome|decision drivers", low):
        return "madr_like"
    if re.search(r"^\s*#+\s*context", low, re.M) and re.search(r"^\s*#+\s*decision", low, re.M):
        return "nygard_like"
    return "other"


def profile_one(repo: dict, f: dict, text: str) -> dict:
    adr = parse_adr(f["path"], text)
    section, found = decision_text(text)
    reading = read_adr(adr, None)  # M6 exactly as frozen (including its Decision-Drivers defect), so its real-text behaviour is reported as it is
    return {
        "repo": repo["repo"], "kind": repo["kind"], "stars": repo["stars"], "created": repo["created"], "file": f["file"], "path": f["path"], "url": f["url"],
        "words": len(text.split()), "format": format_kind(text), "status": adr.status, "active": adr.is_active, "has_date": adr.date is not None,
        "decision_section": found, "decision_words": len(section.split()), "rule_tier": rule_tier(text),
        "m6_stance": reading.stance, "dates_in_decision": len(find_dates(section)), "exception_language": bool(EXCEPTION.search(section)),
        "relative_limit": bool(RELATIVE_LIMIT.search(section)),
    }


def load(root: str, kinds: tuple[str, ...]) -> tuple[list[dict], list[tuple[dict, dict, str]]]:
    manifest = json.load(open(os.path.join(root, "manifest.json")))
    items = []
    for repo in manifest["repos"]:
        repo.setdefault("kind", "tool" if TOOLISH.search(f"{repo['repo']} {repo.get('description') or ''}") else "project")  # older manifests
        repo.setdefault("created", "")
        repo.setdefault("license_ok", repo.get("license") in PERMISSIVE)
        if repo["kind"] not in kinds:
            continue
        for f in repo["files"]:
            path = os.path.join(root, "corpus", f["file"])
            if os.path.exists(path):
                items.append((repo, f, open(path, encoding="utf-8", errors="replace").read()))
    return manifest["repos"], items


def is_boilerplate(text: str) -> bool:
    return bool(re.search(r"record architecture decisions", text[:400], re.I))


def _tolerant(adr_text: str, src_t: str, tgt_t: str) -> bool:
    """Sensitivity variant, NOT the project's matcher: same type-words rule but accepting plurals ('services', 'databases')."""
    f = lambda t: re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?:e?s)?(?![A-Za-z0-9])", adr_text, re.I)
    return bool(f(src_t) and f(tgt_t))


def matcher_probe(items) -> pd.DataFrame:
    """How often does the type-words rule of the project's relevance matcher (analysis/intent/adr.py, unchanged) select a REAL ADR for a
    typical flagged dependency? `matched_by_type_words` is the matcher as it is; `matched_plural_tolerant` shows what accepting plurals
    would change (real ADRs say 'services' and 'databases'; the matcher requires the exact word)."""
    by_repo: dict[str, list] = {}
    for repo, f, text in items:
        if not is_boilerplate(text):
            by_repo.setdefault(repo["repo"], []).append(parse_adr(f["path"], text))
    rows = []
    for src_t, tgt_t in TYPE_PAIRS:
        hit = tol = tot = 0
        for repo, adrs in by_repo.items():
            m = find_relevant_adrs(adrs, rule_id=None, source_path=f"app/{src_t}/zzorders.py", target_path=f"app/{tgt_t}/zzstore.py",
                                   source_type=src_t, target_type=tgt_t)
            hit += len(m); tot += len(adrs)
            tol += sum(_tolerant(a.text, src_t, tgt_t) for a in adrs)
        rows.append({"source_type": src_t, "target_type": tgt_t, "adrs": tot, "matched_by_type_words": hit, "share": hit / tot if tot else 0,
                     "matched_plural_tolerant": tol, "share_plural_tolerant": tol / tot if tot else 0})
    return pd.DataFrame(rows)


def annotation_sheet(items, n: int, seed: int, path: str) -> pd.DataFrame:
    pool = [(r, f, t) for r, f, t in items if not is_boilerplate(t) and r.get("license_ok")]  # excerpts only from permissively licensed repositories
    rng = random.Random(seed)
    pick = rng.sample(pool, min(n, len(pool)))
    rows = []
    for i, (repo, f, text) in enumerate(pick, 1):
        section, found = decision_text(text)
        adr = parse_adr(f["path"], text)
        rows.append({"id": f"R{i:03d}", "repo": repo["repo"], "url": f["url"], "status": adr.status,
                     "decision_excerpt": " ".join(section.split())[:900] if found else "(no decision section found) " + " ".join(text.split())[:700],
                     # ---- to be filled by a human (see docs/REAL_ADRS.md for the exact questions)
                     "Q1_about_dependencies (yes/no/partly)": "", "Q2_exception_or_condition (yes/no)": "",
                     "Q3_wording (templated / plain paraphrase / irregular)": "", "notes": ""})
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    return df


def summarize(df: pd.DataFrame) -> dict:
    d = df[~df["boilerplate"]]
    n = len(d)
    pct = lambda x: round(100 * float(x), 1)
    return {
        "adrs": n, "repos": int(d["repo"].nunique()), "boilerplate_excluded": int(df["boilerplate"].sum()),
        "format": {k: pct(v / n) for k, v in Counter(d["format"]).items()},
        "has_decision_section_pct": pct(d["decision_section"].mean()), "has_date_pct": pct(d["has_date"].mean()), "active_pct": pct(d["active"].mean()),
        "median_words": int(d["words"].median()),
        "rule_tier_pct": {f"tier{t}": pct((d["rule_tier"] == t).mean()) for t in (1, 2, 3)},
        "m6_stance_pct": {k: pct(v / n) for k, v in Counter(d["m6_stance"]).items()},
        "m6_not_unclear_among_tier1_pct": pct((d[d["rule_tier"] == 1]["m6_stance"] != "unclear").mean()) if (d["rule_tier"] == 1).any() else None,
        "dates_in_decision_pct": pct((d["dates_in_decision"] > 0).mean()), "exception_language_pct": pct(d["exception_language"].mean()),
        "relative_limit_pct": pct(d["relative_limit"].mean()),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="../datasets/real_adrs")
    ap.add_argument("--out", default="../results/real_adrs")
    ap.add_argument("--kinds", default="project", help="comma list: project,tool")
    ap.add_argument("--sheet", type=int, default=60)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    repos, items = load(args.corpus, tuple(args.kinds.split(",")))
    rows = []
    for repo, f, text in items:
        r = profile_one(repo, f, text); r["boilerplate"] = is_boilerplate(text); rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(args.out, "profile.csv"), index=False)
    summary = {"corpus": args.corpus, "kinds": args.kinds, **summarize(df)}
    probe = matcher_probe(items)
    probe.to_csv(os.path.join(args.out, "matcher_probe.csv"), index=False)
    summary["matcher_probe"] = probe.round(3).to_dict("records")
    annotation_sheet(items, args.sheet, args.seed, os.path.join(args.out, "annotation_sheet.csv"))
    json.dump(summary, open(os.path.join(args.out, "summary.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "matcher_probe"}, indent=1))
    print(probe.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
