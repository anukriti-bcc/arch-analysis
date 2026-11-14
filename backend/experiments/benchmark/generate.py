"""Controlled benchmark generator.

WHY A GENERATED BENCHMARK (and what it can and cannot show)
-----------------------------------------------------------
Evaluating conformance analysis needs ground truth about each dependency:
is it a genuine violation, or justified by documented intent? For real
repositories that label requires expert annotation of many findings, which is
not feasible in the project's timeframe. This generator instead builds many
small repositories with scripted Git histories in which the correct label is
known BY CONSTRUCTION, and in which the evidence needed to reach it is placed
deliberately in one of three places: the code structure, a decision record
(intent), or the history (dates, commit messages).

It therefore supports claims of the form "under controlled conditions, evidence
source X is/isn't needed to reach the right decision, and costs Y LLM calls".
It does NOT support claims about accuracy on real-world repositories; the
scenario mix and the ADR wording are authored by us, which is a threat to
validity the report must state. Mitigations built in: fixed seeds, several
wording variants per scenario, unrelated "noise" decision records, a dev/test
split decided before the policy is evaluated, and per-scenario reporting so a
reader can see exactly where each evidence source matters.

SCENARIOS (label = ground truth for the one targeted dependency)
----------------------------------------------------------------
 A  plain_violation              violation  structure alone suffices
 B  adr_permanent_exception      justified  active ADR permits this exact dependency
 C  adr_grandfathered_before     justified  ADR grandfathers deps introduced <= cutoff;
                                            this one was  -> needs introduction DATE
 D  adr_grandfathered_after      violation  same ADR text; dep introduced AFTER cutoff
 E  adr_reaffirms_prohibition    violation  active ADR names the pair but forbids it
 F  adr_superseded               violation  the permitting ADR is marked superseded
 G  adr_passing_mention          violation  ADR mentions the same layers in passing only
 H  temporary_became_permanent   violation  "temporary" commit; never removed; no ADR
 J  adr_cited_by_commit_only     justified  permitting ADR shares no wording with the code;
                                            only the introducing commit cites its id
 K  adr_scope_mismatch           violation  active ADR permits a DIFFERENT module
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from dataclasses import dataclass
from datetime import date, timedelta

from experiments.benchmark.gitbuilder import GitBuilder

SCENARIOS: dict[str, tuple[str, int]] = {
    "A_plain_violation": ("violation", 10),
    "B_adr_permanent_exception": ("justified", 6),
    "C_adr_grandfathered_before_cutoff": ("justified", 6),
    "D_adr_grandfathered_after_cutoff": ("violation", 6),
    "E_adr_reaffirms_prohibition": ("violation", 6),
    "F_adr_superseded": ("violation", 5),
    "G_adr_passing_mention": ("violation", 5),
    "H_temporary_became_permanent": ("violation", 5),
    "J_adr_cited_by_commit_only": ("justified", 6),
    "K_adr_scope_mismatch": ("violation", 5),
}

ENTITIES = [
    "order", "payment", "invoice", "shipment", "catalog", "inventory", "customer", "ledger",
    "subscription", "notification", "report", "coupon", "review", "wishlist", "refund",
    "warehouse", "booking", "ticket", "profile", "analytics", "quote", "contract", "payroll", "audit",
]
AUTHORS = ["alice", "bob", "carol", "dev-ops"]

RULES_YAML = """architecture:
  name: layered-architecture
component_mapping:
  controllers: {type: controller}
  services: {type: service}
  repositories: {type: repository}
  database: {type: database}
rules:
  - {id: R001, name: controller-service, source: controller, target: service, relation: allowed, description: Controllers may call Services.}
  - {id: R002, name: service-repository, source: service, target: repository, relation: allowed, description: Services may call Repositories.}
  - {id: R003, name: repository-database, source: repository, target: database, relation: allowed, description: Repositories are the sanctioned path to the database.}
  - {id: R004, name: no-service-database, source: service, target: database, relation: forbidden, description: Services must not access the database directly; go through a Repository.}
  - {id: R005, name: no-controller-repository, source: controller, target: repository, relation: forbidden, description: Controllers must not skip the Service layer to call Repositories directly.}
  - {id: R006, name: no-controller-database, source: controller, target: database, relation: forbidden, description: Controllers must never access the database directly.}
"""

REASONS = [
    "reporting queries need a consistent read snapshot",
    "the nightly reconciliation job must read rows in bulk",
    "the extra layer adds unacceptable latency on this hot path",
    "the data-access layer does not yet support streaming reads",
    "bulk exports would otherwise load the full result set into memory",
]
REJECTIONS = [
    "bypassing the layer would make later storage changes far more expensive",
    "the performance concern can be addressed inside the proper layer",
    "an exception here would set a precedent other modules would follow",
]
NEUTRAL_COMMITS = [
    "Add {e} summary lookup", "Support {e} status filter", "Expose {e} totals",
    "Add {e} detail endpoint", "Handle empty {e} results", "Include {e} timestamps in output",
]
TEMP_COMMITS = [
    "TEMP: read the {e} data straight from the db until the layer is ready",
    "Quick workaround for {e} lookups - bypass the layer for now",
    "Hotfix: temporary direct access for {e} export (remove later)",
]
CITING_COMMITS = [
    "Read {e} rows directly from storage (see ADR-{n:03d})",
    "Implement {e} bulk read as agreed in ADR-{n:03d}",
]
FILLER_COMMITS = ["Tidy {e} module", "Add docstring to {e}", "Refactor {e} helper", "Fix typo in {e}", "Update {e} constants"]
NOISE_ADRS = [
    ("Use structured JSON logging", "All log lines are emitted as single-line JSON objects with a timestamp, level and message so they can be searched centrally."),
    ("Version the public API in the URL", "Public endpoints carry a version prefix such as /v1/ so clients can migrate on their own schedule."),
    ("Run continuous integration on every pull request", "Every pull request triggers the full test suite and linting before it can be merged."),
    ("Adopt semantic versioning for releases", "Releases are tagged MAJOR.MINOR.PATCH and the changelog is updated with each tag."),
]


@dataclass
class Pair:
    key: str
    rule_id: str
    src_type: str
    tgt_type: str


PAIRS = {
    "service_database": Pair("service_database", "R004", "service", "database"),
    "controller_repository": Pair("controller_repository", "R005", "controller", "repository"),
    "controller_database": Pair("controller_database", "R006", "controller", "database"),
}


def _pair_files(pair: Pair, e: str) -> dict:
    src = f"app/{pair.src_type}s/{e}_{pair.src_type}.py"
    if pair.tgt_type == "database":
        tgt, tgt_stem = "app/database/connection.py", "connection"
        imp = "from app.database.connection import get_connection"
        tgt_desc = "the database connection module"
        tgt_abs = "the persistence backend"
    else:
        tgt, tgt_stem = f"app/repositories/{e}_repository.py", f"{e}_repository"
        imp = f"from app.repositories.{e}_repository import {e.capitalize()}Repository"
        tgt_desc = f"the {e} repository"
        tgt_abs = f"the {e} data-access code"
    src_desc = f"the {e} {pair.src_type}"
    src_abs = f"the {e} handling code" if pair.src_type == "service" else f"the {e} HTTP entry points"
    return dict(src=src, src_stem=f"{e}_{pair.src_type}", tgt=tgt, tgt_stem=tgt_stem, imp=imp,
                src_desc=src_desc, tgt_desc=tgt_desc, src_abs=src_abs, tgt_abs=tgt_abs)


# ----------------------------------------------------------- ADR rendering


def render_adr(fmt: str, number: int, title: str, status: str, when: date, context: str, decision: str, consequences: str) -> str:
    if fmt == "nygard":
        return (f"# {number}. {title}\n\nDate: {when.isoformat()}\n\n## Status\n\n{status}\n\n"
                f"## Context\n\n{context}\n\n## Decision\n\n{decision}\n\n## Consequences\n\n{consequences}\n")
    if fmt == "madr":
        return (f"# {title}\n\n* Status: {status}\n* Date: {when.isoformat()}\n\n"
                f"## Context and Problem Statement\n\n{context}\n\n## Decision Outcome\n\n{decision}\n\n"
                f"### Consequences\n\n{consequences}\n")
    return (f"---\nid: ADR-{number:03d}\nstatus: {status}\ndate: {when.isoformat()}\n---\n"
            f"# {title}\n\n## Context\n\n{context}\n\n## Decision\n\n{decision}\n\n## Consequences\n\n{consequences}\n")


def _adr_content(scenario: str, rng: random.Random, f: dict, pair: Pair, other: str, cutoff: date | None, number: int):
    """Returns (title, status, context, decision, consequences) for the scenario's
    principal ADR, or None when the scenario has none."""
    reason = rng.choice(REASONS)
    SF, TF, S, T, R = f["src_stem"], f["tgt_stem"], f["src_desc"], f["tgt_desc"], pair.rule_id
    v = rng.randint(0, 1)
    if scenario in ("B_adr_permanent_exception", "F_adr_superseded"):
        status = "Accepted" if scenario.startswith("B") else f"Superseded by ADR-{number + 20:03d}"
        title = f"Allow {SF} to use {TF} directly"
        context = f"The layering rule {R} normally forbids this dependency, but {reason}."
        decision = (f"{S[0].upper() + S[1:]} (`{SF}`) is permitted to access {T} (`{TF}`) directly. "
                    f"This is a deliberate, permanent exception to rule {R}." if v == 0 else
                    f"We accept that `{SF}` will use `{TF}` directly, bypassing rule {R}. "
                    f"The exception is permanent and applies only to this module.")
        return title, status, context, decision, "No other module is covered by this exception."
    if scenario in ("C_adr_grandfathered_before_cutoff", "D_adr_grandfathered_after_cutoff"):
        title = f"Grandfather direct access from {SF} during the layer migration"
        context = f"Rule {R} forbids this access, but {reason}, and the proper layer will not be ready for some time."
        decision = (f"Until the layer migration completes, {S} (`{SF}`) may continue to access {T} (`{TF}`) directly. "
                    f"Dependencies of this kind introduced on or before {cutoff.isoformat()} are grandfathered. "
                    f"Any such dependency introduced after {cutoff.isoformat()} is NOT covered by this decision "
                    f"and must be treated as a violation of {R}.")
        return title, "Accepted", context, decision, "Grandfathered dependencies must be removed when the migration finishes."
    if scenario == "E_adr_reaffirms_prohibition":
        title = f"Reject direct access from {SF} to {TF}"
        context = f"A request was raised to let {S} (`{SF}`) access {T} (`{TF}`) directly, because {reason}."
        decision = (f"We reaffirm that `{SF}` must not use `{TF}` directly (rule {R}). The request was reviewed and rejected: "
                    f"{rng.choice(REJECTIONS)}. All such access must go through the proper layer.")
        return title, "Accepted", context, decision, "The performance concern will be handled inside the proper layer."
    if scenario == "G_adr_passing_mention":
        title = "Cache hot lookups"
        context = "Several read paths are slow under load."
        decision = (f"The {pair.src_type} tier will cache the results of {pair.tgt_type} lookups in memory with a 60 second TTL. "
                    f"Cache invalidation happens on writes.")
        return title, "Accepted", context, decision, "Stale reads of up to 60 seconds are acceptable."
    if scenario == "K_adr_scope_mismatch":
        S2 = f"the {other} {pair.src_type}"
        if pair.tgt_type == "database":
            T2, TF2 = "the database connection module", "connection"
        else:
            T2, TF2 = f"the {other} repository", f"{other}_repository"
        title = f"Allow {other}_{pair.src_type} to use {TF2} directly"
        context = f"{reason.capitalize()}, which only affects the {other} functionality."
        decision = (f"{S2[0].upper() + S2[1:]} (`{other}_{pair.src_type}`) is permitted to access {T2} (`{TF2}`) directly. "
                    f"This is a permanent exception to rule {R} for that module only.")
        return title, "Accepted", context, decision, "No other module is covered by this exception."
    if scenario == "J_adr_cited_by_commit_only":
        title = f"{f['src_abs'].capitalize().replace(' ', ' ')} may read storage directly"
        context = f"{reason.capitalize()}."
        decision = (f"{f['src_abs'].capitalize()} may query {f['tgt_abs']} directly for this purpose. "
                    f"No other code is covered by this decision.")
        return title, "Accepted", context, decision, "Revisit if the data-access approach changes."
    return None


def _adr_content_heldout(scenario: str, wr: random.Random, f: dict, pair: Pair, other: str, cutoff: date | None, number: int):
    """HELD-OUT wordings: the same decisions as `_adr_content`, expressed in different language.

    The primary templates were written alongside the scenarios, so a reader can fairly ask
    whether a method merely learned their phrasing ("permanent exception", "grandfathered",
    "on or before", "reaffirm"). These variants deliberately avoid all of those phrases and use
    other constructions (waiver, sunset date, "turned down", "predates"). They are meant to be
    run ONCE, on the final evaluation, after prompts and policy are frozen.

    Facts that decide the label (which module, which dates, active or superseded) are
    unchanged, and so are the words text-based relevance looks for, so the same ADRs are
    retrieved; only the decision language differs. Uses its own random stream so the
    repositories and histories are identical to the primary benchmark.
    """
    reason = wr.choice(REASONS)
    SF, TF, S, T, R = f["src_stem"], f["tgt_stem"], f["src_desc"], f["tgt_desc"], pair.rule_id
    v = wr.randint(0, 1)
    if scenario in ("B_adr_permanent_exception", "F_adr_superseded"):
        status = "Accepted" if scenario.startswith("B") else f"Superseded by ADR-{number + 20:03d}"
        decision = (f"The team has agreed to sanction direct use of {T} (`{TF}`) by {S} (`{SF}`); rule {R} is waived "
                    f"for this one module and the waiver has no end date." if v == 0 else
                    f"`{SF}` may keep reaching {T} (`{TF}`) without going through the proper layer. {R} does not "
                    f"apply to it, now or later; no other module gets this treatment.")
        return (f"Waiver of {R} for {SF}", status, f"Routing through the proper layer is costly here: {reason}.",
                decision, "Every other module remains bound by the rule.")
    if scenario in ("C_adr_grandfathered_before_cutoff", "D_adr_grandfathered_after_cutoff"):
        c = cutoff.isoformat()
        decision = (f"Direct use of {T} (`{TF}`) by {S} (`{SF}`) is tolerated for code that was already in place by {c}. "
                    f"From {c} onward no new direct use is accepted, and any that appears counts as a breach of {R}." if v == 0 else
                    f"Existing direct access from `{SF}` to `{TF}` stays acceptable while the layer is being built, but only "
                    f"if it predates {c}. A dependency of this kind added after {c} is a breach of {R}.")
        return (f"Time limit on direct {TF} access from {SF}", "Accepted",
                f"Rule {R} forbids this access, but {reason}, and the proper layer will take a while.",
                decision, "Tolerated access is removed once the layer is ready.")
    if scenario == "E_adr_reaffirms_prohibition":
        decision = (f"The proposal to let `{SF}` reach {T} directly was turned down ({wr.choice(REJECTIONS)}). "
                    f"Rule {R} continues to apply to it with no carve-out." if v == 0 else
                    f"We considered letting {S} (`{SF}`) use {T} (`{TF}`) directly and decided against it "
                    f"({wr.choice(REJECTIONS)}); `{SF}` keeps going through the proper layer.")
        return (f"Decision on {SF} reaching {TF}", "Accepted",
                f"Someone asked whether {S} (`{SF}`) could skip the layer, because {reason}.",
                decision, "The concern is handled inside the proper layer.")
    if scenario == "G_adr_passing_mention":
        decision = (f"Code in the {pair.src_type} tier may keep a small in-memory cache of results obtained from the "
                    f"{pair.tgt_type}, refreshed every minute." if v == 0 else
                    f"We will place a short-lived cache between the {pair.src_type} tier and the {pair.tgt_type}; "
                    f"entries expire after sixty seconds.")
        return "Short-lived caching", "Accepted", "Reads are slow under load.", decision, "Data may be up to a minute old."
    if scenario == "K_adr_scope_mismatch":
        S2 = f"the {other} {pair.src_type}"
        T2, TF2 = (("the database connection module", "connection") if pair.tgt_type == "database"
                   else (f"the {other} repository", f"{other}_repository"))
        decision = (f"The team has agreed to sanction direct use of {T2} (`{TF2}`) by {S2} (`{other}_{pair.src_type}`); "
                    f"rule {R} is waived for that module only." if v == 0 else
                    f"`{other}_{pair.src_type}` may keep reaching {T2} (`{TF2}`) without the proper layer. {R} does not "
                    f"apply to that module; other modules are unaffected.")
        return (f"Waiver of {R} for {other}_{pair.src_type}", "Accepted",
                f"{reason.capitalize()}, which only affects the {other} functionality.",
                decision, "No other module is covered.")
    if scenario == "J_adr_cited_by_commit_only":
        decision = (f"{f['src_abs'].capitalize()} is allowed to read from {f['tgt_abs']} directly. "
                    f"The permission covers that code only." if v == 0 else
                    f"We let {f['src_abs']} query {f['tgt_abs']} on its own, without an intermediate layer. "
                    f"No other code is covered.")
        return ("Direct storage reads for one piece of logic", "Accepted", f"{reason.capitalize()}.",
                decision, "Revisit if the data-access approach changes.")
    return None


# ------------------------------------------------------------------ builder


def _file_content(kind: str, e: str, deps: list[str]) -> str:
    lines = list(deps) + ["", ""]
    lines.append(f"class {e.capitalize()}{kind.capitalize()}:")
    lines.append(f'    """{kind.capitalize()} for {e} handling."""')
    lines.append("")
    lines.append("    def run(self):")
    lines.append("        return None")
    return "\n".join(lines) + "\n"


def build_case(root: str, case_id: str, scenario: str, seed: int, wording: str = "primary") -> dict:
    if wording not in ("primary", "heldout"):
        raise ValueError(f"unknown wording {wording!r}")
    rng = random.Random(f"{seed}:{case_id}")
    label = SCENARIOS[scenario][0]
    pair_key = rng.choices(["service_database", "controller_repository", "controller_database"], weights=[6, 3, 1])[0]
    pair = PAIRS[pair_key]
    ents = rng.sample(ENTITIES, 3)
    e, e2, other = ents
    f = _pair_files(pair, e)

    # ---- timeline
    start = date(2025, 3, 1) + timedelta(days=rng.randint(0, 60))
    cutoff = None
    if scenario.startswith("C_") or scenario.startswith("D_"):
        cutoff = start + timedelta(days=rng.randint(130, 210))
        intro = cutoff - timedelta(days=rng.randint(15, 100)) if scenario.startswith("C_") else cutoff + timedelta(days=rng.randint(15, 90))
        adr_date = cutoff - timedelta(days=rng.randint(10, 30))
        snapshot = max(intro, cutoff) + timedelta(days=rng.randint(40, 120))
    elif scenario.startswith("H_"):
        intro = start + timedelta(days=rng.randint(20, 80))
        adr_date, snapshot = None, intro + timedelta(days=rng.randint(180, 380))
    else:
        intro = start + timedelta(days=rng.randint(40, 150))
        adr_date = intro - timedelta(days=rng.randint(10, 40))
        snapshot = intro + timedelta(days=rng.randint(30, 160))

    repo_dir = os.path.join(root, case_id, "repo")
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir)
    g = GitBuilder(repo_dir)

    # ---- initial scaffold: two fully conformant entities
    g.write("architecture/rules.yaml", RULES_YAML)
    for pkg in ("app", "app/controllers", "app/services", "app/repositories", "app/database"):
        g.write(f"{pkg}/__init__.py", "")
    g.write("app/database/connection.py", "def get_connection():\n    return object()\n")
    for ent in (e, e2):
        g.write(f"app/repositories/{ent}_repository.py",
                _file_content("repository", ent, ["from app.database.connection import get_connection"]))
        g.write(f"app/services/{ent}_service.py",
                _file_content("service", ent, [f"from app.repositories.{ent}_repository import {ent.capitalize()}Repository"]))
        g.write(f"app/controllers/{ent}_controller.py",
                _file_content("controller", ent, [f"from app.services.{ent}_service import {ent.capitalize()}Service"]))
    g.commit("Initial project structure", start, rng.choice(AUTHORS))

    # ---- decision records
    adr_number = rng.randint(5, 30)
    noise_n = rng.randint(0, 2)
    adr_files: list[tuple[date, str, str]] = []  # (date, path, text)
    adr_ids = [1, 2, 3, 4]
    for i, (title, body) in enumerate(rng.sample(NOISE_ADRS, noise_n)):
        n = adr_ids[i]
        slug = title.lower().replace(" ", "-")
        noise_date = start + timedelta(days=rng.randint(1, 20))
        text = render_adr(rng.choice(["nygard", "madr", "frontmatter"]), n, title, "Accepted",
                          noise_date, "Recorded for consistency.", body, "None significant.")
        adr_files.append((noise_date, f"architecture/adr/{n:04d}-{slug}.md", text))
    principal = _adr_content(scenario, rng, f, pair, other, cutoff, adr_number)  # always drawn: keeps the rng stream identical
    if wording == "heldout" and principal is not None:
        principal = _adr_content_heldout(scenario, random.Random(f"{seed}:{case_id}:heldout"), f, pair, other, cutoff, adr_number)
    if principal is not None:
        title, status, context, decision, conseq = principal
        slug = title.lower().replace(" ", "-").replace("`", "")[:40]
        text = render_adr(rng.choice(["nygard", "madr", "frontmatter"]), adr_number, title, status, adr_date, context, decision, conseq)
        adr_files.append((adr_date, f"architecture/adr/{adr_number:04d}-{slug}.md", text))

    # ---- events in chronological order
    events: list[tuple[date, int, object]] = []

    def add(d, fn):
        events.append((d, len(events), fn))

    for d, path, text in adr_files:
        def mk(path=path, text=text, d=d):
            def fn():
                g.write(path, text)
                g.commit(f"Record decision {os.path.basename(path).split('-')[0]}", d, rng.choice(AUTHORS))
            return fn
        add(d, mk())

    if scenario.startswith("H_"):
        intro_msg = rng.choice(TEMP_COMMITS).format(e=e)
    elif scenario.startswith("J_"):
        intro_msg = rng.choice(CITING_COMMITS).format(e=e, n=adr_number)
    else:
        intro_msg = rng.choice(NEUTRAL_COMMITS).format(e=e)

    def introduce():
        text = g.read(f["src"])
        g.write(f["src"], f["imp"] + "\n" + text)
        g.append(f["src"], f"\n\ndef {e}_snapshot():\n    return None\n")
        g.commit(intro_msg, intro, rng.choice(AUTHORS))

    add(intro, introduce)

    conformant_files = [f"app/repositories/{e2}_repository.py", f"app/services/{e2}_service.py", f"app/controllers/{e2}_controller.py"]
    n_before, n_after = rng.randint(3, 7), rng.randint(3, 8)
    span_before = max((intro - start).days, 2)
    for i in range(n_before):
        d = start + timedelta(days=rng.randint(1, span_before - 1))
        tgt_file = rng.choice(conformant_files + [f["src"]])
        add(d, _filler(g, rng, d, tgt_file, e, i))
    span_after = max((snapshot - intro).days, 2)
    for i in range(n_after):
        d = intro + timedelta(days=rng.randint(1, span_after - 1))
        tgt_file = f["src"] if i == 0 else rng.choice(conformant_files + [f["src"]])
        add(d, _filler(g, rng, d, tgt_file, e, 100 + i))
    add(snapshot, _filler(g, rng, snapshot, rng.choice(conformant_files), e, 999))

    events.sort(key=lambda t: (t[0], t[1]))
    for _, _, fn in events:
        fn()

    # ---- ground truth
    edges = []
    for ent in (e, e2):
        edges += [
            {"source": f"app/controllers/{ent}_controller.py", "target": f"app/services/{ent}_service.py", "rule_id": "R001", "label": "conformant"},
            {"source": f"app/services/{ent}_service.py", "target": f"app/repositories/{ent}_repository.py", "rule_id": "R002", "label": "conformant"},
            {"source": f"app/repositories/{ent}_repository.py", "target": "app/database/connection.py", "rule_id": "R003", "label": "conformant"},
        ]
    edges.append({"source": f["src"], "target": f["tgt"], "rule_id": pair.rule_id, "label": label})
    meta = {
        "case_id": case_id, "scenario": scenario, "label": label, "pair": pair_key, "wording": wording,
        "target_edge": {"source": f["src"], "target": f["tgt"], "rule_id": pair.rule_id},
        "intended_intro_date": intro.isoformat(), "snapshot_date": snapshot.isoformat(),
        "grandfather_cutoff": cutoff.isoformat() if cutoff else None,
        "adr_number": adr_number if principal else None, "edges": edges,
    }
    with open(os.path.join(root, case_id, "labels.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def _filler(g: GitBuilder, rng: random.Random, d: date, path: str, e: str, i: int):
    author, msg = rng.choice(AUTHORS), rng.choice(FILLER_COMMITS).format(e=e)

    def fn():
        g.append(path, f"\n# note {i}\n")
        g.commit(msg, d, author)
    return fn


def generate_benchmark(out_dir: str, seed: int = 7, wording: str = "primary") -> dict:
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"seed": seed, "wording": wording, "cases": []}
    for scenario, (label, count) in SCENARIOS.items():
        ids = [f"{scenario.split('_')[0]}{i + 1:02d}" for i in range(count)]
        order = list(range(count))
        random.Random(f"{seed}:split:{scenario}").shuffle(order)
        dev_n = (count + 1) // 2
        for pos, idx in enumerate(range(count)):
            case_id = ids[idx]
            meta = build_case(out_dir, case_id, scenario, seed, wording)
            manifest["cases"].append({
                "case_id": case_id, "scenario": scenario, "label": label,
                "split": "dev" if order.index(idx) < dev_n else "test",
                "path": case_id,
            })
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate the controlled conformance benchmark.")
    ap.add_argument("--out", default="../datasets/benchmark/generated")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--wording", choices=["primary", "heldout"], default="primary",
                    help="heldout = same repositories, ADR decision language rewritten (run once, on the frozen final evaluation)")
    args = ap.parse_args()
    m = generate_benchmark(args.out, args.seed, args.wording)
    by = {}
    for c in m["cases"]:
        by.setdefault((c["split"], c["label"]), 0)
        by[(c["split"], c["label"])] += 1
    print(f"Generated {len(m['cases'])} cases in {args.out}")
    for k in sorted(by):
        print(f"  {k[0]:>4} {k[1]:>9}: {by[k]}")
