"""A small, hand-built case study: M7 and M6 on REAL ADR text.

What this is: ~7 cases, each a real ADR (pinned to a commit and a SHA-256) plus a hand-written flagged dependency and a draft expected
verdict. What it is NOT: a benchmark. Seven cases cannot give a rate; they show what the methods do with real wording, including failures.
The expected verdicts are a DRAFT written by the same person who built the cases; the team must review them (`reviewed_by_team`) and the
cases marked `debatable` are exactly where a reasonable reader could disagree.

For every case the ADR is shown to the model through the unchanged M7 path (`render_extract_prompt` -> model -> grounding -> code computes the
verdict), and the frozen code-only reader M6 is run twice: as the pipeline would (the relevance matcher decides whether the ADR is even
selected, which needs file names real ADRs rarely contain) and "reading only" (the ADR is forced in, so only M6's reading is tested).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import urllib.request

import pandas as pd

from analysis.evidence.aggregator import EvidenceBundle
from analysis.intent.adr import ADRMatch, find_relevant_adrs, parse_adr
from analysis.intent.reader import decide_deterministic
from analysis.semantic.extract import LLMExtractAnalyzer, resolve_extraction

REQUIRED = ["case_id", "repo", "commit", "adr_path", "adr_sha256", "source_path", "source_type", "target_path", "target_type",
            "import_reference", "code_snippet", "rule_description", "expected", "debatable"]


def raw_url(repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"


def load_adr_text(row: dict, corpus: str | None = None) -> str:
    """The ADR text, from a local corpus copy if present, else downloaded at the pinned commit. Always verified against the recorded hash."""
    text = None
    if corpus:
        local = os.path.join(corpus, row["repo"].replace("/", "__"), row["adr_path"].replace("/", "_"))
        if os.path.exists(local):
            text = open(local, "rb").read()
    if text is None:
        with urllib.request.urlopen(raw_url(row["repo"], row["commit"], row["adr_path"]), timeout=40) as r:
            text = r.read()
    digest = hashlib.sha256(text).hexdigest()
    if digest != row["adr_sha256"]:
        raise ValueError(f"{row['case_id']}: ADR text does not match the recorded SHA-256 (got {digest[:12]}, expected {row['adr_sha256'][:12]}); "
                         "the upstream file has changed or the wrong version was fetched")
    return text.decode("utf-8", errors="replace")


def build_bundle(row: dict, adr, reasons: tuple[str, ...]) -> EvidenceBundle:
    return EvidenceBundle(
        finding_key=row["case_id"], finding_id=row["case_id"], rule_id=None, rule_name="case-study rule", rule_relation="forbidden",
        rule_description=row["rule_description"], source_path=row["source_path"], target_path=row["target_path"], source_type=row["source_type"],
        target_type=row["target_type"], line=1, import_reference=row["import_reference"], code_snippet=row["code_snippet"], snapshot_date=None,
        adrs=[ADRMatch(adr, reasons)], evolution=None)


def run_case(row: dict, client, corpus: str | None = None) -> dict:
    text = load_adr_text(row, corpus)
    adr = parse_adr(row["adr_path"], text)
    out = {"case_id": row["case_id"], "adr": os.path.basename(row["adr_path"]), "expected": row["expected"], "debatable": row["debatable"],
           "adr_status": adr.status}
    # M6 as the pipeline would run it: the real relevance matcher decides whether the ADR is selected, and how strongly
    matches = find_relevant_adrs([adr], rule_id=None, source_path=row["source_path"], target_path=row["target_path"],
                                 source_type=row["source_type"], target_type=row["target_type"])
    out["matcher_selected"] = bool(matches)
    out["matcher_reasons"] = ",".join(matches[0].reasons) if matches else ""
    d = decide_deterministic(matches, None)
    out["m6_pipeline"] = "violation" if d.predicted_violation else "justified"
    out["m6_pipeline_note"] = d.reason[:120]
    # M6 reading only: scope forced to strong, so only the reading is tested
    forced = decide_deterministic([ADRMatch(adr, ("file_names",))], None)
    out["m6_reading_only"] = {"justified": "justified", "violation": "violation", "unclear": "unclear"}[forced.outcome]
    out["m6_reading_note"] = forced.reason[:120]
    # M7 exactly as frozen: extraction prompt -> model -> grounding -> code computes
    bundle = build_bundle(row, adr, ("case_study",))
    res = LLMExtractAnalyzer(client).extract(bundle)
    out["m7_parsed_ok"] = res["parsed_ok"]
    if res["parsed"] is None:
        out.update(m7="fallback", m7_decision="", m7_limit="", m7_explanation=(res.get("raw_text") or "")[:200], m7_computed="")
    else:
        x = res["parsed"]
        r = resolve_extraction(x, None)
        out.update(m7={"justified": "justified", "violation": "violation", "unresolved": "fallback"}[r.outcome], m7_decision=x["decision"],
                   m7_limit=x["limit"], m7_explanation=x["explanation"], m7_computed=r.note)
    for k in ("m6_pipeline", "m6_reading_only", "m7"):
        out[f"{k}_correct"] = out[k] == row["expected"]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default="../datasets/real_adrs_case_study/cases.csv")
    ap.add_argument("--corpus", default="../datasets/real_adrs/corpus")
    ap.add_argument("--out", default="../results/real_adrs_case_study")
    ap.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1"))
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", "arch-judge"))
    args = ap.parse_args(argv)
    from analysis.semantic.llm_client import OpenAICompatibleClient
    client = OpenAICompatibleClient(base_url=args.base_url, model=args.model, api_key=os.environ.get("LLM_API_KEY", "ollama"))
    cases = pd.read_csv(args.cases, dtype=str).fillna("")
    missing = [c for c in REQUIRED if c not in cases.columns]
    if missing:
        raise SystemExit(f"cases file lacks columns: {missing}")
    rows = [run_case(r, client, args.corpus) for r in cases.to_dict("records")]
    os.makedirs(args.out, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(args.out, "results.csv"), index=False)
    show = df[["case_id", "expected", "debatable", "m6_pipeline", "m6_reading_only", "m7", "m7_decision", "m7_limit"]]
    print(show.to_string(index=False))
    print("\ncorrect (of %d): M6 as pipeline %d | M6 reading only %d | M7 %d" % (len(df), df.m6_pipeline_correct.sum(), df.m6_reading_only_correct.sum(), df.m7_correct.sum()))
    print("\nM7's explanations:")
    for _, r in df.iterrows():
        print(f"  {r.case_id} [{r.m7}] {r.m7_explanation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
