"""Extract-then-compute resolution of a flagged dependency (method M7).

The measured problem (hard tier, docs/HARD_TIER.md and the 2026-11 results): when an ADR grandfathers
dependencies introduced up to a date, every LLM method scored 0 of 6 on the after-cutoff case. The model
read the ADR correctly and then invented the date comparison ("introduced before the freeze date").

The fix is a division of labour, not a better prompt:

    LLM   reads the record and EXTRACTS facts it is good at: does the decision permit or prohibit,
          does it cover THIS module, and is the permission limited to dependencies introduced within a
          time window (the limit's kind and calendar date, copied from the text).
    CODE  COMPUTES the verdict: it compares the introduction date (from Git) with the extracted limit.

The prompt therefore deliberately withholds the introduction date, the snapshot date and the dependency's
age, so the model has nothing to do arithmetic with. Everything the model is asked is a reading task.

Failure handling is explicit and conservative: an unparseable reply, an unclear scope, a stated limit with
no usable date, or an unknown introduction date all leave the structural verdict (violation) in place and
are labelled `fallback`, never guessed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from analysis.evidence.aggregator import EvidenceBundle
from analysis.semantic.llm_client import LLMClient
from analysis.semantic.prompts import _render_adr

EXTRACT_VERSION = "x2"

DECISIONS = {"permits", "prohibits", "does_not_address"}
COVERS = {"yes", "no", "unclear"}
LIMITS = {"none", "introduced_on_or_before", "introduced_before", "introduced_after"}

SYSTEM_EXTRACT = """You read architecture decision records (ADRs) and report facts from them. You do NOT decide whether the dependency is a violation, and you must NOT compare dates or do any date arithmetic: other software does that.

An automated checker flagged one dependency as breaking a declared architectural rule. Read the ADR(s) provided and report:

- "decision": what the ADR's decision says about this kind of access.
    "permits"          the decision allows, accepts or tolerates it (including as an accepted trade-off or exception);
    "prohibits"        the decision forbids it, rejects it, or declines to approve it;
    "does_not_address" the ADR is about something else.
  An alternative that was rejected inside a decision that permits the access does not make the decision a prohibition.
  Ignore ADRs whose status is not active (superseded, rejected, deprecated).
- "covers_this_dependency": does the decision apply to THIS source module?
    "yes"     the source module is named, or described unambiguously as the same code; or the introducing commit cites this ADR (see the history notes and the "Selected because" line). A decision that describes the code by its purpose rather than by file name still covers it when the commit cites it;
    "no"      the decision names or describes a different module, or expressly excludes this one;
    "unclear" you cannot tell.
- "limit": is the permission restricted to dependencies introduced within a time window?
    "none"                     no date limit;
    "introduced_on_or_before"  permitted only for code introduced up to and including a date;
    "introduced_before"        permitted only for code introduced strictly before a date;
    "introduced_after"         permitted only for code introduced after a date.
- "limit_date": the calendar date of that limit as written in the decision text, converted to YYYY-MM-DD, or null. Copy the date; never calculate one. If the limit is not a specific calendar date (for example "until the migration completes"), use limit "none" and null.

Respond with ONLY one JSON object, no other text:
{"adr_id": "<id of the ADR you relied on, or null>", "decision": "permits" | "prohibits" | "does_not_address", "covers_this_dependency": "yes" | "no" | "unclear", "limit": "none" | "introduced_on_or_before" | "introduced_before" | "introduced_after", "limit_date": "YYYY-MM-DD" | null, "explanation": "<at most two sentences>"}"""


def render_history_undated(evolution: dict | None) -> str:
    """History evidence WITHOUT any date, age or snapshot: the model must not be handed the numbers
    it would be tempted to compare."""
    if not evolution or not evolution.get("available"):
        return "No version-control history is available for this dependency."
    intro = evolution.get("introducing_commit")
    if not intro:
        return "The dependency is not present in committed history at HEAD."
    sig = evolution.get("message_signals", {})
    lines = [f"Introducing commit message: \"{intro['message'].strip()}\""]
    if evolution.get("introduced_with_file_creation"):
        lines.append("The source file was created in the same commit that introduced the dependency.")
    if evolution.get("reintroduced"):
        lines.append("The dependency was removed at least once and later reintroduced.")
    flags = []
    if sig.get("temporary_language"):
        flags.append("temporary-language in commit message: " + ", ".join(sig["temporary_language"]))
    if sig.get("adr_references"):
        flags.append("ADRs cited by the commit: " + ", ".join(sig["adr_references"]))
    if flags:
        lines.append("Signals: " + "; ".join(flags) + ".")
    return "\n".join(lines)


def render_extract_prompt(bundle: EvidenceBundle) -> str:
    parts = [
        "## Flagged dependency",
        f"Source file: {bundle.source_path} (component type: {bundle.source_type})",
        f"Target file: {bundle.target_path} (component type: {bundle.target_type})",
        f"Triggered rule {bundle.rule_id} [{bundle.rule_relation}]: {bundle.rule_description}",
        "Code around the import:",
        bundle.code_snippet or "(not available)",
        "",
        "## Architecture decision records possibly relevant to this dependency",
    ]
    parts += [_render_adr(m.adr, m.reasons) for m in bundle.adrs] if bundle.adrs else ["None found."]
    parts += ["", "## Notes from version-control history (no dates are given on purpose)",
              render_history_undated(bundle.evolution),
              "", "Report the facts as the JSON object only."]
    return "\n".join(parts)


# ------------------------------------------------------------------ parsing

def _norm(value: Any) -> str:
    return re.sub(r"[\s-]+", "_", str(value).strip().lower())


def _iso_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def parse_extraction_json(text: str) -> dict | None:
    """First JSON object in the reply with valid enumerations; None when none can be recovered."""
    if not text:
        return None
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start: i + 1])
                break
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        decision, covers, limit = _norm(obj.get("decision", "")), _norm(obj.get("covers_this_dependency", "")), _norm(obj.get("limit", "none") or "none")
        if decision not in DECISIONS or covers not in COVERS or limit not in LIMITS:
            continue
        adr_id = obj.get("adr_id")
        return {
            "adr_id": None if adr_id in (None, "", "null") else str(adr_id),
            "decision": decision, "covers_this_dependency": covers, "limit": limit,
            "limit_date": _iso_date(obj.get("limit_date")),
            "explanation": str(obj.get("explanation", "")).strip(),
        }
    return None


# ------------------------------------------------------------------ the computation (pure code)

@dataclass
class Resolution:
    outcome: str  # 'justified' | 'violation' | 'unresolved'
    note: str

    @property
    def predicted_violation(self) -> bool:
        return self.outcome != "justified"  # unresolved keeps the structural verdict


def resolve_extraction(x: dict, introduced: Optional[date]) -> Resolution:
    """Turn extracted facts plus the Git introduction date into a verdict. No model involved."""
    if x["decision"] != "permits":
        return Resolution("violation", f"decision {x['decision']}")
    if x["covers_this_dependency"] == "no":
        return Resolution("violation", "permits, but not for this module")
    if x["covers_this_dependency"] == "unclear":
        return Resolution("unresolved", "permits, but scope unclear")
    if x["limit"] == "none":
        return Resolution("justified", "permits this module, no date limit")
    limit_date: Optional[date] = x["limit_date"]
    if limit_date is None:
        return Resolution("unresolved", f"limit {x['limit']} stated without a usable date")
    if introduced is None:
        return Resolution("unresolved", "limit stated but the introduction date is unknown")
    ok = {"introduced_on_or_before": introduced <= limit_date,
          "introduced_before": introduced < limit_date,
          "introduced_after": introduced > limit_date}[x["limit"]]
    sign = {True: "satisfies", False: "does not satisfy"}[ok]
    return Resolution("justified" if ok else "violation",
                      f"introduced {introduced.isoformat()} {sign} '{x['limit']} {limit_date.isoformat()}'")


# ------------------------------------------------------------------ the call

class LLMExtractAnalyzer:
    """One call per escalated finding, same budget as the review analyzer (M5)."""

    def __init__(self, client: LLMClient, max_tokens: int = 400):
        self.client, self.max_tokens = client, max_tokens

    def extract(self, bundle: EvidenceBundle) -> dict:
        resp = self.client.complete(SYSTEM_EXTRACT, render_extract_prompt(bundle), temperature=0.0, max_tokens=self.max_tokens)
        parsed = parse_extraction_json(resp.text) if resp.ok else None
        return {
            "mode": "extract", "extract_version": EXTRACT_VERSION, "parsed": parsed, "parsed_ok": parsed is not None,
            "error": resp.error if not resp.ok else (None if parsed else "unparseable model output"),
            "model": resp.model, "tokens_used": {"input": resp.input_tokens, "output": resp.output_tokens},
            "tokens_estimated": resp.tokens_estimated, "latency_s": resp.latency_s, "cached": resp.cached,
            "raw_text": resp.text,
        }
