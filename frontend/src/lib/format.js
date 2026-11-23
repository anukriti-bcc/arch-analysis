// Small display helpers. Dates are formatted in UTC so output does not depend
// on the viewer's time zone (commit dates are what matters, not "where you are").

export function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

export function formatFixed(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

export function formatInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Math.round(Number(value)).toLocaleString("en-US");
}

export function plural(n, singular, pluralForm) {
  return `${n} ${n === 1 ? singular : pluralForm || `${singular}s`}`;
}

export function shortSha(sha) {
  return sha ? String(sha).slice(0, 8) : "";
}

export const INACTIVE_ADR_STATUSES = ["superseded", "deprecated", "rejected"];

export function isActiveAdrStatus(status) {
  return !INACTIVE_ADR_STATUSES.includes(String(status || "").toLowerCase());
}

// Escalation policy routes (backend/analysis/policy/gated.py) and the readability gates that can send a finding to the model.
export const ROUTE_LABELS = {
  direct_structural: {
    title: "Resolved structurally",
    detail: "No active decision record is about this dependency and the history shows nothing ambiguous, so the structural verdict stands.",
  },
  direct_code: {
    title: "Resolved by code reading the ADR",
    detail: "An active ADR is about this dependency and every readability check passed, so code applied the ADR's stance. No model was needed.",
  },
  escalate: {
    title: "Sent to the model",
    detail: "The evidence is not enough to decide without a model, or the code reading of the ADR cannot be trusted.",
  },
};

export const GATE_LABELS = {
  G_clear: "The code reader reached no clear verdict",
  G_section: "The ADR has no recognisable Decision section",
  G_polarity: "Both prohibiting and permitting wording",
  G_negation: "A negation inside a decision read as permitting",
  G_anchor: "No stance sentence names both modules",
  G_temporal: "Date or time wording the reader cannot fully explain",
  G_conditions: "Conditional or hedged wording",
  G_subject: "The decision also covers other modules",
  G_single: "Another active ADR also governs this dependency",
  G_scope: "No strongly scoped ADR to read",
};

export function gateLabel(gate) {
  return GATE_LABELS[gate] || gate;
}

export function policyLabel(policy) {
  if (policy === "gated") return "M8 readability-gated policy";
  if (policy === "v1") return "v1 policy (M7: every finding with an active ADR escalates)";
  return null;
}

export const MATCH_REASON_LABELS = {
  rule_id: "names the triggered rule",
  file_names: "names both files",
  component_types: "mentions both layers",
  commit_reference: "cited by the introducing commit",
};

export const METHOD_LABELS = {
  M1_static: "M1 Static rules",
  M2_llm_only: "M2 LLM-only",
  M3_full_hybrid: "M3 Full hybrid",
  M4_generic_selective_mean: "M4 Generic selective (mean of seeds)",
  M5_evidence_guided: "M5 Evidence-guided (v1 policy)",
  M6_deterministic_adr: "M6 Code-only ADR reader",
  M7_extract_compute: "M7 Extract-then-compute",
  M8_gated: "M8 Readability-gated",
  M8_gated_attr: "M8 Gated + attribution (proposed)",
  A1_no_history: "A1 No evolution evidence",
  A2_no_intent: "A2 No intent evidence",
};

// The method the project proposes as its final approach (what the product runs by default).
export const PROPOSED_METHOD = "M8_gated_attr";

export function methodLabel(method) {
  if (METHOD_LABELS[method]) return METHOD_LABELS[method];
  const seed = /^M4_generic_selective_s(\d+)$/.exec(method || "");
  return seed ? `M4 Generic selective (seed ${seed[1]})` : method;
}

// Short chart/column label. M8 and M8+attr need distinct labels, otherwise both read "M8".
const SHORT_OVERRIDES = { M8_gated_attr: "M8+attr" };

export function methodShort(method) {
  if (SHORT_OVERRIDES[method]) return SHORT_OVERRIDES[method];
  const m = /^([A-Z]\d)/.exec(method || "");
  return m ? m[1] : method;
}
