"""Remediation advice for a confirmed architectural drift: "how would I fix this?"

Two layers, kept visibly separate so a reader always knows which part is which:

1. RULE-DERIVED options (deterministic, always available, no model). From the architecture rules the code finds the
   sanctioned route between the two component types (for example service -> repository -> database), and offers
   the standard fix steps for it, a "document it as an exception" option with a ready ADR draft, and (when the same
   rule is broken repeatedly) a "review the rule" option.
2. AI-TAILORED steps (optional, needs a model). The model is shown the rule, the two files, the offending import, the
   sanctioned route and the history, and asked to choose one of the rule-derived options and write concrete steps for
   THIS code. It invents no architecture: it picks from the options and personalises the steps.

Safeguards, in line with the rest of the project (the model proposes, code checks):
* the reply must parse as the requested JSON and name one of the offered options; otherwise the rule-derived advice stands alone;
* every file name the model writes is checked against the files of the analysed repository; unknown ones are
  reported in `warnings` rather than trusted;
* nothing is applied to the code. The result is always labelled as a suggestion to review.

This feature is NOT part of the evaluated methods (M1-M8) and has not been measured: no accuracy claim is made for the
AI-tailored steps.
"""
from __future__ import annotations

import json
import os
import re
from collections import deque
from typing import Any, Optional

from analysis.evidence.aggregator import EvidenceBundle
from analysis.semantic.llm_client import LLMClient
from models.rule import Architecture, RelationType

DISCLAIMER = "Suggestion only. Review before applying; nothing here has been changed in your code."
MAX_STEPS, MAX_RISKS, MAX_TEXT = 6, 3, 220

SYSTEM_REMEDIATION = (
    "You are a careful software architect. You help fix one architectural violation. "
    "Use only the facts given. Do not invent files, classes or layers. Reply with one JSON object and nothing else."
)


# ------------------------------------------------------------------ sanctioned routes (pure code)

def allowed_paths(architecture: Architecture, source_type: str, target_type: str, limit: int = 3, max_hops: int = 4) -> list[list[str]]:
    """Shortest routes source_type -> ... -> target_type that use only ALLOWED rules, never the direct edge itself.

    Example with the sample rules: service -> repository -> database."""
    edges: dict[str, set[str]] = {}
    for r in architecture.rules:
        if r.relation == RelationType.ALLOWED:
            edges.setdefault(r.source, set()).add(r.target)
    found: list[list[str]] = []
    queue = deque([[source_type]])
    while queue and len(found) < limit:
        path = queue.popleft()
        if len(path) - 1 >= max_hops:
            continue
        for nxt in sorted(edges.get(path[-1], ())):
            if nxt in path:
                continue
            if nxt == target_type:
                if len(path) >= 2:  # a route with at least one intermediate layer
                    found.append(path + [nxt])
                continue
            queue.append(path + [nxt])
    return found


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def adr_draft(bundle: EvidenceBundle) -> str:
    """A skeleton ADR recording the dependency as a deliberate exception. Placeholders are in <angle brackets>.

    The wording uses phrases the project's own reader understands (a permission with a stated scope)."""
    ev = bundle.evolution or {}
    since = (ev.get("introduced_at") or "")[:10] if ev.get("available") else ""
    since = since or "<date the dependency was introduced>"
    return (
        "# ADR-<number>: Allow `{src}` to use `{tgt}` directly\n\n"
        "Date: <today>\n\n## Status\n\nAccepted\n\n## Context\n\n"
        "Rule {rule} ({desc}) is broken by `{src}` importing `{tgt}` (introduced {since}). "
        "<Why the sanctioned route is not suitable here.>\n\n## Decision\n\n"
        "We accept that `{src}` will use `{tgt}` directly, as an exception to rule {rule}. "
        "<Optional: this exception is permanent / ends on YYYY-MM-DD.>\n\n## Consequences\n\n"
        "<What this costs, and who reviews it again.>\n"
    ).format(src=_stem(bundle.source_path), tgt=_stem(bundle.target_path), rule=bundle.rule_id or "<rule>", desc=(bundle.rule_description or "").rstrip("."), since=since)


def template_options(bundle: EvidenceBundle, architecture: Architecture, rule_violation_count: int = 1) -> list[dict]:
    src, tgt = _stem(bundle.source_path), _stem(bundle.target_path)
    where = f"line {bundle.line}" if bundle.line else "the import"
    options: list[dict] = []
    for route in allowed_paths(architecture, bundle.source_type, bundle.target_type):
        via = route[1:-1]
        label = " -> ".join(route)
        mid = via[0]
        options.append({
            "id": f"route_via_{'_'.join(via)}",
            "title": f"Route the call through the {', '.join(via)} layer",
            "effort": "medium",
            "why": f"The architecture already allows {label}; `{src}` should use that route instead of reaching `{tgt}` directly.",
            "steps": [
                f"Find what `{src}` needs from `{tgt}` ({where}: `{bundle.import_reference or tgt}`).",
                f"Expose that capability on a {mid} component (reuse an existing one if there is one, otherwise add a small new {mid}).",
                f"Change `{src}` to call the {mid} instead of `{tgt}`.",
                f"Remove the direct import of `{tgt}` from `{src}`.",
                "Re-run the analysis: this finding should disappear and no new one should appear.",
            ],
            "route": route,
        })
    options.append({
        "id": "document_exception",
        "title": "Keep it and document it as a deliberate exception",
        "effort": "low",
        "why": "If the dependency is intentional, record why in an Architecture Decision Record so the analysis can recognise it as justified.",
        "steps": [
            "Write an ADR using the draft below (fill in the reason and whether it is permanent or temporary).",
            "Commit it in the repository's ADR folder, naming both modules.",
            "Re-run the analysis: the finding should be resolved as justified by the ADR.",
        ],
        "adr_draft": adr_draft(bundle),
    })
    if rule_violation_count >= 3:
        options.append({
            "id": "review_rule",
            "title": "Review the rule itself",
            "effort": "medium",
            "why": f"Rule {bundle.rule_id} is broken in {rule_violation_count} places, which may mean the rule no longer matches how the system is really built.",
            "steps": [
                f"List the {rule_violation_count} findings of rule {bundle.rule_id} and decide whether they are accidents or a pattern.",
                "If it is a pattern, amend the rule (or add an exception) in the architecture file and record the decision in an ADR.",
                "If they are accidents, fix them one by one using the routing option.",
            ],
        })
    return options


# ------------------------------------------------------------------ the AI layer

def render_prompt(bundle: EvidenceBundle, options: list[dict]) -> str:
    ev = bundle.evolution or {}
    hist = "no history available"
    if ev.get("available") and ev.get("introducing_commit"):
        c = ev["introducing_commit"]
        hist = f"introduced {(ev.get('introduced_at') or '?')[:10]} in a commit titled: {str(c.get('message', ''))[:100]}"
    snippet = "\n".join((bundle.code_snippet or "").splitlines()[:14])
    opts = "\n".join(f"- {o['id']}: {o['title']}" for o in options)
    return (
        f"Rule {bundle.rule_id}: {bundle.rule_description} (relation: {bundle.rule_relation})\n"
        f"Offending file: {bundle.source_path} (type {bundle.source_type})\n"
        f"It depends on: {bundle.target_path} (type {bundle.target_type}), {('line ' + str(bundle.line)) if bundle.line else 'import'}\n"
        f"History: {hist}\n"
        f"Code around the import:\n{snippet}\n\n"
        f"Fix options already identified by the architecture rules:\n{opts}\n\n"
        "Choose the best option for this code and write concrete steps for it. "
        "Name only the two files above or well-known layer names. Reply as JSON with exactly these keys:\n"
        '{"summary": "<one or two sentences: why this is drift and what the fix achieves>", '
        '"recommended_option": "<one of the option ids above>", '
        '"steps": ["<imperative step>", "..."], "risks": ["<what could go wrong>"]}'
    )


def _first_json(text: str) -> Optional[dict]:
    if not text:
        return None
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(text[start: i + 1])
                except ValueError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _clean(items: Any, cap: int) -> list[str]:
    if not isinstance(items, list):
        return []
    out = [re.sub(r"\s+", " ", x).strip()[:MAX_TEXT] for x in items if isinstance(x, str) and x.strip()]
    return out[:cap]


_FILEISH = re.compile(r"[\w./\\-]+\.(?:py|js|jsx|ts|tsx|java|cs|go|rb|php|kt)\b")


def parse_advice(text: str, option_ids: list[str]) -> Optional[dict]:
    """The model's advice, validated. None when it cannot be used (then the rule-derived advice stands alone)."""
    obj = _first_json(text)
    if obj is None:
        return None
    rec = obj.get("recommended_option")
    steps = _clean(obj.get("steps"), MAX_STEPS)
    if rec not in option_ids or not steps:
        return None
    return {"summary": re.sub(r"\s+", " ", str(obj.get("summary", ""))).strip()[:400], "recommended_option": rec, "steps": steps,
            "risks": _clean(obj.get("risks"), MAX_RISKS)}


def unknown_references(advice: dict, known_files: set[str], bundle: EvidenceBundle) -> list[str]:
    """File names the model mentions that are not part of the analysed repository (nor the two files in question)."""
    known = {os.path.basename(f).lower() for f in known_files} | {os.path.basename(bundle.source_path).lower(), os.path.basename(bundle.target_path).lower()}
    text = " ".join([advice.get("summary", ""), *advice.get("steps", []), *advice.get("risks", [])])
    seen: list[str] = []
    for m in _FILEISH.findall(text):
        base = os.path.basename(m.replace("\\", "/")).lower()
        if base not in known and base not in seen:
            seen.append(base)
    return seen


class RemediationAnalyzer:
    def __init__(self, client: Optional[LLMClient], max_tokens: int = 500):
        self.client, self.max_tokens = client, max_tokens

    def suggest(self, bundle: EvidenceBundle, architecture: Architecture, *, known_files: set[str] | None = None,
                rule_violation_count: int = 1, finding_id: str = "", justified: bool = False) -> dict:
        base: dict = {"finding_id": finding_id, "disclaimer": DISCLAIMER, "model": None, "tokens_used": None, "latency_s": None,
                      "warnings": [], "error": None, "ai": None}
        if justified:
            return {**base, "source": "rules", "summary": "The evidence indicates this dependency is an intentional, documented exception, so no fix is recommended.",
                    "recommended_option": None, "options": [], "note": "If the exception is no longer wanted, update or supersede the ADR that justifies it."}
        options = template_options(bundle, architecture, rule_violation_count)
        ids = [o["id"] for o in options]
        out = {**base, "source": "rules", "summary": (f"Rule {bundle.rule_id} is broken: {bundle.rule_description}".rstrip(".") + "."),
               "recommended_option": ids[0], "options": options, "note": None}
        if self.client is None:
            out["note"] = "No language model is configured, so only rule-derived options are shown."
            return out
        resp = self.client.complete(SYSTEM_REMEDIATION, render_prompt(bundle, options), temperature=0.2, max_tokens=self.max_tokens)
        out.update(model=resp.model, tokens_used={"input": resp.input_tokens, "output": resp.output_tokens}, latency_s=resp.latency_s)
        if not resp.ok:
            out["error"] = resp.error
            out["note"] = "The model could not be reached, so only rule-derived options are shown."
            return out
        advice = parse_advice(resp.text, ids)
        if advice is None:
            out["note"] = "The model's reply could not be used, so only rule-derived options are shown."
            return out
        warnings = unknown_references(advice, known_files or set(), bundle)
        out["source"] = "ai"
        out["recommended_option"] = advice["recommended_option"]
        out["ai"] = {**advice}
        if advice["summary"]:
            out["summary"] = advice["summary"]
        if warnings:
            out["warnings"] = [f"The AI mentioned file(s) not found in this repository: {', '.join(warnings)}. Check them before following the steps."]
        return out
