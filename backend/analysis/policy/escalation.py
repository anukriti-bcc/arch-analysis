"""Evidence-guided escalation policy (Milestone 5) — the "Evidence Sufficient?"
diamond of the synopsis workflow.

Given the evidence gathered for a structural violation, decide whether the
deterministic verdict ("violation") can stand on its own or whether the case is
ambiguous enough to justify the cost of an LLM call.

The policy is a short list of explicit, individually switchable rules, so each
can be tested, explained at a viva, and ablated in the evaluation:

  INTENT rules (architectural intent evidence)
    I1  an ACTIVE decision record is relevant to this dependency
        -> escalate: only semantic reading can tell whether it authorises
           this specific dependency (scope, conditions, dates).
    I2  relevant records exist but ALL are inactive (superseded / rejected /
        deprecated) -> no authorising intent -> direct verdict, no LLM.

  HISTORY rules (evolution evidence)
    H1  the introducing commit describes the change as temporary/workaround
    H2  the introducing commit uses migration/legacy/transition language
    H3  the dependency was removed and later reintroduced
        -> escalate: history suggests a possibly deliberate, transitional
           arrangement that the structure alone cannot classify.
    (History also acts earlier, inside evidence aggregation: a commit that
    cites an ADR id pulls that record into rule I1, even if its wording shares
    nothing with the dependency.)

  Otherwise: evidence is sufficient -> direct verdict "violation".

The thresholds here are design choices made BEFORE seeing test-split results;
see experiments/ for how they are evaluated (dev/test split, ablations).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from analysis.evidence.aggregator import EvidenceBundle


@dataclass
class PolicyDecision:
    escalate: bool
    direct_verdict: str | None  # "violation" when not escalating
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"escalate": self.escalate, "direct_verdict": self.direct_verdict, "reasons": self.reasons}


class EvidenceGuidedPolicy:
    def __init__(self, use_intent: bool = True, use_history: bool = True):
        self.use_intent = use_intent
        self.use_history = use_history

    def decide(self, bundle: EvidenceBundle) -> PolicyDecision:
        reasons: list[str] = []

        if self.use_intent and bundle.adrs:
            active = [m for m in bundle.adrs if m.adr.is_active]
            if active:
                reasons.append("I1: active decision record(s) relevant: " + ", ".join(m.adr.id for m in active))
            else:
                return PolicyDecision(
                    False, "violation",
                    ["I2: relevant records are all inactive (" + ", ".join(f"{m.adr.id}={m.adr.status}" for m in bundle.adrs) + ")"],
                )

        ev = bundle.evolution
        if self.use_history and ev and ev.get("available") and ev.get("introducing_commit"):
            sig = ev.get("message_signals", {})
            if sig.get("temporary_language"):
                reasons.append("H1: introducing commit describes the change as temporary")
            if sig.get("migration_language"):
                reasons.append("H2: introducing commit mentions migration/legacy/transition")
            if ev.get("reintroduced"):
                reasons.append("H3: dependency was removed and later reintroduced")

        if reasons:
            return PolicyDecision(True, None, reasons)
        return PolicyDecision(False, "violation", ["evidence sufficient: no relevant active intent and no ambiguity signal in history"])
