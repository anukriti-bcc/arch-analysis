"""False-permission probe: does the model invent a permission from a real ADR that has nothing to do with dependencies?

Why this exists. In the pipeline a flagged dependency is a violation by default; an ADR can only change that by convincing the
extractor that it PERMITS the dependency. The dangerous failure is therefore the model reading an unrelated ADR as a permission,
which hides a real violation (this happened once in the 7-case study, C05). The benchmark cannot show it because its ADRs are short
and always relevant. This probe asks, on real ADR text that the team verified does NOT govern dependencies (Q1 = "no"), how often
that happens. Every case's correct answer is "violation" and every ADR is unrelated by construction, so ANY "justified" is an error.

Design (fixed before any model run; see docs/FALSE_PERMISSION_PLAN.md, which also holds the thresholds):

  population  the team-verified Q1 = "no" ADRs of the 60-ADR sample. Primary stratum = ACTIVE ADRs that have text. Rejected or
              superseded ADRs form a control stratum (the pipeline never sends them to the model: policy rule I2). Empty files are
              excluded and listed.
  pairing     each ADR gets one flagged dependency from a fixed list of six type pairs, rotated after a seeded shuffle so that no
              pair dominates. The dependency is unrelated to the ADR by construction.
  model path  the UNCHANGED M7 extraction (prompt x4, `LLMExtractAnalyzer`) with the ADR forced in. Forcing is the stress test:
              it measures the model's reading given selection. The "Selected because" line shows the matcher's real reasons when
              the matcher would have selected the ADR, and nothing otherwise.
  second view the same extraction after the stance-attribution check the product applies by default (no extra call).
  routing     M8's policy applied the way the product would: only ADRs the relevance matcher selects reach the policy. The answer
              for a routed-to-model case is the forced-in answer already on record (same bundle, same prompt), so the routing half
              needs no model. A code reader that says "permits" without a model (direct_code) is a false permission too.

Outcome classes for one extraction (primary metric = share of `dangerous`):
  dangerous    decision = permits and covers = yes        the verdict can flip to "justified"
  misleading   attributed in some other way (prohibits, or permits with unclear scope)    verdict stays "violation", explanation cites an irrelevant ADR
  correct      does_not_address, or covers = no
  failure      no usable reply (never a verdict; the structural verdict stands)

Run:
  python -m experiments.real_adrs.false_permission build        # writes the case file (no network, no model)
  python -m experiments.real_adrs.false_permission freeze       # writes the SHA-256 freeze record
  python -m experiments.real_adrs.false_permission run          # verifies the freeze, fetches ADRs at pinned commits, 44+5 model calls
  python -m experiments.real_adrs.false_permission score --results ../results/real_adrs_false_permission/results.csv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
from typing import Callable, Optional

import pandas as pd

from analysis.evidence.aggregator import EvidenceBundle
from analysis.intent.adr import INACTIVE_STATUSES, ADRMatch, find_relevant_adrs, parse_adr
from analysis.policy.gated import ESCALATE, ReadabilityGatedPolicy
from analysis.semantic.attribution import check_attribution
from analysis.semantic.extract import LLMExtractAnalyzer, resolve_extraction
from experiments.real_adrs import case_study

SEED = 20261123
Q1 = "Q1_about_dependencies (yes/no/partly)"
PRIMARY, INACTIVE_CONTROL, EXCLUDED_EMPTY = "primary", "inactive_control", "excluded_empty"

# Interpretation bands for the PRIMARY metric (raw M7 `dangerous` count in the primary stratum). Fixed before any run.
LOW_MAX, MODERATE_MAX = 2, 4          # 0-2 LOW, 3-4 MODERATE, 5+ HIGH

DEFAULT_SHEET = "../results/real_adrs/annotation_sheet_verified.csv"
DEFAULT_MANIFEST = "../datasets/real_adrs/manifest.json"
DEFAULT_CASES = "../datasets/real_adrs_false_permission/cases.csv"
DEFAULT_FREEZE = "../docs/frozen_false_permission_sha256.json"
DEFAULT_OUT = "../results/real_adrs_false_permission"
DEFAULT_CORPUS = "../datasets/real_adrs/corpus"

# Six flagged dependencies, none related to any particular ADR. Fixed list; the order is the rotation order.
PAIRS = [
    dict(pair_id="P1", source_type="controller", target_type="repository",
         source_path="src/app/controllers/order_controller.py", target_path="src/app/repositories/order_repository.py",
         import_reference="app.repositories.order_repository",
         code_snippet="from app.repositories.order_repository import OrderRepository",
         rule_description="Controllers must not import repositories directly; they must go through the service layer."),
    dict(pair_id="P2", source_type="service", target_type="database",
         source_path="src/app/services/billing_service.py", target_path="src/app/database/connection.py",
         import_reference="app.database.connection",
         code_snippet="from app.database.connection import get_connection",
         rule_description="Services must not import the database connection module directly; they must go through a repository."),
    dict(pair_id="P3", source_type="service", target_type="database_driver",
         source_path="src/app/services/report_service.py", target_path="psycopg2",
         import_reference="psycopg2", code_snippet="import psycopg2",
         rule_description="Services must not import database driver libraries directly."),
    dict(pair_id="P4", source_type="ui", target_type="database",
         source_path="src/app/ui/dashboard_view.py", target_path="src/app/database/session.py",
         import_reference="app.database.session",
         code_snippet="from app.database.session import Session",
         rule_description="UI modules must not import the database layer."),
    dict(pair_id="P5", source_type="domain", target_type="infrastructure",
         source_path="src/app/domain/order.py", target_path="src/app/infrastructure/http_client.py",
         import_reference="app.infrastructure.http_client",
         code_snippet="from app.infrastructure.http_client import HttpClient",
         rule_description="The domain layer must not depend on infrastructure."),
    dict(pair_id="P6", source_type="core", target_type="third_party_http",
         source_path="src/app/core/scheduler.py", target_path="requests",
         import_reference="requests", code_snippet="import requests",
         rule_description="Core modules must not import HTTP client libraries directly."),
]

CASE_COLUMNS = ["case_id", "sheet_id", "stratum", "repo", "commit", "adr_path", "adr_sha256", "adr_bytes", "sheet_status",
                "pair_id", "source_path", "source_type", "target_path", "target_type", "import_reference", "code_snippet",
                "rule_description", "expected"]

# Files whose content determines the experiment. The freeze record holds their SHA-256 (paths relative to backend/).
FROZEN_FILES = [
    "analysis/semantic/extract.py", "analysis/semantic/prompts.py", "analysis/semantic/attribution.py", "analysis/semantic/llm_client.py",
    "analysis/policy/gated.py", "analysis/intent/readability.py", "analysis/intent/reader.py", "analysis/intent/adr.py",
    "analysis/evidence/aggregator.py", "experiments/real_adrs/case_study.py", "experiments/real_adrs/false_permission.py",
    DEFAULT_CASES,
]


# ------------------------------------------------------------------ statistics

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion (95% by default). (0, 0) when n = 0."""
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": int(k), "n": int(n), "rate": (k / n) if n else 0.0, "ci_low": lo, "ci_high": hi}


# ------------------------------------------------------------------ case construction

def build_cases(sheet_csv: str = DEFAULT_SHEET, manifest_json: str = DEFAULT_MANIFEST, seed: int = SEED) -> pd.DataFrame:
    """The case table. Deterministic for a given sheet, manifest and seed. Holds no ADR text, only pointers and hashes."""
    sheet = pd.read_csv(sheet_csv, dtype=str).fillna("")
    with open(manifest_json, encoding="utf-8") as f:
        manifest = json.load(f)
    files = {fe["url"]: (r["repo"], r["commit"], fe) for r in manifest["repos"] for fe in r["files"]}

    chosen = []
    for rec in sheet.to_dict("records"):
        if rec[Q1].strip().lower() != "no":
            continue
        if rec["url"] not in files:
            raise ValueError(f"{rec['id']}: url not in the manifest, cannot pin it to a commit and hash")
        repo, commit, fe = files[rec["url"]]
        status = rec["status"].strip().lower()
        if fe["bytes"] == 0:
            stratum = EXCLUDED_EMPTY
        elif status in INACTIVE_STATUSES:
            stratum = INACTIVE_CONTROL
        else:
            stratum = PRIMARY
        chosen.append(dict(case_id="FP_" + rec["id"], sheet_id=rec["id"], stratum=stratum, repo=repo, commit=commit, adr_path=fe["path"],
                           adr_sha256=fe["sha256"], adr_bytes=int(fe["bytes"]), sheet_status=status))
    chosen.sort(key=lambda c: c["sheet_id"])

    # Rotation: seeded shuffle within each runnable stratum, primary first, one continuing counter, so pairs are balanced inside the primary stratum.
    rng = random.Random(seed)
    order = []
    for stratum in (PRIMARY, INACTIVE_CONTROL):
        group = [c for c in chosen if c["stratum"] == stratum]
        rng.shuffle(group)
        order += group
    pair_of = {c["case_id"]: PAIRS[i % len(PAIRS)] for i, c in enumerate(order)}

    rows = []
    for c in chosen:
        pair = pair_of.get(c["case_id"])
        extra = {k: pair[k] for k in ("pair_id", "source_path", "source_type", "target_path", "target_type", "import_reference", "code_snippet", "rule_description")} if pair else {k: "" for k in ("pair_id", "source_path", "source_type", "target_path", "target_type", "import_reference", "code_snippet", "rule_description")}
        rows.append({**c, **extra, "expected": "violation" if pair else ""})
    return pd.DataFrame(rows, columns=CASE_COLUMNS)


# ------------------------------------------------------------------ one case

def _bundle(row: dict, matches: list[ADRMatch]) -> EvidenceBundle:
    return EvidenceBundle(
        finding_key=row["case_id"], finding_id=row["case_id"], rule_id=None, rule_name="false-permission probe rule", rule_relation="forbidden",
        rule_description=row["rule_description"], source_path=row["source_path"], target_path=row["target_path"], source_type=row["source_type"],
        target_type=row["target_type"], line=1, import_reference=row["import_reference"], code_snippet=row["code_snippet"], snapshot_date=None,
        adrs=list(matches), evolution=None)


def classify(x: Optional[dict]) -> str:
    """dangerous | misleading | correct | failure, for one parsed extraction (None = no usable reply)."""
    if x is None:
        return "failure"
    if x["decision"] == "permits" and x["covers_this_dependency"] == "yes":
        return "dangerous"
    if x["decision"] == "does_not_address" or x["covers_this_dependency"] == "no":
        return "correct"
    return "misleading"


def pipeline_verdict(route: str, route_verdict: str, attr_outcome: str) -> str:
    """The verdict the product would give: direct routes carry their own, an escalated finding takes the model path (with attribution)."""
    if route == ESCALATE:
        return "justified" if attr_outcome == "justified" else "violation"
    return route_verdict


def run_case(row: dict, client, corpus: str | None = None, loader: Callable | None = None, policy: ReadabilityGatedPolicy | None = None) -> dict:
    loader = loader or case_study.load_adr_text
    policy = policy or ReadabilityGatedPolicy()
    adr = parse_adr(row["adr_path"], loader(row, corpus))
    out: dict = {"case_id": row["case_id"], "stratum": row["stratum"], "pair_id": row["pair_id"], "repo": row["repo"], "adr": os.path.basename(row["adr_path"]),
                 "adr_status": adr.status, "adr_active": adr.is_active, "sheet_status": row["sheet_status"]}

    # routing as the product would: only matcher-selected ADRs reach the policy
    matches = find_relevant_adrs([adr], rule_id=None, source_path=row["source_path"], target_path=row["target_path"],
                                 source_type=row["source_type"], target_type=row["target_type"])
    d = policy.decide(_bundle(row, matches))
    out.update(matcher_selected=bool(matches), matcher_reasons=",".join(matches[0].reasons) if matches else "", route=d.route,
               route_failed_gates=",".join(d.failed_gates), route_reasons=" | ".join(d.reasons)[:300],
               route_verdict="" if d.escalate else ("violation" if d.predicted_violation else "justified"))

    # model path: the ADR is forced in; the "Selected because" line shows the matcher's real reasons, or nothing
    forced = [ADRMatch(adr, tuple(matches[0].reasons) if matches else ())]
    res = LLMExtractAnalyzer(client).extract(_bundle(row, forced))
    x = res["parsed"]
    out.update(parsed_ok=res["parsed_ok"], error=res["error"] or "", tokens_in=res["tokens_used"]["input"], tokens_out=res["tokens_used"]["output"],
               latency_s=res["latency_s"], cached=res["cached"], model=res["model"], raw_reply=(res.get("raw_text") or "")[:400])
    if x is None:
        out.update(decision="", covers="", limit="", explanation="", adr_id="", raw_class="failure", raw_outcome="unresolved",
                   attr_decision="", attr_note="", attr_class="failure", attr_outcome="unresolved")
    else:
        xa = check_attribution(x, forced, row["source_path"], row["target_path"])
        out.update(decision=x["decision"], covers=x["covers_this_dependency"], limit=x["limit"], explanation=x["explanation"], adr_id=x["adr_id"] or "",
                   raw_class=classify(x), raw_outcome=resolve_extraction(x, None).outcome,
                   attr_decision=xa["decision"], attr_note=xa["attribution"], attr_class=classify(xa), attr_outcome=resolve_extraction(xa, None).outcome)
    out["pipeline_verdict"] = pipeline_verdict(out["route"], out["route_verdict"], out["attr_outcome"])
    out["pipeline_false_justified"] = out["pipeline_verdict"] == "justified"
    return out


# ------------------------------------------------------------------ scoring

def band(dangerous: int) -> str:
    return "LOW" if dangerous <= LOW_MAX else ("MODERATE" if dangerous <= MODERATE_MAX else "HIGH")


def _bool(s) -> pd.Series:
    return s.astype(str).str.lower().isin(("true", "1", "yes"))


def score(results: pd.DataFrame, adjudication: pd.DataFrame | None = None, n_excluded_empty: int = 0) -> dict:
    """All pre-registered quantities from the per-case rows. Pure function of its input."""
    df = results.copy()
    df["matcher_selected"] = _bool(df["matcher_selected"])
    df["pipeline_false_justified"] = _bool(df["pipeline_false_justified"])
    prim = df[df.stratum == PRIMARY]
    ctrl = df[df.stratum == INACTIVE_CONTROL]
    n = len(prim)
    raw, attr = prim.raw_class.value_counts(), prim.attr_class.value_counts()
    dang = int(raw.get("dangerous", 0))

    def strat(col):
        return {str(k): {"n": int(len(g)), "dangerous": int((g.raw_class == "dangerous").sum())} for k, g in prim.groupby(col)}

    routes = prim.route.value_counts()
    summary = {
        "n_primary": n, "n_inactive_control": len(ctrl), "n_excluded_empty": int(n_excluded_empty),
        "model_raw": {"dangerous": rate(dang, n), "misleading": rate(int(raw.get("misleading", 0)), n),
                      "any_false_attribution": rate(dang + int(raw.get("misleading", 0)), n), "correct": int(raw.get("correct", 0)),
                      "failure": int(raw.get("failure", 0)), "verdict_flipped_to_justified": rate(int((prim.raw_outcome == "justified").sum()), n)},
        "model_with_attribution": {"dangerous": rate(int(attr.get("dangerous", 0)), n),
                                   "rejected_by_check": int(prim.attr_note.astype(str).str.startswith("rejected").sum()),
                                   "verdict_flipped_to_justified": rate(int((prim.attr_outcome == "justified").sum()), n)},
        "routing": {"selected_by_matcher": rate(int(prim.matcher_selected.sum()), n),
                    "direct_structural": int(routes.get("direct_structural", 0)), "direct_code": int(routes.get("direct_code", 0)),
                    "escalate": int(routes.get("escalate", 0))},
        "pipeline": {"false_justified": rate(int(prim.pipeline_false_justified.sum()), n),
                     "via_code_reader": int(((prim.route == "direct_code") & prim.pipeline_false_justified).sum()),
                     "via_model": int(((prim.route == ESCALATE) & prim.pipeline_false_justified).sum())},
        "strata": {"matcher_selected": strat("matcher_selected"), "pair": strat("pair_id"), "repo": strat("repo"), "sheet_status": strat("sheet_status")},
        "inactive_control": {"n": len(ctrl), "dangerous": int((ctrl.raw_class == "dangerous").sum()), "misleading": int((ctrl.raw_class == "misleading").sum()),
                             "failure": int((ctrl.raw_class == "failure").sum())},
        "band": band(dang), "thresholds": {"LOW": f"0-{LOW_MAX}", "MODERATE": f"{LOW_MAX + 1}-{MODERATE_MAX}", "HIGH": f">={MODERATE_MAX + 1}"},
    }
    if adjudication is not None and len(adjudication):
        adj = adjudication.set_index("case_id")["team_judgement"].astype(str).str.strip().str.lower()
        flagged = prim[prim.raw_class == "dangerous"]
        defensible = int(sum(adj.get(c, "") == "defensible" for c in flagged.case_id))
        summary["adjudicated"] = {"dangerous_before": dang, "judged_defensible": defensible, "dangerous_after": rate(dang - defensible, n),
                                  "unjudged": int(sum(adj.get(c, "") not in ("defensible", "false_permission") for c in flagged.case_id))}
    return summary


def adjudication_template(results: pd.DataFrame) -> pd.DataFrame:
    """One row per dangerous or misleading extraction, for the team to judge BEFORE reading the verdict band.
    `team_judgement`: false_permission (the ADR really has nothing to do with this dependency) or defensible (a reasonable reader could take it as relevant)."""
    r = results[(results.stratum == PRIMARY) & results.raw_class.isin(["dangerous", "misleading"])]
    return r[["case_id", "adr", "pair_id", "raw_class", "decision", "covers", "explanation"]].assign(team_judgement="", notes="")


def render_markdown(s: dict) -> str:
    def pct(r):
        return f"{r['k']}/{r['n']} ({100 * r['rate']:.1f}%, 95% CI {100 * r['ci_low']:.1f} to {100 * r['ci_high']:.1f}%)"
    m, a, rt, p = s["model_raw"], s["model_with_attribution"], s["routing"], s["pipeline"]
    lines = [
        "# False-permission probe: results", "",
        f"Primary stratum: {s['n_primary']} active real ADRs verified as not governing dependencies; control stratum (inactive): {s['n_inactive_control']}; excluded (empty file): {s['n_excluded_empty']}.", "",
        f"**Band (pre-registered, raw model, unadjudicated): {s['band']}** (thresholds {s['thresholds']}).", "",
        "| Quantity | Result |", "|---|---|",
        f"| Dangerous false permission (permits and covers yes), raw M7 | {pct(m['dangerous'])} |",
        f"| Misleading (attributed another way) | {pct(m['misleading'])} |",
        f"| Any false attribution | {pct(m['any_false_attribution'])} |",
        f"| Correct / no usable reply | {m['correct']} / {m['failure']} |",
        f"| Verdict actually flipped to justified (raw) | {pct(m['verdict_flipped_to_justified'])} |",
        f"| Dangerous after the attribution check (product setting) | {pct(a['dangerous'])}; check rejected {a['rejected_by_check']} readings |",
        f"| Selected by the relevance matcher | {pct(rt['selected_by_matcher'])} |",
        f"| M8 routes: structural / code reader / model | {rt['direct_structural']} / {rt['direct_code']} / {rt['escalate']} |",
        f"| **Pipeline false-justified (M8 routing + attribution)** | {pct(p['false_justified'])}; via code reader {p['via_code_reader']}, via model {p['via_model']} |",
        f"| Control stratum (inactive ADRs): dangerous / misleading / failure | {s['inactive_control']['dangerous']} / {s['inactive_control']['misleading']} / {s['inactive_control']['failure']} of {s['inactive_control']['n']} |",
    ]
    if "adjudicated" in s:
        j = s["adjudicated"]
        lines.append(f"| After team adjudication: dangerous | {pct(j['dangerous_after'])}; {j['judged_defensible']} judged defensible, {j['unjudged']} not yet judged |")
    lines += ["", "Stratified counts (descriptive, small cells): see summary.json.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ freeze

def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def freeze_record(files: list[str] | None = None) -> dict:
    return {p: _sha(p) for p in (files or FROZEN_FILES)}


def verify_freeze(record_path: str = DEFAULT_FREEZE) -> list[str]:
    """Files whose current hash differs from the record (empty list = the experiment is exactly the frozen one)."""
    with open(record_path, encoding="utf-8") as f:
        rec = json.load(f)
    return [p for p, h in rec.items() if not os.path.exists(p) or _sha(p) != h]


# ------------------------------------------------------------------ CLI

def _client():
    from analysis.semantic.llm_client import CachingClient, OpenAICompatibleClient
    base = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
    inner = OpenAICompatibleClient(base_url=base, model=os.environ.get("LLM_MODEL", "arch-judge"), api_key=os.environ.get("LLM_API_KEY", "ollama"))
    cache = os.environ.get("LLM_CACHE_PATH")
    return CachingClient(inner, cache) if cache else inner


def _write_outputs(df: pd.DataFrame, out: str, adjudication_path: str | None = None, n_excluded_empty: int = 0) -> dict:
    adj = pd.read_csv(adjudication_path, dtype=str).fillna("") if adjudication_path else None
    s = score(df, adj, n_excluded_empty)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(s))
    adjudication_template(df).to_csv(os.path.join(out, "adjudication_template.csv"), index=False)
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "freeze", "run", "score"])
    ap.add_argument("--sheet", default=DEFAULT_SHEET)
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--freeze", default=DEFAULT_FREEZE)
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--results", default=None, help="score: results.csv of an earlier run")
    ap.add_argument("--adjudication", default=None, help="score: the team's filled adjudication CSV")
    args = ap.parse_args(argv)

    if args.command == "build":
        df = build_cases(args.sheet, args.manifest)
        os.makedirs(os.path.dirname(args.cases), exist_ok=True)
        df.to_csv(args.cases, index=False, lineterminator="\n")
        print(df.stratum.value_counts().to_string())
        print(df[df.stratum == PRIMARY].pair_id.value_counts().sort_index().to_string())
        return 0
    if args.command == "freeze":
        rec = freeze_record()
        with open(args.freeze, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)
        print(f"froze {len(rec)} files -> {args.freeze}")
        return 0
    if args.command == "score":
        df = pd.read_csv(args.results, dtype=str).fillna("")
        s = _write_outputs(df, args.out, args.adjudication)
        print(render_markdown(s))
        return 0

    bad = verify_freeze(args.freeze)
    if bad:
        raise SystemExit(f"frozen files differ from the freeze record: {bad}. Refusing to run.")
    print(f"freeze check OK ({len(json.load(open(args.freeze)))} files match)")
    cases = pd.read_csv(args.cases, dtype=str).fillna("")
    runnable = cases[cases.stratum != EXCLUDED_EMPTY]
    client = _client()
    rows = [run_case(r, client, args.corpus) for r in runnable.to_dict("records")]
    os.makedirs(args.out, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(args.out, "results.csv"), index=False)
    s = _write_outputs(df, args.out, None, int((cases.stratum == EXCLUDED_EMPTY).sum()))
    print(render_markdown(s))
    print("Next: the team fills adjudication_template.csv (judge before reading the band), then `score --results ... --adjudication ...`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
