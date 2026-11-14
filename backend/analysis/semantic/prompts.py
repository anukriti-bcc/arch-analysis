"""Prompt construction for LLM semantic analysis.

Kept separate from the client and the analyzer so the exact text sent to the
model is easy to inspect, version and report in the thesis. Two modes:

  * review  — the deterministic checker already flagged a dependency; the model
              decides violation vs justified using supplied evidence (M3, M4, M5).
  * edge    — no structural pre-check; the model sees raw rules/ADRs and a
              single import and must decide everything itself (M2, LLM-only).
"""
from __future__ import annotations

from analysis.evidence.aggregator import EvidenceBundle

PROMPT_VERSION = "v1"
MAX_ADR_CHARS = 3500

SYSTEM_REVIEW = """You are a software-architecture conformance reviewer.
An automated checker has flagged one dependency in a code repository as violating a declared architectural rule. Decide whether it is a genuine violation, or is justified by documented architectural intent (for example an accepted Architecture Decision Record that explicitly permits it).

Guidance:
- Judge only from the evidence supplied. Do not assume facts that are not stated.
- A decision record authorises the dependency only if (a) its status is active (for example accepted; not superseded, rejected or deprecated), (b) it covers THIS specific dependency or code rather than a different module, and (c) every condition it states (dates, deadlines, grandfathering clauses, scope limits) is satisfied by the facts provided.
- A record that merely mentions the same components, or that restates the rule, does not authorise an exception.
- A commit message or comment calling something "temporary" does not by itself justify it.
- If a condition depends on a fact that is not provided (for example the date the dependency was introduced), answer "uncertain".

Respond with ONLY one JSON object, no other text:
{"verdict": "violation" | "justified" | "uncertain", "confidence": <number 0 to 1>, "explanation": "<at most two sentences>", "evidence_used": ["<short labels, e.g. ADR-007, introduction date>"]}"""

SYSTEM_EDGE = """You are a software-architecture conformance reviewer.
You are given a repository's declared architecture (component types and rules), its architecture decision records (ADRs), and ONE import statement from its source code. Decide whether this import is consistent with the architecture.

Verdicts:
- "conformant": the import follows the declared architecture (allowed by the rules, or not restricted).
- "violation": the import breaks a declared rule and no active decision record permits it.
- "justified": the import breaks a declared rule but an active decision record permits this specific dependency.
- "uncertain": the evidence supplied is insufficient to decide.

Guidance:
- Judge only from the evidence supplied; map file paths to component types using the declared directory mapping.
- A decision record authorises a rule-breaking dependency only if it is active (not superseded, rejected or deprecated), covers this specific dependency rather than a different module, and every condition it states is satisfied by the facts provided.
- A record that merely mentions the same components, or restates the rule, does not authorise an exception.

Respond with ONLY one JSON object, no other text:
{"verdict": "conformant" | "violation" | "justified" | "uncertain", "confidence": <number 0 to 1>, "explanation": "<at most two sentences>", "evidence_used": ["<short labels>"]}"""


# Sensitivity-analysis variants. The "full" prompts above contain guidance (grandfathering
# clauses, "temporary" commits, records that merely mention components) that closely mirrors
# the benchmark's scenarios. A critic can fairly say that is teaching to the test. The
# "minimal" variants keep the task and the output format but drop ALL of that guidance, so the
# experiment can show how much of the measured performance comes from the evidence supplied
# and how much from instructions we wrote with the scenarios in mind.
SYSTEM_REVIEW_MINIMAL = """You are a software-architecture reviewer.
An automated checker has flagged one dependency in a code repository as violating a declared architectural rule. Decide whether it is a genuine violation or is justified.

Respond with ONLY one JSON object, no other text:
{"verdict": "violation" | "justified" | "uncertain", "confidence": <number 0 to 1>, "explanation": "<at most two sentences>", "evidence_used": ["<short labels>"]}"""

SYSTEM_EDGE_MINIMAL = """You are a software-architecture reviewer.
You are given a repository's declared architecture, its architecture decision records, and ONE import statement from its source code. Decide whether the import is consistent with the architecture.

Verdicts: "conformant" (follows the architecture), "violation" (breaks a rule and nothing permits it), "justified" (breaks a rule but is permitted), "uncertain".

Respond with ONLY one JSON object, no other text:
{"verdict": "conformant" | "violation" | "justified" | "uncertain", "confidence": <number 0 to 1>, "explanation": "<at most two sentences>", "evidence_used": ["<short labels>"]}"""

# variant name -> (review system prompt, edge system prompt)
PROMPT_VARIANTS = {
    "full": (SYSTEM_REVIEW, SYSTEM_EDGE),
    "minimal": (SYSTEM_REVIEW_MINIMAL, SYSTEM_EDGE_MINIMAL),
}


def _clip(text: str, limit: int = MAX_ADR_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[... truncated ...]"


def _render_adr(adr, reasons=None) -> str:
    """Each record is wrapped in explicit <adr> tags: ADR files carry their own
    markdown headings ('## Context', '## Decision'), which would otherwise be
    indistinguishable from this prompt's own section headings."""
    meta = [f"Title: {adr.title}", f"Status (parsed): {adr.status}"]
    if adr.status_raw and adr.status_raw.lower() != adr.status:
        meta[-1] += f"  (as written: {adr.status_raw})"
    if adr.date:
        meta.append(f"Date: {adr.date.isoformat()}")
    if reasons:
        meta.append(f"Selected because: {', '.join(reasons)}")
    return f'<adr id="{adr.id}">\n' + "\n".join(meta) + "\n\n" + _clip(adr.text.strip()) + "\n</adr>"


def render_evolution(evolution: dict | None, snapshot_date: str | None) -> str:
    if not evolution or not evolution.get("available"):
        return "No version-control history is available for this dependency."
    intro = evolution.get("introducing_commit")
    if not intro:
        return "The dependency is not present in committed history at HEAD."
    sig = evolution.get("message_signals", {})
    lines = [
        f"The dependency was introduced on {evolution['introduced_at'][:10]} "
        f"(commit {intro['short']} by {intro['author']}), "
        f"{evolution['age_days']} days before the snapshot date.",
        f"Introducing commit message: \"{intro['message'].strip()}\"",
        f"It has been continuously present since then; {evolution['commits_since_introduction']} commit(s) "
        f"were made to the repository afterwards, {evolution['relevant_commits_since_introduction']} of them touching the two files involved.",
    ]
    if evolution.get("introduced_with_file_creation"):
        lines.append("The source file was created in the same commit that introduced the dependency.")
    if evolution.get("reintroduced"):
        lines.append(
            f"The dependency was removed at least once and later reintroduced (first introduced "
            f"{evolution['first_introduced_at'][:10]})."
        )
    flags = []
    if sig.get("temporary_language"):
        flags.append("temporary-language in commit message: " + ", ".join(sig["temporary_language"]))
    if sig.get("migration_language"):
        flags.append("migration-language: " + ", ".join(sig["migration_language"]))
    if sig.get("adr_references"):
        flags.append("ADRs cited by the commit: " + ", ".join(sig["adr_references"]))
    if sig.get("issue_references"):
        flags.append("issues cited: " + ", ".join(sig["issue_references"]))
    if flags:
        lines.append("Signals: " + "; ".join(flags) + ".")
    return "\n".join(lines)


def render_review_prompt(bundle: EvidenceBundle, *, include_adrs: bool, include_evolution: bool) -> str:
    parts = [
        f"Repository snapshot date: {bundle.snapshot_date[:10] if bundle.snapshot_date else 'unknown'}",
        "",
        "## Flagged dependency",
        f"Source file: {bundle.source_path} (component type: {bundle.source_type})",
        f"Target file: {bundle.target_path} (component type: {bundle.target_type})",
        f"Triggered rule {bundle.rule_id} [{bundle.rule_relation}]: {bundle.rule_description}",
        "Code around the import:",
        bundle.code_snippet or "(not available)",
    ]
    if include_adrs:
        parts += ["", "## Architecture decision records possibly relevant to this dependency"]
        if bundle.adrs:
            parts += [_render_adr(m.adr, m.reasons) for m in bundle.adrs]
        else:
            parts.append("None found.")
    if include_evolution:
        parts += ["", "## Version-control history of this dependency", render_evolution(bundle.evolution, bundle.snapshot_date)]
    parts += ["", "Decide: is this dependency a genuine violation, or justified by documented intent? Reply with the JSON object only."]
    return "\n".join(parts)


def render_edge_prompt(
    *,
    snapshot_date: str | None,
    mapping_text: str,
    rules_text: str,
    adrs: list,
    source_path: str,
    target_path: str,
    import_reference: str,
    code_snippet: str,
) -> str:
    parts = [
        f"Repository snapshot date: {snapshot_date[:10] if snapshot_date else 'unknown'}",
        "",
        "## Declared architecture",
        "Directory -> component type:",
        mapping_text,
        "Rules:",
        rules_text,
        "",
        "## Architecture decision records in this repository",
    ]
    parts += [_render_adr(a) for a in adrs] if adrs else ["None."]
    parts += [
        "",
        "## Import to assess",
        f"Source file: {source_path}",
        f"Imports: {import_reference}  (resolves to {target_path})",
        "Code around the import:",
        code_snippet or "(not available)",
        "",
        "Reply with the JSON object only.",
    ]
    return "\n".join(parts)
