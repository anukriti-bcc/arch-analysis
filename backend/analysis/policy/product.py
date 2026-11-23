"""Which escalation policy the PRODUCT (API + UI) runs, and a single decision shape for both.

The research has two policies (both frozen, neither edited here):

  gated  analysis/policy/gated.py       policy v2 = method M8. Confirmed on fresh seeds 41-43 (docs/GATED_POLICY_RESULTS.md).
  v1     analysis/policy/escalation.py  policy v1 = methods M5/M7. Escalates every finding with an active relevant ADR.

The report's headline result is about M8, so M8 is the DEFAULT. v1 stays available for comparison and for the
tests that pin its behaviour:

    ESCALATION_POLICY=gated   (default)
    ESCALATION_POLICY=v1

This module only adapts. It does not change routing, gates or thresholds. Both policies are reduced to one
`ProductDecision` that keeps the three keys the API and UI already used (`escalate`, `direct_verdict`, `reasons`)
and adds what M8 knows: the route taken, the readability gates that failed, and the ADR that was read.

Routes (same names as the experiments, so a demo finding can be matched to a benchmark row):

  direct_structural  resolved from structure + intent + history; no ADR needed and no model
  direct_code        resolved by CODE reading the ADR, every readability gate passed; no model
  escalate           sent to the model (it extracts facts from the ADR, code computes the verdict)

v1 can only produce direct_structural and escalate, because it has no code reader.

Not changed by this module: the product resolves an escalated finding as method M7 does (see api/routes/analyze.py),
which is also what M8 does for its escalations. The stance-attribution check (M8_gated_attr, analysis/semantic/attribution.py,
confirmed on fresh seeds in docs/GATED_POLICY_RESULTS.md) is applied to every extraction BY DEFAULT; set ATTRIBUTION_CHECK=off
to run plain M8 (for example to show the mixed-decision weakness it fixes). It changes no routing and makes no extra model call.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from analysis.evidence.aggregator import EvidenceBundle
from analysis.policy.escalation import EvidenceGuidedPolicy
from analysis.policy.gated import DIRECT_CODE, DIRECT_STRUCTURAL, ESCALATE, ReadabilityGatedPolicy

POLICY_ENV = "ESCALATION_POLICY"
GATED, V1 = "gated", "v1"
DEFAULT_POLICY = GATED
POLICIES = (GATED, V1)


class PolicyConfigError(ValueError):
    """ESCALATION_POLICY holds a value that names no policy."""


@dataclass
class ProductDecision:
    policy: str                       # "gated" or "v1"
    route: str                        # direct_structural | direct_code | escalate
    escalate: bool
    direct_verdict: Optional[str]     # "violation" / "justified" when not escalating, else None
    reasons: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)
    adr_id: Optional[str] = None      # the ADR the code reader or gates looked at (gated only)

    def to_dict(self) -> dict:
        return {
            "policy": self.policy, "route": self.route, "escalate": self.escalate,
            "direct_verdict": self.direct_verdict, "reasons": self.reasons,
            "failed_gates": self.failed_gates, "adr_id": self.adr_id,
        }


class _V1:
    name = V1

    def __init__(self) -> None:
        self._policy = EvidenceGuidedPolicy()

    def decide(self, bundle: EvidenceBundle) -> ProductDecision:
        d = self._policy.decide(bundle)
        return ProductDecision(V1, ESCALATE if d.escalate else DIRECT_STRUCTURAL, d.escalate, d.direct_verdict, d.reasons)


class _Gated:
    name = GATED

    def __init__(self) -> None:
        self._policy = ReadabilityGatedPolicy()

    def decide(self, bundle: EvidenceBundle) -> ProductDecision:
        d = self._policy.decide(bundle)
        verdict = None
        if not d.escalate:
            verdict = "violation" if d.predicted_violation else "justified"
        return ProductDecision(GATED, d.route, d.escalate, verdict, d.reasons, d.failed_gates, d.adr_id)


ATTRIBUTION_ENV = "ATTRIBUTION_CHECK"
_ON, _OFF = {"on", "1", "true", "yes"}, {"off", "0", "false", "no"}


def attribution_enabled() -> bool:
    """ATTRIBUTION_CHECK=on|off (default on). Read per call. A value that is neither is a configuration error, not a silent default."""
    raw = os.environ.get(ATTRIBUTION_ENV, "").strip().lower()
    if not raw or raw in _ON:
        return True
    if raw in _OFF:
        return False
    raise PolicyConfigError(f"{ATTRIBUTION_ENV}={raw!r} is not valid; use on or off.")


def policy_name_from_env() -> str:
    raw = os.environ.get(POLICY_ENV, "").strip().lower()
    if not raw:
        return DEFAULT_POLICY
    if raw not in POLICIES:
        raise PolicyConfigError(f"{POLICY_ENV}={raw!r} is not a policy; use one of: {', '.join(POLICIES)}.")
    return raw


def policy_from_env():
    """Read per call (not at import), so a test or a restart-free demo can switch the setting."""
    return _Gated() if policy_name_from_env() == GATED else _V1()
