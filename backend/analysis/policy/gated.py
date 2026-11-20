"""Readability-gated escalation policy (policy v2, method M8).

The v1 policy (`escalation.py`, methods M5/M7, frozen) escalates every finding
that has an active relevant ADR. That is thin: on the hard tier it makes 171
calls where an oracle needs 72, and it never asks whether code could already
read the ADR. This policy replaces "an ADR exists" with the question the
synopsis's "Evidence sufficient?" diamond really asks:

    Is the evidence enough to decide WITHOUT a model, and can that decision be trusted?

Every structural violation is routed one of three ways, cheapest first:

  direct_structural  no active, strongly scoped ADR is about this dependency
                     (none exists, all are inactive, or they only share
                     component-type words) and history shows nothing ambiguous
                     -> the structural verdict "violation" stands.
  direct_code        an active, strongly scoped ADR exists AND its code reading
                     passes every readability gate (`analysis.intent.readability`)
                     -> the code verdict (permits => justified, else violation).
  escalate           anything else: the reading is unclear or fails a gate,
                     or history signals an ambiguity -> semantic review
                     (extract-then-compute for an ADR, review prompt otherwise).

Rule ids kept from v1 so reasons stay comparable: I2 (inactive ADRs), H1-H3
(history). New: W1 (weak scope is not relevance), R1 (trusted reading), R2
(reading not trustworthy, with the failing gates named).

Switches, so each idea can be ablated:
  use_history      H1-H3 may trigger escalation (as v1)
  weak_irrelevant  W1 on: a weakly scoped ADR does not count as intent about this dependency
  use_gates        R1/R2 on: code may decide; off = every strong active ADR escalates (v1 behaviour
                   apart from W1)

Budget: `risk` orders escalations (more failed gates = riskier); `Budgeted` below keeps the k riskiest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from analysis.evidence.aggregator import EvidenceBundle
from analysis.intent.reader import introduction_date
from analysis.intent.readability import assess, governing_adr, scope_of

DIRECT_STRUCTURAL, DIRECT_CODE, ESCALATE = "direct_structural", "direct_code", "escalate"


@dataclass
class GatedDecision:
    route: str
    escalate: bool
    predicted_violation: Optional[bool]  # set for direct routes, None when escalating
    reasons: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)
    risk: float = 0.0
    adr_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "route": self.route, "escalate": self.escalate, "predicted_violation": self.predicted_violation,
            "reasons": self.reasons, "failed_gates": self.failed_gates, "risk": self.risk, "adr_id": self.adr_id,
        }


def _history_reasons(bundle: EvidenceBundle) -> list[str]:
    ev = bundle.evolution
    out: list[str] = []
    if ev and ev.get("available") and ev.get("introducing_commit"):
        sig = ev.get("message_signals", {})
        if sig.get("temporary_language"):
            out.append("H1: introducing commit describes the change as temporary")
        if sig.get("migration_language"):
            out.append("H2: introducing commit mentions migration/legacy/transition")
        if ev.get("reintroduced"):
            out.append("H3: dependency was removed and later reintroduced")
    return out


class ReadabilityGatedPolicy:
    def __init__(self, use_history: bool = True, weak_irrelevant: bool = True, use_gates: bool = True):
        self.use_history, self.weak_irrelevant, self.use_gates = use_history, weak_irrelevant, use_gates

    def decide(self, bundle: EvidenceBundle) -> GatedDecision:
        matches = bundle.adrs
        active = [m for m in matches if m.adr.is_active]
        if matches and not active:  # I2, as v1: nothing authorises the dependency
            return GatedDecision(
                DIRECT_STRUCTURAL, False, True,
                ["I2: relevant records are all inactive (" + ", ".join(f"{m.adr.id}={m.adr.status}" for m in matches) + ")"],
            )

        history = _history_reasons(bundle) if self.use_history else []
        strong = [m for m in active if scope_of(m, bundle.source_path, bundle.target_path) != "weak"]
        relevant = strong if self.weak_irrelevant else active

        if not relevant:
            reasons = []
            if active and self.weak_irrelevant:
                reasons.append("W1: active ADR(s) " + ", ".join(m.adr.id for m in active) + " share only component-type words with this dependency")
            if history:
                return GatedDecision(ESCALATE, True, None, reasons + history, [], float(len(history)))
            return GatedDecision(
                DIRECT_STRUCTURAL, False, True, reasons + ["evidence sufficient: no relevant active intent and no ambiguity signal in history"],
            )

        # at least one active, relevant ADR
        if not self.use_gates:
            return GatedDecision(ESCALATE, True, None, ["I1: active relevant decision record(s): " + ", ".join(m.adr.id for m in relevant)] + history, [], 1.0 + len(history))

        gov, others = governing_adr(matches, bundle.source_path, bundle.target_path)
        if gov is None:  # relevant (weak-allowed) but nothing strong to read: let the model look
            return GatedDecision(ESCALATE, True, None, ["R2: no strongly scoped ADR to read"] + history, ["G_scope"], 2.0 + len(history))
        r = assess(
            gov.adr, introduced=introduction_date(bundle.evolution),
            source_path=bundle.source_path, target_path=bundle.target_path, other_strong_active=others,
        )
        if r.decisive and r.verdict_violation is not None:
            return GatedDecision(
                DIRECT_CODE, False, r.verdict_violation,
                [f"R1: {gov.adr.id} read by code and passed every gate ({r.reading.stance}; " + "; ".join(r.reading.notes) + ")"],
                [], 0.0, gov.adr.id,
            )
        risk = len(r.failed) + (1.0 if "G_clear" in r.failed else 0.0) + 0.5 * len(history)
        return GatedDecision(ESCALATE, True, None, ["R2: " + n for n in r.notes] + history, r.failed, risk, gov.adr.id)


def apply_budget(decisions: list[GatedDecision], k: int) -> list[GatedDecision]:
    """Keep the k riskiest escalations, turn the rest into their cheapest safe fallback (structural violation).

    Ties are broken by input order, so the result is deterministic. `k >= number of escalations` changes nothing.
    """
    idx = [i for i, d in enumerate(decisions) if d.escalate]
    keep = set(sorted(idx, key=lambda i: (-decisions[i].risk, i))[: max(k, 0)])
    out = []
    for i, d in enumerate(decisions):
        if d.escalate and i not in keep:
            out.append(GatedDecision(DIRECT_STRUCTURAL, False, True, d.reasons + ["budget: not among the riskiest escalations"], d.failed_gates, d.risk, d.adr_id))
        else:
            out.append(d)
    return out
