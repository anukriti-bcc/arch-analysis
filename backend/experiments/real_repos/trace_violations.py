"""Trace violations found by evaluate_repo.py through Git history: when was each violating
import introduced, and when (if ever) was it removed?

  python -m experiments.real_repos.trace_violations --repo-src ../datasets/real/sqlfluff/src \
      --evaluation ../results/real/sqlfluff/evaluation.json --refs early_4 pre_adoption
"""
import argparse
import json
import os

from analysis.evolution.git_evolution import GitEvolutionAnalyzer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-src", required=True, help="the scan root inside the clone (e.g. <repo>/src)")
    ap.add_argument("--evaluation", required=True)
    ap.add_argument("--refs", nargs="+", required=True, help="evaluation labels whose untolerated violations to trace")
    a = ap.parse_args()
    d = json.load(open(a.evaluation))
    an = GitEvolutionAnalyzer(max_commits=1000, anchored_imports=True)  # must match the scanner's mode
    seen, out = set(), []
    for label in a.refs:
        r = next(x for x in d["refs"] if x["label"] == label)
        for e in r.get("untolerated_edges", []):
            k = (e["source"], e["target"])
            if k in seen:
                continue
            seen.add(k)
            ev = an.analyze_dependency(a.repo_src, *k)
            tl = [{"change": x["change"], "date": x["date"][:10], "sha": x["sha"][:8], "subject": x.get("subject") or x.get("message", "")[:80]}
                  for x in ev.get("timeline", [])]
            out.append({"edge": list(k), "first_seen_in": label, "present_at_head": ev.get("present_at_head"), "timeline": tl,
                        "history_truncated": ev.get("history_truncated"), "rename_history_detected": ev.get("rename_history_detected")})
            print(f"{k[0]} -> {k[1]}")
            for x in tl:
                print("   ", x["change"], x["date"], x["sha"], x["subject"])
    with open(os.path.join(os.path.dirname(a.evaluation), "evolution_trace.json"), "w") as fh:
        json.dump(out, fh, indent=2)


if __name__ == "__main__":
    main()
